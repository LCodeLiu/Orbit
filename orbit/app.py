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

"""应用入口、单实例与命令行诊断。"""

from __future__ import annotations

import argparse
import ctypes
import logging
import os
import sys
from datetime import datetime

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QApplication

from orbit.config import ConfigStore
from orbit.constants import APP_NAME, ORG_NAME, VERSION
from orbit.logging_setup import install_exception_hook, setup_logging
from orbit.ui.main_window import MainWindow
from orbit.ui.theme import app_icon, build_stylesheet
from orbit.util.paths import (
    config_path,
    log_dir,
)

log = logging.getLogger(__name__)

SINGLE_INSTANCE_NAME = "Orbit.Desktop.SingleInstance"


class SingleInstanceGuard(QObject):
    """使用 Windows 命名互斥体保证单实例。

    DSH 沙箱或某些安全软件可能阻止本地命名管道，因此这里不依赖 QLocalServer。
    第二个实例会通过窗口标题找到主窗口并尝试恢复/置前，然后退出。
    """

    def __init__(self, name: str = SINGLE_INSTANCE_NAME) -> None:
        super().__init__()
        self.name = name
        self._handle: int | None = None

    def acquire(self) -> bool:
        if sys.platform != "win32":
            return True
        try:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.CreateMutexW.argtypes = [
                ctypes.c_void_p,
                ctypes.c_bool,
                ctypes.c_wchar_p,
            ]
            kernel32.CreateMutexW.restype = ctypes.c_void_p
            kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel32.CloseHandle.restype = ctypes.c_bool
            handle = kernel32.CreateMutexW(None, False, f"Local\\{self.name}")
        except Exception:
            log.exception("创建单实例互斥体失败，允许本进程继续")
            return True
        if not handle:
            log.warning("无法创建单实例互斥体，允许本进程继续")
            return True
        already_exists = ctypes.get_last_error() == 183
        if already_exists:
            kernel32.CloseHandle(ctypes.c_void_p(handle))
            log.info("检测到已有实例，尝试激活其主窗口")
            self._activate_existing_window()
            return False
        self._handle = int(handle)
        return True

    @staticmethod
    def _activate_existing_window() -> None:
        if sys.platform != "win32":
            return
        import time

        user32 = ctypes.windll.user32
        user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
        user32.ShowWindow.restype = ctypes.c_bool
        user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
        user32.SetForegroundWindow.restype = ctypes.c_bool
        user32.GetWindowTextLengthW.argtypes = [ctypes.c_void_p]
        user32.GetWindowTextLengthW.restype = ctypes.c_int
        user32.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
        user32.GetWindowTextW.restype = ctypes.c_int
        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        user32.EnumWindows.argtypes = [WNDENUMPROC, ctypes.c_void_p]
        user32.EnumWindows.restype = ctypes.c_bool

        def find_window() -> int:
            matches: list[int] = []

            def callback(hwnd, _lparam):  # noqa: ANN001
                length = user32.GetWindowTextLengthW(hwnd)
                if length <= 0:
                    return True
                buffer = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buffer, length + 1)
                title = buffer.value
                if "Orbit" in title and "系统音频采集" in title:
                    matches.append(int(hwnd))
                    return False
                return True

            user32.EnumWindows(WNDENUMPROC(callback), None)
            return matches[0] if matches else 0

        hwnd = 0
        # 主实例可能还在启动，最多等待 2.5 秒
        for _ in range(25):
            hwnd = find_window()
            if hwnd:
                break
            time.sleep(0.1)
        if not hwnd:
            log.warning("未找到主实例窗口，第二个实例直接退出")
            return
        SW_SHOW = 5
        SW_RESTORE = 9
        handle = ctypes.c_void_p(hwnd)
        user32.ShowWindow(handle, SW_RESTORE)
        user32.ShowWindow(handle, SW_SHOW)
        user32.SetForegroundWindow(handle)
        log.info("已请求主实例窗口显示到前台")

    def close(self) -> None:
        if self._handle and sys.platform == "win32":
            try:
                kernel32 = ctypes.WinDLL("kernel32")
                kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
                kernel32.CloseHandle(ctypes.c_void_p(self._handle))
            except Exception:
                pass
            self._handle = None


def _ensure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream is not None and hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _spawn_console_for_cli(effective: list[str]) -> bool:
    """当没有父控制台时（Explorer 双击 / gui-scripts），在新 cmd 窗口中重新运行。

    使用 python.exe（控制台程序）而非 orbit.exe（GUI 程序），确保输出可见。
    返回 True 表示已派生子进程，调用方应直接退出。
    """
    if sys.platform != "win32":
        return False
    # 有控制台（cmd/PowerShell 中运行）→ 直接在当前控制台输出
    if sys.stdout is not None and sys.stderr is not None:
        return False
    try:
        import os
        import subprocess

        python = sys.executable
        if python.lower().endswith("pythonw.exe"):
            candidate = python[:-len("pythonw.exe")] + "python.exe"
            if os.path.exists(candidate):
                python = candidate
        # 用 python.exe 运行 CLI，/k 保持窗口打开方便查看输出
        code = "from orbit.app import main; raise SystemExit(main(%r))" % (effective,)
        subprocess.Popen(
            ["cmd", "/k", python, "-c", code],
            creationflags=subprocess.CREATE_NEW_CONSOLE,
        )
        return True
    except Exception:
        return False


def _setup_windows_identity() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "Orbit.Desktop.1"
        )
    except Exception:
        pass


def _apply_dark_titlebar(window) -> None:  # noqa: ANN001
    """将窗口标题栏设为深色。仅使用 DWMWA_USE_IMMERSIVE_DARK_MODE (attr 20)。

    不要设置 DWMWA_CAPTION_COLOR (35) / DWMWA_BORDER_COLOR (34)：在部分
    Windows 11 版本上，attr 35 会导致窗口标题栏/边框全黑，且与
    orbit.ui.theme._apply_dark_titlebar 保持一致。
    """
    if sys.platform != "win32":
        return
    try:
        hwnd = int(window.winId())
        value = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 20, ctypes.byref(value), ctypes.sizeof(value)
        )
    except Exception:
        log.debug("设置 Windows 深色标题栏失败", exc_info=True)


def _diagnose() -> int:
    from orbit.audio.devices import enumerate_devices
    from orbit.audio.ffmpeg import inspect_ffmpeg

    _ensure_utf8_stdio()
    cfg = ConfigStore().load()
    print(f"{APP_NAME} {VERSION}")
    print(f"Python      : {sys.version.splitlines()[0]}")
    print(f"Executable  : {sys.executable}")
    print(f"Platform    : {sys.platform}")
    print(f"Config      : {config_path()}")
    print(f"Logs        : {log_dir()}")
    print(f"Output      : {cfg.output_dir}")
    print()
    inventory = enumerate_devices()
    print(f"[WASAPI Loopback]  PortAudio: {inventory.portaudio_version or '?'}")
    if inventory.error:
        print(f"ERROR: {inventory.error}")
    for device in inventory.devices:
        mark = "DEFAULT" if device.is_default else "       "
        print(
            f"  {mark} [{device.index:>2}] {device.name} | "
            f"{device.sample_rate} Hz | {device.channels} ch"
        )
    print()
    info = inspect_ffmpeg(cfg.ffmpeg_path)
    print(f"[FFmpeg] {info.summary}")
    if info.path:
        print(f"  path: {info.path}")
    for codec in ("alac", "aac", "libmp3lame", "libvorbis"):
        print(f"  {codec:<12}: {'OK' if info.has_encoder(codec) else 'missing'}")
    print()
    print("[Settings]")
    print(
        f"  device={cfg.device_name or '-'} rate={cfg.sample_rate or 'native'} "
        f"depth={cfg.bit_depth} channels={cfg.channels or 'native'} "
        f"format={cfg.output_format}"
    )
    print(
        f"  buffer={cfg.buffer_ms}ms split={cfg.split_minutes}min/"
        f"{cfg.split_size_mb}MB max={cfg.max_minutes}min "
        f"schedule={cfg.schedule_enabled}@{cfg.schedule_time}"
    )
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="orbit", description="Orbit 音频采集工具")
    parser.add_argument("--version", action="store_true", help="显示版本并退出")
    parser.add_argument("--diagnose", action="store_true", help="打印环境、设备和编码器信息")
    parser.add_argument("--reset-config", action="store_true", help="备份并重置配置文件")
    parser.add_argument("--no-single-instance", action="store_true", help="开发调试：允许多开")
    return parser


def main(argv: list[str] | None = None) -> int:
    effective = list(argv) if argv is not None else sys.argv[1:]
    if any(a in ("--version", "--diagnose", "--reset-config", "-h", "--help") for a in effective):
        if sys.stdout is None or sys.stderr is None:
            if _spawn_console_for_cli(effective):
                return 0
    _ensure_utf8_stdio()
    args = _build_parser().parse_args(argv)
    if args.version:
        print(f"{APP_NAME} {VERSION}")
        return 0
    if args.reset_config:
        path = config_path()
        if path.exists():
            backup = path.with_suffix(f".backup-{datetime.now():%Y%m%d-%H%M%S}.json")
            try:
                path.replace(backup)
                print(f"配置已备份到：{backup}")
            except OSError as exc:
                print(f"无法备份配置：{exc}", file=sys.stderr)
                return 1
        else:
            print("配置文件不存在，无需重置。")
        return 0
    if args.diagnose:
        return _diagnose()

    _setup_windows_identity()
    app = QApplication(sys.argv[:1] + (argv or []))
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName(ORG_NAME)
    app.setApplicationVersion(VERSION)
    app.setWindowIcon(app_icon())
    app.setStyle("Fusion")
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet(build_stylesheet())
    install_exception_hook()

    cfg = ConfigStore().load()
    setup_logging(cfg.log_level)
    log.info("=" * 70)
    log.info("%s %s 启动", APP_NAME, VERSION)
    log.info("Python=%s", sys.version.splitlines()[0])
    log.info("配置=%s", config_path())
    log.info("日志=%s", log_dir())
    log.info("输出=%s", cfg.output_dir)

    guard: SingleInstanceGuard | None = None
    if not args.no_single_instance and not os.environ.get("ORBIT_MULTI"):
        guard = SingleInstanceGuard()
        if not guard.acquire():
            log.info("已有实例在运行，已请求其显示主窗口")
            return 0

    window = MainWindow(cfg)
    app.aboutToQuit.connect(lambda: guard.close() if guard else None)
    window.show()
    QTimer.singleShot(30, lambda: _apply_dark_titlebar(window))
    log.info("主窗口已显示")
    return app.exec()
