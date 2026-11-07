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

"""WASAPI Loopback 设备发现。

采用 PyAudioWPatch 暴露的 WASAPI 回环端点。回环端点复用播放设备的格式，

设备枚举会触碰 PortAudio 全局状态，因此：
- 放在后台线程执行，避免阻塞 UI；
- 使用进程共享的 PyAudio 实例（见 portaudio.py），并在 stream_guard
  保护下访问
"""

from __future__ import annotations

import logging
import threading

from PySide6.QtCore import QObject, Signal

from orbit.audio.portaudio import stream_guard
from orbit.models import AudioDevice, DeviceInventory

log = logging.getLogger(__name__)


def enumerate_devices() -> DeviceInventory:
    try:
        import pyaudiowpatch as pyaudio
    except Exception as exc:  # pragma: no cover - 依赖缺失时给出可操作提示
        msg = (
            "无法导入 PyAudioWPatch。请运行：pip install PyAudioWPatch\n"
            f"详细信息：{exc}"
        )
        log.exception("PyAudioWPatch 导入失败")
        return DeviceInventory(error=msg)

    try:
        # PortAudio 的 WASAPI host 线程亲和，且 Pa_Terminate 会动全局状态，
        # 因此本线程自建实例，并在 stream_guard 内完成初始化与释放
        with stream_guard():
            pa = pyaudio.PyAudio()
            try:
                version = str(pyaudio.get_portaudio_version_text())
            except Exception:
                version = ""

            default_index: int | None = None
            try:
                default_info = pa.get_default_wasapi_loopback()
                default_index = int(default_info["index"])
            except Exception as exc:
                log.debug("无法确定默认回环设备：%s", exc)

            devices: list[AudioDevice] = []
            seen: set[tuple[int, str]] = set()
            for info in pa.get_loopback_device_info_generator():
                if not info.get("isLoopbackDevice"):
                    continue
                index = int(info["index"])
                name = str(info["name"]).replace(" [Loopback]", "").strip()
                channels = int(info.get("maxInputChannels") or 0)
                rate = int(round(float(info.get("defaultSampleRate") or 0)))
                if channels <= 0 or rate <= 0:
                    continue
                key = (index, name)
                if key in seen:
                    continue
                seen.add(key)
                devices.append(
                    AudioDevice(
                        index=index,
                        name=name,
                        channels=channels,
                        sample_rate=rate,
                        is_default=index == default_index,
                        host_api="Windows WASAPI",
                        loopback=True,
                    )
                )
            # 与初始化在同一把锁内释放，避免与录音/监听的开流竞争
            try:
                pa.terminate()
            except Exception:
                pass
    except Exception as exc:
        log.exception("枚举音频设备失败")
        return DeviceInventory(error=f"枚举音频设备失败：{exc}")

    devices.sort(key=lambda d: (not d.is_default, d.name.casefold()))
    log.debug(
        "发现 %d 个回环设备，PortAudio=%s，默认=%s",
        len(devices),
        version or "?",
        default_index,
    )
    for device in devices:
        log.debug(
            "  [%d] %s | %d Hz | %d ch | default=%s",
            device.index,
            device.name,
            device.sample_rate,
            device.channels,
            device.is_default,
        )
    if not devices:
        return DeviceInventory(
            default_index=default_index,
            portaudio_version=version,
            error=(
                "未找到 WASAPI 回环设备。请确认已连接/启用播放设备，"
                "并在“声音设置”中允许应用访问音频设备。"
            ),
        )
    return DeviceInventory(
        devices=devices,
        default_index=default_index,
        portaudio_version=version,
    )


class DeviceScanner(QObject):
    """在后台扫描设备，避免 PortAudio 初始化阻塞 UI。"""

    finished = Signal(object)  # DeviceInventory

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    @property
    def busy(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def scan(self) -> bool:
        with self._lock:
            if self.busy:
                return False
            self._thread = threading.Thread(
                target=self._run, name="DeviceScan", daemon=True
            )
            self._thread.start()
            return True

    def _run(self) -> None:
        inventory = enumerate_devices()
        # PySide 会把跨线程信号排队到 GUI 线程
        self.finished.emit(inventory)
