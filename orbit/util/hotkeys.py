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

"""可选的 Windows 全局快捷键。

使用 Win32 RegisterHotKey，不依赖键盘钩子，也不会拦截其他程序的按键。
注册失败（例如被其他软件占用）只记录日志，不影响主程序。
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
import sys

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Signal

log = logging.getLogger(__name__)

WM_HOTKEY = 0x0312
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_NOREPEAT = 0x4000
VK_F9 = 0x78
VK_F10 = 0x79
VK_F11 = 0x7A


class GlobalHotkeys(QObject, QAbstractNativeEventFilter):
    triggered = Signal(str)  # toggle_record / toggle_pause / open_folder

    def __init__(self, app, parent: QObject | None = None) -> None:
        QObject.__init__(self, parent)
        QAbstractNativeEventFilter.__init__(self)
        self._app = app
        self._ids: dict[int, str] = {}
        self._registered = False
        self.errors: list[str] = []

    @property
    def registered(self) -> bool:
        return bool(self._ids)

    def register(self) -> bool:
        if sys.platform != "win32":
            self.errors.append("全局快捷键仅支持 Windows。")
            return False
        if self._registered:
            return bool(self._ids)
        self._registered = True
        self._app.installNativeEventFilter(self)
        combos = (
            ("toggle_record", VK_F9),
            ("toggle_pause", VK_F10),
            ("open_folder", VK_F11),
        )
        try:
            user32 = ctypes.windll.user32
        except Exception as exc:
            self.errors.append(f"无法加载 user32：{exc}")
            return False
        key_names = {VK_F9: "F9", VK_F10: "F10", VK_F11: "F11"}
        for index, (action, vk) in enumerate(combos, start=0xB001):
            ok = user32.RegisterHotKey(
                None, index, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, vk
            )
            if ok:
                self._ids[index] = action
                log.info("全局快捷键已注册：Ctrl+Alt+%s", key_names[vk])
            else:
                error = ctypes.windll.kernel32.GetLastError()
                self.errors.append(
                    f"Ctrl+Alt+{key_names[vk]} 注册失败（错误 {error}）"
                )
                log.warning("全局快捷键注册失败：action=%s error=%s", action, error)
        return bool(self._ids)

    def unregister(self) -> None:
        if not self._registered:
            return
        try:
            user32 = ctypes.windll.user32
            for hotkey_id in self._ids:
                user32.UnregisterHotKey(None, hotkey_id)
        except Exception:
            log.debug("注销全局快捷键失败", exc_info=True)
        try:
            self._app.removeNativeEventFilter(self)
        except Exception:
            pass
        self._ids.clear()
        self._registered = False
        log.info("全局快捷键已注销")

    def nativeEventFilter(self, event_type, message):  # noqa: ANN001, N802
        try:
            raw_type = bytes(event_type)
            if raw_type not in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
                return False
            msg = ctypes.wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY:
                action = self._ids.get(int(msg.wParam))
                if action:
                    log.debug("全局快捷键触发：%s", action)
                    self.triggered.emit(action)
                    return True
        except Exception:
            log.debug("处理全局快捷键消息失败", exc_info=True)
        return False
