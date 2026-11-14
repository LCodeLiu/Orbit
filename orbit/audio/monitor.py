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

"""空闲实时监听。

复用与 Recorder 相同的 WASAPI 回环端点：
读取 → 解码 → 计算电平/波形 → 发信号。
录音开始时会停止，避免两个采集流同时占用设备。

线程安全要点（曾两次导致打包程序EXE“未响应”）：
- 使用进程共享的 PyAudio 实例，流的创建/关闭在 stream_guard 内串行，
  且不 terminate()（见 portaudio.py）；
- stop() 不 join 工作线程：GUI 线程同步等待 PortAudio 释放会卡死消息循环；
- 读取用 get_read_available() 轮询而非阻塞 read()，设备静音时也能
  每 ~20ms 检查停止标志并自行退出。
"""

from __future__ import annotations

import logging
import threading
import time

import numpy as np
from PySide6.QtCore import QObject, Signal

from orbit.audio.analysis import block_levels, decode_to_float, spectrum_bands
from orbit.audio.formats import get_sample_format
from orbit.audio.portaudio import (
    note_stream_closed,
    note_stream_opened,
    stream_guard,
)

log = logging.getLogger(__name__)

_VISUAL_INTERVAL = 0.066  # ~22 fps，足够顺滑且不占 CPU
_POLL_SECONDS = 0.02


class LiveMonitor(QObject):
    """后台监听回环设备并以信号推送可视化数据。"""

    # {"samples": np.ndarray, "peaks": list, "rms": list, "sample_rate": int}
    frame_ready = Signal(object)
    state_changed = Signal(bool, str)  # active, message

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._lock = threading.Lock()
        self._stop_event: threading.Event | None = None
        self._device_key: tuple[int, int, int] | None = None

    @property
    def running(self) -> bool:
        with self._lock:
            return self._stop_event is not None

    def start(self, device_index: int, channels: int, sample_rate: int) -> bool:
        """启动监听；设备参数变化时替换旧线程（不等待其退出）。"""
        key = (int(device_index), int(channels), int(sample_rate))
        with self._lock:
            if self._stop_event is not None and self._device_key == key:
                return True
            if self._stop_event is not None:
                # 旧线程自行收尾；共享模式下两个回环流可短暂并存
                self._stop_event.set()
            stop_event = threading.Event()
            self._stop_event = stop_event
            self._device_key = key
            threading.Thread(
                target=self._run,
                args=(key, stop_event),
                name="LiveMonitor",
                daemon=True,
            ).start()
        log.debug(
            "实时监听已启动：device=%d %dHz/%dch",
            key[0],
            key[2],
            key[1],
        )
        self.state_changed.emit(True, "实时监听中")
        return True

    def stop(self) -> None:
        """请求停止。立即返回"""
        with self._lock:
            was_running = self._stop_event is not None
            if was_running:
                self._stop_event.set()
                self._stop_event = None
                self._device_key = None
        if was_running:
            log.debug("实时监听已请求停止")
            self.state_changed.emit(False, "")

    def restart(self, device_index: int, channels: int, sample_rate: int) -> bool:
        self.stop()
        return self.start(device_index, channels, sample_rate)

    # ------------------------------------------------------------------
    def _run(self, key: tuple[int, int, int], stop_event: threading.Event) -> None:
        device_index, channels, sample_rate = key
        stream = None
        pa = None
        registered = False
        try:
            import pyaudiowpatch as pyaudio

            sample_format = get_sample_format(32)  # 共享混音原生浮点格式
            with stream_guard():
                # 本线程自建实例：PortAudio 的 WASAPI host 线程亲和，
                # 跨线程使用同一实例开流会返回 -9999
                pa = pyaudio.PyAudio()
                try:
                    info = pa.get_device_info_by_index(device_index)
                except Exception:
                    log.debug("监听设备已不可用：%d", device_index)
                    return
                if not info.get("isLoopbackDevice"):
                    log.debug("设备不是回环端点，跳过监听")
                    return
                block_frames = max(256, min(4096, int(sample_rate * 0.02)))
                # 先占位再开流：回环设备同时只允许一个流，若等 pa.open()
                # 返回后才登记，录音线程会看到“空闲”并挤进来撞出 -9999
                note_stream_opened()
                registered = True
                stream = pa.open(
                    format=getattr(pyaudio, sample_format.pyaudio_attr),
                    channels=channels,
                    rate=sample_rate,
                    input=True,
                    input_device_index=device_index,
                    frames_per_buffer=block_frames,
                    start=False,
                )
                stream.start_stream()
            if stop_event.is_set():
                return

            tail = np.zeros(2048, dtype=np.float32)
            last_emit = 0.0
            while not stop_event.is_set():
                try:
                    available = stream.get_read_available()
                except OSError as exc:
                    log.debug("监听状态查询失败，停止：%s", exc)
                    break
                if available < block_frames:
                    # 轮询等待：最迟 ~20ms 后就能响应停止标志
                    stop_event.wait(_POLL_SECONDS)
                    continue
                try:
                    raw = stream.read(block_frames, exception_on_overflow=False)
                except OSError as exc:
                    log.debug("监听读取失败，停止：%s", exc)
                    break
                if not raw or stop_event.is_set():
                    continue
                frames = decode_to_float(raw, sample_format, channels)
                if frames.size == 0:
                    continue
                mono = frames.mean(axis=1, dtype=np.float32)
                tail = mono.copy()
                now = time.monotonic()
                if now - last_emit < _VISUAL_INTERVAL:
                    continue
                last_emit = now
                peaks, rms = block_levels(frames)
                spectrum = spectrum_bands(tail, sample_rate)
                self.frame_ready.emit(
                    {
                        "samples": tail.copy(),
                        "peaks": peaks,
                        "rms": rms,
                        "sample_rate": sample_rate,
                        "spectrum": spectrum,
                    }
                )
        except Exception as exc:
            # 监听失败不影响主功能，只记一次
            log.debug("实时监听异常：%s", exc)
        finally:
            # 全部在工作线程内释放，GUI 线程从不等待这里
            if stream is not None:
                with stream_guard():
                    try:
                        if stream.is_active():
                            stream.stop_stream()
                    except Exception:
                        pass
                    try:
                        stream.close()
                    except Exception:
                        pass
            # 递减以“占位过”为准：pa.open() 失败时 stream 为空，
            # 但占位已经发生，必须撤销，否则计数泄漏会永久阻塞录音
            if registered:
                note_stream_closed()
            # 必须 terminate 本线程的 PyAudio 实例：不释放实例，PortAudio
            # 的 WASAPI host 状态会残留在监听线程上，后续任一线程再
            # 初始化/开流都会得到 -9999（实测监听停止后录音无法开流）。
            # 本线程实例 terminate 是安全的——它不共享、且全程在
            # stream_guard 串行化下与别的线程错开。
            if pa is not None:
                with stream_guard():
                    try:
                        pa.terminate()
                    except Exception:
                        log.debug("释放监听 PyAudio 实例失败", exc_info=True)
            with self._lock:
                if self._stop_event is stop_event:
                    self._stop_event = None
                    self._device_key = None
