# Copyright 2026 LCode
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""WASAPI Loopback 录音引擎。

线程模型：
- GUI 线程只负责发指令与接收 Qt 信号；
- 采集线程持有独立的 PyAudio 实例；
- PortAudio 回调只把 bytes 放入有界队列，绝不写磁盘；
- 采集线程负责写文件、统计、自动分割；
- 需要 FFmpeg 的格式由单线程执行器顺序转码，保留源 WAV 以防失败。

这样可避免 UI 卡顿，也能在磁盘短时抖动时用队列吸收数据。
"""

from __future__ import annotations

import ctypes
import logging
import os
import queue
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, Signal

from orbit.audio.analysis import block_levels, decode_to_float
from orbit.audio.ffmpeg import inspect_ffmpeg, transcode
from orbit.audio.formats import (
    get_output_format,
    get_sample_format,
    validate_rate_for_format,
)
from orbit.audio.portaudio import (
    note_stream_closed,
    note_stream_opened,
    stream_guard,
    wait_until_idle,
)
from orbit.audio.sinks import (
    BaseSink,
    SinkCapacityError,
    create_direct_sink,
    create_temp_wav,
)
from orbit.constants import VERSION
from orbit.models import RecordingRequest, RecordingResult
from orbit.util.naming import unique_path

log = logging.getLogger(__name__)

VISUAL_SAMPLES = 4096


class RecordingCancelled(Exception):
    """用户在开流等待期间取消录音：属于正常流程，不作为错误上报。"""


class Recorder(QObject):
    # state, 人类可读说明
    state_changed = Signal(str, str)
    started = Signal(object)
    paused_changed = Signal(bool)
    stats_updated = Signal(object)
    visual_updated = Signal(object)
    segment_started = Signal(str, int)
    file_ready = Signal(str)
    processing = Signal(str, float)
    error = Signal(str, str)
    device_lost = Signal(str)
    finished = Signal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._request: RecordingRequest | None = None
        self._lock = threading.RLock()
        self._result_lock = threading.Lock()
        self._result = RecordingResult()

        self._queue: queue.Queue[bytes] = queue.Queue()
        self._executor: ThreadPoolExecutor | None = None
        self._stream = None
        self._pa = None
        self._pa_continue = 0
        self._pa_complete = 0

        self._sink: BaseSink | None = None
        self._segment_final: Path | None = None
        self._segment_temp: Path | None = None
        self._segment_index = 0
        self._segment_frames = 0
        self._segment_started_at = 0.0
        self._reserved: set[Path] = set()
        self._completed_bytes = 0

        self._actual_rate = 0
        self._channels = 0
        self._buffer_frames = 0
        self._latency_ms = 0.0
        self._portaudio_version = ""

        self._dropped_blocks = 0
        self._dropped_frames = 0
        self._overflows = 0
        self._logged_dropped_frames = 0
        self._logged_overflows = 0
        self._last_callback = 0.0
        self._last_emit = 0.0
        self._last_peak = 0.0
        self._segment_peak = 0.0
        self._mono_tail = np.zeros(0, dtype=np.float32)
        self._fatal_error: tuple[str, str] | None = None
        self._auto_stop_reason = ""
        self._silent_since = None
        self._sleep_prevented = False

    # ------------------------------------------------------------------ 公共 API
    @property
    def active(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    @property
    def paused(self) -> bool:
        return self._pause_event.is_set()

    def start(self, request: RecordingRequest) -> bool:
        with self._lock:
            if self.active:
                self.error.emit("无法开始", "已有录音正在进行。")
                return False

            fmt = get_output_format(request.output_format)
            if request.bit_depth not in fmt.allowed_depths:
                self.error.emit(
                    "参数不支持",
                    f"{fmt.label} 不支持 {request.bit_depth}-bit，请重新选择位深。",
                )
                return False
            rate = request.sample_rate or request.device.sample_rate
            ok, message = validate_rate_for_format(fmt, rate)
            if not ok:
                self.error.emit("采样率不支持", message)
                return False
            if fmt.requires_ffmpeg:
                info = inspect_ffmpeg(request.ffmpeg_path)
                if not info.available or not info.supports(fmt):
                    self.error.emit(
                        "需要 FFmpeg",
                        info.error
                        or f"当前 FFmpeg 缺少 {fmt.codec} 编码器，无法输出 {fmt.label}。",
                    )
                    return False

            self._request = request
            self._stop_event.clear()
            self._pause_event.clear()
            self._queue = queue.Queue()
            self._result = RecordingResult()
            self._executor = ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="AudioEncode"
            )
            self._sink = None
            self._segment_final = None
            self._segment_temp = None
            self._segment_index = 0
            self._segment_frames = 0
            self._reserved = set()
            self._completed_bytes = 0
            self._dropped_blocks = 0
            self._dropped_frames = 0
            self._overflows = 0
            self._logged_dropped_frames = 0
            self._logged_overflows = 0
            self._last_callback = time.monotonic()
            self._last_emit = 0.0
            self._last_peak = 0.0
            self._segment_peak = 0.0
            self._mono_tail = np.zeros(0, dtype=np.float32)
            self._fatal_error = None
            self._auto_stop_reason = ""
            self._silent_since = None
            self._thread = threading.Thread(
                target=self._run, name="AudioCapture", daemon=True
            )
            self.state_changed.emit("starting", "正在打开 WASAPI 回环流…")
            self._thread.start()
            return True

    def pause(self) -> None:
        if not self.active or self.paused or self._stop_event.is_set():
            return
        self._pause_event.set()
        self.state_changed.emit("paused", "录音已暂停")
        self.paused_changed.emit(True)
        log.info("录音暂停")

    def resume(self) -> None:
        if not self.active or not self.paused or self._stop_event.is_set():
            return
        self._pause_event.clear()
        self._last_callback = time.monotonic()
        self.state_changed.emit("recording", "正在采集系统音频")
        self.paused_changed.emit(False)
        log.info("录音继续")

    def toggle_pause(self) -> None:
        if self.paused:
            self.resume()
        else:
            self.pause()

    def stop(self, reason: str = "") -> None:
        if not self.active:
            return
        if self._stop_event.is_set():
            return
        if reason:
            self._auto_stop_reason = reason
        self._stop_event.set()
        self.state_changed.emit("stopping", "正在完成录音并写入文件…")
        log.info("请求停止录音%s", f"（{reason}）" if reason else "")

    # -------------------------------------------------------------- PortAudio 回调
    def _audio_callback(self, in_data, frame_count, time_info, status):  # noqa: ANN001
        """必须极快返回：只做入队/计数，不做文件 IO 或日志。"""
        self._last_callback = time.monotonic()
        if status:
            self._overflows += 1
        if not self._pause_event.is_set():
            try:
                self._queue.put_nowait(in_data)
            except queue.Full:
                self._dropped_blocks += 1
                self._dropped_frames += frame_count
        if self._stop_event.is_set():
            return (None, self._pa_complete)
        return (None, self._pa_continue)

    # ------------------------------------------------------ 开流（含重试）
    def _discard_segment(self) -> None:
        """回滚当前分段：关写入端并删除半成品，避免留下空文件。"""
        sink = self._sink
        if sink is not None:
            try:
                sink.abort()
            except Exception:
                log.debug("回滚分段时关闭写入端失败", exc_info=True)
            self._sink = None
        temp = self._segment_temp
        if temp is not None:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass
            self._segment_temp = None
        self._segment_final = None

    def _open_stream_with_retry(self, pyaudio_fmt: int, request: RecordingRequest) -> None:
        """打开并启动录音流，容忍实时监听尚未释放设备的短暂窗口。

        WASAPI 回环同一设备同时只允许一个流：监听线程的流若还开着，
        Pa_OpenStream / Pa_StartStream 会返回 -9999（Unanticipated host
        error）。因此每次尝试前先等待监听释放，失败后重试。

        重试必须在工作线程执行；stream_guard 只覆盖单次开流，否则锁被
        录音线程占住，监听线程就无法关闭它的流，会互相等死。
        """
        attempts = 4
        last_error: Exception | None = None
        for attempt in range(attempts):
            if self._stop_event.is_set():
                raise RecordingCancelled()
            if not wait_until_idle(timeout=1.5) and attempt < attempts - 1:
                log.debug("等待音频设备空闲超时，第 %d 次尝试前继续", attempt + 1)

            stream = None
            registered = False
            # 建写入端放在锁外：FLAC/WAV 打开文件可能有磁盘延迟，
            # 持有 stream_guard 会阻塞监听线程释放它的流
            self._open_segment()
            try:
                with stream_guard():
                    # 先占位再开流：监听线程的流若还开着，Pa_OpenStream 会返回 -9999
                    note_stream_opened()
                    registered = True
                    stream = self._pa.open(
                        format=pyaudio_fmt,
                        channels=self._channels,
                        rate=self._actual_rate,
                        input=True,
                        input_device_index=request.device.index,
                        frames_per_buffer=self._buffer_frames,
                        stream_callback=self._audio_callback,
                        start=False,
                    )
                    stream.start_stream()
            except OSError as exc:
                if registered:
                    if stream is not None:
                        try:
                            stream.close()
                        except Exception:
                            log.debug("回滚时关闭录音流失败", exc_info=True)
                    note_stream_closed()
                self._discard_segment()
                message = str(exc)
                code = getattr(exc, "errno", None)
                if code == -9997 or "Invalid sample rate" in message:
                    raise RuntimeError(
                        f"设备不支持 {self._actual_rate:,} Hz 采样率。"
                        "WASAPI 共享回环通常只能使用设备当前的混音采样率"
                        f"（{request.device.sample_rate:,} Hz）。\n"
                        "本应用不会为了启动而自动重采样，请选择“原生”采样率。"
                    ) from exc
                if code == -9998 or "Invalid number of channels" in message:
                    raise RuntimeError(
                        f"设备不支持 {self._channels} 声道输入。"
                        f"该回环端点原生为 {request.device.channels} 声道，"
                        "请选择原生声道数。"
                    ) from exc
                last_error = exc
                if attempt < attempts - 1:
                    log.warning(
                        "打开录音流失败（%s），第 %d/%d 次重试",
                        message,
                        attempt + 1,
                        attempts - 1,
                    )
                    time.sleep(0.2)
                    continue
                raise RuntimeError(
                    f"无法打开录音流：{message}\n"
                    "音频设备可能正被其他程序占用，请关闭实时监听或其他录音软件后重试。"
                ) from exc
            except Exception:
                # 非 OSError 的意外失败同样要回滚，避免泄漏流/半成品文件
                if registered:
                    try:
                        stream.close()
                    except Exception:
                        log.debug("回滚时关闭录音流失败", exc_info=True)
                    note_stream_closed()
                self._discard_segment()
                raise

            self._stream = stream
            actual_rate = int(getattr(stream, "_rate", self._actual_rate))
            if actual_rate != self._actual_rate:
                log.warning(
                    "PortAudio 实际采样率 %d 与请求 %d 不一致",
                    actual_rate,
                    self._actual_rate,
                )
                self._actual_rate = actual_rate
            try:
                self._latency_ms = float(stream.get_input_latency()) * 1000.0
            except Exception:
                self._latency_ms = request.buffer_ms
            return

        # 理论上不可达：最后一次尝试要么成功返回，要么抛出异常
        raise RuntimeError(f"无法打开录音流：{last_error}")

    # ---------------------------------------------------------------------- 主循环
    def _run(self) -> None:
        opened = False
        try:
            import pyaudiowpatch as pyaudio

            self._pa_continue = pyaudio.paContinue
            self._pa_complete = pyaudio.paComplete
            request = self._request
            assert request is not None
            fmt = get_output_format(request.output_format)
            self._actual_rate = int(request.sample_rate or request.device.sample_rate)
            self._channels = int(request.channels or request.device.channels)
            if self._channels > request.device.channels:
                raise RuntimeError(
                    f"设备“{request.device.clean_name}”最多支持 "
                    f"{request.device.channels} 声道。"
                )
            if self._channels < 1:
                raise RuntimeError("声道数无效。")
            self._buffer_frames = min(
                8192,
                max(128, round(self._actual_rate * request.buffer_ms / 1000)),
            )
            block_seconds = self._buffer_frames / self._actual_rate
            self._queue = queue.Queue(maxsize=min(512, max(48, int(3.0 / block_seconds))))

            # PortAudio 的 WASAPI host 线程亲和： recorder 线程必须自己创建实例
            with stream_guard():
                self._pa = pyaudio.PyAudio()
                try:
                    device_info = self._pa.get_device_info_by_index(request.device.index)
                except Exception as exc:
                    raise RuntimeError(
                        "音频设备已不可用（可能被拔出或禁用），请刷新设备列表。"
                    ) from exc
                if not device_info.get("isLoopbackDevice"):
                    raise RuntimeError("所选设备不是 WASAPI 回环端点，请重新扫描设备。")
                try:
                    self._portaudio_version = pyaudio.get_portaudio_version_text()
                except Exception:
                    self._portaudio_version = ""

            sample_format = get_sample_format(request.bit_depth)
            pyaudio_fmt = getattr(pyaudio, sample_format.pyaudio_attr)

            log.info(
                "打开回环流：device=[%d] %s, %d Hz, %d ch, %s, buffer=%d frames (%.1f ms)",
                request.device.index,
                request.device.clean_name,
                self._actual_rate,
                self._channels,
                sample_format.label,
                self._buffer_frames,
                request.buffer_ms,
            )
            self._open_stream_with_retry(pyaudio_fmt, request)
            opened = True
            self._prevent_system_sleep()
            info = {
                "backend": "WASAPI Loopback（共享模式）",
                "portaudio": self._portaudio_version,
                "device": request.device.clean_name,
                "device_index": request.device.index,
                "device_native_rate": request.device.sample_rate,
                "device_native_channels": request.device.channels,
                "sample_rate": self._actual_rate,
                "channels": self._channels,
                "bit_depth": request.bit_depth,
                "sample_format": sample_format.label,
                "buffer_frames": self._buffer_frames,
                "buffer_ms": round(self._buffer_frames / self._actual_rate * 1000, 2),
                "latency_ms": round(self._latency_ms, 2),
                "output_format": fmt.label,
                "output_path": str(self._segment_final or ""),
                "ffmpeg": bool(fmt.requires_ffmpeg),
            }
            log.info(
                "音频流已启动：实际 %d Hz / %d ch / %s / 缓冲 %d 帧 / 延迟 %.1f ms",
                self._actual_rate,
                self._channels,
                sample_format.label,
                self._buffer_frames,
                self._latency_ms,
            )
            log.info("PortAudio 版本：%s", self._portaudio_version or "未知")
            self.started.emit(info)
            self.state_changed.emit("recording", "正在采集系统音频")
            self._loop()
        except RecordingCancelled:
            # 用户在开流等待期间点了停止：静默收尾，不报错误
            log.info("录音在打开音频流前被取消")
        except Exception as exc:
            log.exception("录音线程异常")
            detail = str(exc)
            if "采样率" in detail:
                title = "采样率不支持"
            elif "声道" in detail:
                title = "声道数不支持"
            elif "设备已不可用" in detail:
                title = "音频设备不可用"
            else:
                title = "录音失败"
                detail += "\n\n请检查播放设备是否启用，或点击刷新后重新选择设备。"
            self._fatal_error = (title, detail)
            self.error.emit(*self._fatal_error)
        finally:
            self._shutdown(opened)

    def _loop(self) -> None:
        request = self._request
        assert request is not None
        last_watchdog_log = 0.0
        while True:
            if self._stop_event.is_set() and self._queue.empty():
                break
            try:
                chunk = self._queue.get(timeout=0.1)
            except queue.Empty:
                if self._stop_event.is_set():
                    # 给 PortAudio 回调最后一点时间投递当前缓冲
                    time.sleep(0.06)
                    if self._queue.empty():
                        break
                    continue
                now = time.monotonic()
                # 暂停时不判断；WASAPI 在静音时也会持续送静音帧
                if (
                    not self._pause_event.is_set()
                    and now - self._last_callback > 6.0
                ):
                    if now - last_watchdog_log > 10.0:
                        last_watchdog_log = now
                        log.warning("超过 6 秒未收到回环数据，判定设备已断开")
                    self.device_lost.emit("音频设备长时间无响应，可能已断开。")
                    self._fatal_error = (
                        "设备连接中断",
                        "音频设备已断开或驱动无响应。已保存此前的录音。",
                    )
                    self.stop("设备断开")
                    break
                continue

            if self._pause_event.is_set():
                continue
            # 每个音频块重新计算峰值，否则 _last_peak 一旦被非零值锁住就永远不回零
            self._last_peak = 0.0
            try:
                self._write_chunk(chunk)
            except SinkCapacityError as exc:
                log.error("WAV 容量达到上限：%s", exc)
                self.error.emit("文件达到 WAV 4 GB 上限", str(exc))
                self.stop("WAV 容量上限")
                break
            except Exception as exc:
                log.exception("写入音频数据失败")
                self._fatal_error = (
                    "写入文件失败",
                    f"{exc}\n磁盘可能已满或保存目录不可写。",
                )
                self.error.emit(*self._fatal_error)
                self.stop("写入失败")
                break

            elapsed = self._elapsed_seconds()
            if request.max_seconds and elapsed >= request.max_seconds:
                log.info("达到最长录制时间 %d 秒，自动停止", request.max_seconds)
                self.stop("已达设定时长")
                # 继续循环以排空队列
            # 无声自动停止：仅当启用时生效
            if (
                request.silent_auto_stop_enabled
                and request.silent_timeout_seconds > 0
                and not self._pause_event.is_set()
            ):
                if self._last_peak <= 0.0001:
                    if getattr(self, "_silent_since", None) is None:
                        self._silent_since = time.monotonic()
                    elif time.monotonic() - self._silent_since >= request.silent_timeout_seconds:
                        log.info("连续 %d 秒无声，自动停止", request.silent_timeout_seconds)
                        self.stop("无声超时")
                else:
                    self._silent_since = None
            if self._should_split():
                self._rotate_segment()

    def _elapsed_seconds(self) -> float:
        with self._result_lock:
            completed = self._result.frames
        current = self._sink.frames_written if self._sink else 0
        return (completed + current) / self._actual_rate if self._actual_rate else 0.0

    def _should_split(self) -> bool:
        request = self._request
        if not request or self._stop_event.is_set():
            return False
        if not self._sink or self._sink.frames_written <= 0:
            return False
        # 分割阈值针对“当前分段”，不能用累计时长，否则新分段会立刻再次触发
        segment_seconds = (
            self._sink.frames_written / self._actual_rate if self._actual_rate else 0.0
        )
        if request.split_seconds and segment_seconds >= request.split_seconds:
            return True
        if request.split_bytes and self._sink.size_bytes >= request.split_bytes:
            return True
        return False

    def _write_chunk(self, chunk: bytes) -> None:
        sink = self._sink
        if sink is None:
            return
        sink.write(chunk)
        frames = decode_to_float(chunk, sink.sample_format, self._channels)
        if frames.size == 0:
            return
        peaks, rms = block_levels(frames)
        mono = frames.mean(axis=1, dtype=np.float32)
        if self._mono_tail.size:
            self._mono_tail = np.concatenate((self._mono_tail, mono))[-VISUAL_SAMPLES:]
        else:
            self._mono_tail = mono[-VISUAL_SAMPLES:].copy()
        if peaks:
            self._last_peak = max(self._last_peak, max(peaks))
            self._segment_peak = max(self._segment_peak, max(peaks))

        now = time.monotonic()
        if now - self._last_emit >= 0.05:
            self._last_emit = now
            self._emit_stats(peaks, rms)
            self.visual_updated.emit(
                {
                    "samples": self._mono_tail.copy(),
                    "peaks": peaks,
                    "rms": rms,
                    "sample_rate": self._actual_rate,
                }
            )

    def _emit_stats(self, peaks: list[float] | None = None, rms: list[float] | None = None) -> None:
        if self._overflows and (
            self._logged_overflows == 0
            or self._overflows >= self._logged_overflows + 100
        ):
            self._logged_overflows = self._overflows
            log.warning("检测到 PortAudio 输入溢出（累计 %d 次）", self._overflows)
        drop_threshold = max(1, int(self._actual_rate * 2))
        if self._dropped_frames and (
            self._logged_dropped_frames == 0
            or self._dropped_frames >= self._logged_dropped_frames + drop_threshold
        ):
            self._logged_dropped_frames = self._dropped_frames
            log.warning(
                "写入队列已满，累计丢弃 %d 帧（%d 个数据块）",
                self._dropped_frames,
                self._dropped_blocks,
            )
        sink = self._sink
        with self._result_lock:
            completed_bytes = self._completed_bytes
            total_frames = self._result.frames
        current_frames = sink.frames_written if sink else 0
        stats = {
            "elapsed": self._elapsed_seconds(),
            "frames": total_frames + current_frames,
            "bytes": completed_bytes + (sink.size_bytes if sink else 0),
            "peaks": peaks or [],
            "rms": rms or [],
            "dropped_frames": self._dropped_frames,
            "dropped_blocks": self._dropped_blocks,
            "overflows": self._overflows,
            "queue": self._queue.qsize(),
            "segment": self._segment_index + 1,
            "sample_rate": self._actual_rate,
            "channels": self._channels,
            "buffer_frames": self._buffer_frames,
            "latency_ms": self._latency_ms,
            "output_format": (
                get_output_format(self._request.output_format).label
                if self._request
                else ""
            ),
            "current_file": str(self._segment_final or ""),
            "paused": self._pause_event.is_set(),
        }
        self.stats_updated.emit(stats)

    # ------------------------------------------------------------------ 分段/写入
    def _open_segment(self) -> None:
        request = self._request
        assert request is not None
        fmt = get_output_format(request.output_format)
        split_enabled = bool(request.split_seconds or request.split_bytes)
        stem = request.base_name
        if split_enabled:
            stem = f"{stem}_part{self._segment_index + 1:02d}"
        final_path = unique_path(
            request.output_dir, stem, fmt.extension, self._reserved
        )
        self._reserved.add(final_path)
        self._segment_final = final_path
        self._segment_frames = 0
        self._segment_started_at = time.monotonic()
        self._segment_peak = 0.0
        sample_format = get_sample_format(request.bit_depth)

        if fmt.requires_ffmpeg:
            temp = request.output_dir / f".orbit_tmp_{uuid.uuid4().hex}.wav"
            self._segment_temp = temp
            sink: BaseSink = create_temp_wav(
                temp, self._actual_rate, self._channels, sample_format
            )
        else:
            self._segment_temp = None
            sink = create_direct_sink(
                fmt.key, final_path, self._actual_rate, self._channels, sample_format
            )
        self._sink = sink
        part = self._segment_index + 1 if split_enabled else 1
        self.segment_started.emit(str(final_path), part)
        log.info("录音分段 #%d → %s", part, final_path)
        if split_enabled:
            log.info(
                "自动分割已启用：%s 分钟 / %s MB",
                request.split_seconds // 60 if request.split_seconds else 0,
                request.split_bytes // (1024 * 1024) if request.split_bytes else 0,
            )

    def _rotate_segment(self) -> None:
        if not self._sink:
            return
        log.info("达到分割阈值，切换新文件")
        self._finalize_current_segment()
        self._segment_index += 1
        try:
            self._open_segment()
        except Exception as exc:
            log.exception("创建下一段文件失败")
            self.error.emit("无法创建新文件", str(exc))
            self._fatal_error = ("无法创建新文件", str(exc))
            self.stop("文件创建失败")

    def _finalize_current_segment(self) -> None:
        sink = self._sink
        final_path = self._segment_final
        temp_path = self._segment_temp
        if sink is None or final_path is None:
            return
        frames = sink.frames_written
        if frames <= 0:
            sink.abort()
            if temp_path:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass
            self._sink = None
            return
        request = self._request
        assert request is not None
        # 无声音数据的文件不保存（可选）
        if (
            getattr(request, "discard_silent_files", False)
            and self._segment_peak <= 0.0001
        ):
            log.info("本段无有效声音，按设置丢弃：%s", final_path)
            sink.abort()
            if temp_path:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass
            # part file cleanup
            try:
                sink.part_path.unlink(missing_ok=True)
            except OSError:
                pass
            self._sink = None
            self._segment_final = None
            return
        fmt = get_output_format(request.output_format)
        tags = self._build_tags(final_path, frames)
        try:
            if fmt.requires_ffmpeg:
                source = sink.finalize(None)
                self._segment_temp = None
                with self._result_lock:
                    # 临时 WAV 不计入最终文件大小；转码成功后再累加
                    self._result.frames += frames
                self._submit_transcode(source, final_path, tags, frames, fmt)
            else:
                path = sink.finalize(tags if request.metadata_enabled else None)
                size = path.stat().st_size if path.exists() else 0
                with self._result_lock:
                    self._completed_bytes += size
                    self._result.frames += frames
                    self._result.files.append(path)
                self.file_ready.emit(str(path))
                log.info("录音文件完成：%s", path)
        except Exception as exc:
            log.exception("完成录音分段失败")
            self.error.emit("保存录音失败", str(exc))
            self._fatal_error = ("保存录音失败", str(exc))
            # 不直接删除半成品：尝试把 .part 重命名为可恢复文件
            try:
                part = sink.part_path
                if part.exists() and part.stat().st_size > 0:
                    original = part.name.removesuffix(".part")
                    suffix = Path(original).suffix or final_path.suffix
                    recovery = unique_path(
                        request.output_dir,
                        f"{final_path.stem}_recovered",
                        suffix,
                        self._reserved,
                    )
                    os.replace(part, recovery)
                    with self._result_lock:
                        self._result.preserved_sources.append(recovery)
                        self._result.errors.append(
                            f"{final_path.name}: 封存失败，已保留恢复文件 {recovery.name}"
                        )
                    self.file_ready.emit(str(recovery))
                    log.warning("已保留恢复文件：%s", recovery)
                else:
                    sink.abort()
            except Exception as recovery_exc:
                log.exception("保留恢复文件失败，保留 .part 文件")
                with self._result_lock:
                    self._result.errors.append(
                        f"{final_path.name}: 恢复文件重命名失败，"
                        f"临时文件保留在 {sink.part_path}（{recovery_exc}）"
                    )
            self._stop_event.set()
        finally:
            self._sink = None
            self._segment_final = None

    def _build_tags(self, final_path: Path, frames: int) -> dict[str, str]:
        request = self._request
        if not request or not request.metadata_enabled:
            return {}
        fmt = get_output_format(request.output_format)
        now = datetime.now()
        comment = (
            f"Windows WASAPI Loopback | {self._actual_rate} Hz | "
            f"{request.bit_depth}-bit | {self._channels} ch | {fmt.label} | "
            "无应用层重采样"
        )
        return {
            "title": final_path.stem,
            "artist": request.device.clean_name,
            "album": "系统音频采集",
            "comment": comment,
            "date": now.strftime("%Y-%m-%d"),
            "software": f"Orbit {VERSION}",
            "encoder": f"Orbit {VERSION}",
            "device": request.device.clean_name,
        }

    def _submit_transcode(
        self, source: Path, final_path: Path, tags: dict[str, str], frames: int, fmt
    ) -> None:
        executor = self._executor
        if executor is None:
            raise RuntimeError("转码执行器未初始化")
        duration = frames / self._actual_rate if self._actual_rate else 0.0
        request = self._request
        assert request is not None

        def task() -> None:
            source_consumed = False
            try:
                self.processing.emit(final_path.name, 0.0)
                transcode(
                    source=source,
                    destination=final_path,
                    fmt=fmt,
                    bitrate_kbps=request.bitrate_kbps,
                    metadata=tags,
                    ffmpeg_path=request.ffmpeg_path,
                    sample_rate=self._actual_rate,
                    channels=self._channels,
                    duration_seconds=duration,
                    progress=lambda value: self.processing.emit(final_path.name, value),
                )
                source_consumed = True
                size = final_path.stat().st_size
                with self._result_lock:
                    self._completed_bytes += size
                    self._result.files.append(final_path)
                self.processing.emit(final_path.name, 1.0)
                self.file_ready.emit(str(final_path))
                log.info("转码文件完成：%s", final_path)
            except Exception as exc:
                log.exception("转码失败，保留源 WAV")
                recovery = unique_path(
                    request.output_dir,
                    f"{final_path.stem}_source",
                    ".wav",
                    self._reserved,
                )
                self._reserved.add(recovery)
                source_note = ""
                try:
                    os.replace(source, recovery)
                    source_consumed = True
                    with self._result_lock:
                        self._result.preserved_sources.append(recovery)
                        self._result.errors.append(f"{final_path.name}: {exc}")
                    self.file_ready.emit(str(recovery))
                    source_note = f"源 WAV 已保留：{recovery}"
                except OSError as move_exc:
                    log.exception("保留临时 WAV 失败")
                    source_note = f"临时源 WAV 仍位于：{source}"
                    with self._result_lock:
                        self._result.errors.append(
                            f"{final_path.name}: 转码失败且源文件保留失败：{move_exc}"
                        )
                self.error.emit(
                    "转码失败，原始 WAV 已保留",
                    f"{final_path.name}：{exc}\n\n{source_note}",
                )
            finally:
                # 只有转码成功或已移出临时文件时才删除，失败时绝不丢录音
                if source_consumed:
                    try:
                        source.unlink(missing_ok=True)
                    except OSError:
                        pass

        executor.submit(task)

    # --------------------------------------------------------------------- 收尾
    def _prevent_system_sleep(self) -> None:
        """录音期间阻止系统空闲睡眠；退出时恢复。"""
        if sys.platform != "win32":
            return
        try:
            ES_CONTINUOUS = 0x80000000
            ES_SYSTEM_REQUIRED = 0x00000001
            if ctypes.windll.kernel32.SetThreadExecutionState(
                ES_CONTINUOUS | ES_SYSTEM_REQUIRED
            ):
                self._sleep_prevented = True
                log.debug("已阻止系统在录音期间空闲睡眠")
        except Exception:
            log.debug("设置系统防睡眠失败", exc_info=True)

    def _restore_system_sleep(self) -> None:
        if not self._sleep_prevented or sys.platform != "win32":
            return
        try:
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
            log.debug("已恢复系统空闲睡眠策略")
        except Exception:
            pass
        self._sleep_prevented = False

    def _shutdown(self, opened: bool) -> None:
        self._restore_system_sleep()
        # 先停止回调，再排空队列并封存，避免收尾期间又有新块入队
        if self._stream is not None:
            try:
                if self._stream.is_active():
                    self._stream.stop_stream()
            except Exception:
                log.debug("停止 PortAudio 流时出错", exc_info=True)
        try:
            if self._sink is not None and not self._queue.empty():
                while True:
                    try:
                        chunk = self._queue.get_nowait()
                    except queue.Empty:
                        break
                    if self._pause_event.is_set():
                        continue
                    try:
                        self._write_chunk(chunk)
                    except Exception:
                        log.exception("收尾时写入尾部数据失败")
                        break
            if self._sink is not None:
                self.state_changed.emit("finishing", "正在封存录音文件…")
                self._finalize_current_segment()
        finally:
            if self._executor is not None:
                self.state_changed.emit("finishing", "正在编码 / 写入磁盘…")
                self._executor.shutdown(wait=True)
                self._executor = None
            if self._stream is not None:
                with stream_guard():
                    try:
                        self._stream.close()
                    except Exception:
                        log.debug("关闭 PortAudio 流时出错", exc_info=True)
                self._stream = None
                # 与开流时的登记一一对应，唤醒后续等待者
                note_stream_closed()
            if self._pa is not None:
                with stream_guard():
                    try:
                        self._pa.terminate()
                    except Exception:
                        log.debug("释放 PortAudio 实例时出错", exc_info=True)
                self._pa = None

            with self._result_lock:
                result = self._result
                result.dropped_frames = self._dropped_frames
                result.overflows = self._overflows
                result.elapsed = (
                    result.frames / self._actual_rate if self._actual_rate else 0.0
                )
            if self._fatal_error:
                result.errors.append(self._fatal_error[1])
            log.info(
                "录音结束：%.2f 秒，%d 帧，%d 个文件，丢帧 %d，溢出 %d",
                result.elapsed,
                result.frames,
                len(result.files),
                self._dropped_frames,
                self._overflows,
            )
            if self._queue.qsize():
                log.warning("收尾时队列仍有 %d 个数据块", self._queue.qsize())
            self.finished.emit(result)
            # 便于下一次录音启动；finished 已入 GUI 队列
            self._thread = None
