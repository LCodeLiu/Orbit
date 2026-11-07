"""开发期自检：全局快捷键注册与 WM_HOTKEY 处理。"""

from __future__ import annotations

import ctypes
import sys
import time

from PySide6.QtWidgets import QApplication

from orbit.util.hotkeys import GlobalHotkeys, WM_HOTKEY

app = QApplication(sys.argv[:1])
hk = GlobalHotkeys(app)
events: list[str] = []
hk.triggered.connect(events.append)
print("register", hk.register(), hk.errors, hk._ids)
if hk.registered:
    first_id = next(iter(hk._ids))
    tid = ctypes.windll.kernel32.GetCurrentThreadId()
    ok = ctypes.windll.user32.PostThreadMessageW(tid, WM_HOTKEY, first_id, 0)
    print("post", ok, "thread", tid)
    end = time.monotonic() + 1.5
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.02)
print("events", events)
hk.unregister()
