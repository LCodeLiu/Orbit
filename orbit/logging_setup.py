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

"""日志系统：滚动文件 + 控制台 + Qt 日志面板桥接。

重要约定：文件日志**绝不允许**导致程序启动失败。
app.log 可能被编辑器/tailer 占用、被杀软实时扫描锁定，或因日志滚动
重命名而短暂处于 delete-pending 状态；这些情况下 Windows 会以
PermissionError([WinError 5]) 拒绝以写方式打开。若异常逃出 main()，
用户只会看到一个“Unhandled exception”弹窗而完全无法使用程序。
因此这里逐级降级：主日志 → 带时间戳的备用日志 → 临时目录 → 仅内存/控制台。
"""

from __future__ import annotations

import logging
import sys
import tempfile
import time
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from orbit.constants import APP_NAME
from orbit.util.paths import ensure_dir, log_dir

_LOG_FORMAT_FILE = (
    "%(asctime)s.%(msecs)03d | %(levelname)-7s | %(threadName)-14s | "
    "%(name)s | %(message)s"
)
_LOG_FORMAT_CONSOLE = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"

# 文件日志不可用时，记录原因供 UI 提示
_file_logging_error = ""
# 实际生效的日志文件（可能因主文件被占用而落到备用/临时路径）
_active_log_file: Path | None = None


def get_file_logging_error() -> str:
    """返回文件日志降级/失败的原因；空字符串表示正常。"""
    return _file_logging_error


def get_active_log_file() -> Path | None:
    """返回当前实际写入的日志文件；None 表示完全没有文件日志。"""
    return _active_log_file


class LogBridge(QObject):
    """把 logging 记录安全地转发到 GUI 线程。"""

    message = Signal(str, str, str)  # timestamp, level, text


_bridge: LogBridge | None = None


def get_log_bridge() -> LogBridge:
    global _bridge
    if _bridge is None:
        _bridge = LogBridge()
    return _bridge


class QtLogHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.bridge = get_log_bridge()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
            timestamp = datetime.fromtimestamp(record.created).strftime("%H:%M:%S.%f")[:-3]
            self.bridge.message.emit(timestamp, record.levelname, message)
        except Exception:
            self.handleError(record)


class ConsoleFilter(logging.Filter):
    """控制台只输出本应用日志，避免第三方库噪声。"""

    def filter(self, record: logging.LogRecord) -> bool:
        return record.name.startswith("orbit")


def _candidate_log_files() -> list[Path]:
    """按优先级给出可尝试的日志文件路径。

    只返回路径，不创建目录：备用位置必须等到真正要用时才建，
    否则每次启动都会在临时目录留下空文件夹。

    候选必须是绝对路径：TEMP/TMP 被设成无效值时，
    tempfile.gettempdir() 可能返回相对路径，直接拼接会在当前工作目录
    （打包版通常就是 exe 所在目录）里创建出意外的 logs 文件夹。
    """
    candidates: list[Path] = []
    try:
        primary_dir = ensure_dir(log_dir())
        candidates.append(primary_dir / "app.log")
        # 主文件被占用时，用带时间戳的同目录文件继续记录
        candidates.append(
            primary_dir / f"app-{datetime.now():%Y%m%d-%H%M%S}.log"
        )
    except Exception:  # pragma: no cover - 路径异常不应影响启动
        pass
    # 退到临时目录，保证仍能落盘。
    # 注意：TEMP/TMP 全部无效时 gettempdir() 会退化成 os.getcwd()，
    # 返回的仍是绝对路径；而打包版的工作目录通常就是 exe 所在目录，
    # 于是会在 dist 里创建出意外的 logs 文件夹。因此必须排除
    # 等于或位于当前工作目录内的候选。
    try:
        tmp_root = Path(tempfile.gettempdir()).resolve()
        cwd = Path.cwd().resolve()
        inside_cwd = tmp_root == cwd or cwd in tmp_root.parents
        if tmp_root.is_absolute() and not inside_cwd:
            candidates.append(tmp_root / "Orbit" / "logs" / "app.log")
    except Exception:  # pragma: no cover
        pass
    # 不提供“紧邻 exe 的 logs”这一级：打包版常被放在只读位置，
    # 且实测会在 dist 里生成意外的嵌套文件夹，污染交付目录。
    # 以上候选全部失败时，日志仍会通过界面日志面板与控制台输出，不影响启动。
    return candidates


def _prune_fallback_logs(directory: Path, keep: int = 5) -> None:
    """备用日志按时间戳命名，主日志长期被占用会不断累积；只保留最近几个。"""
    try:
        fallbacks = sorted(
            (
                p
                for p in directory.glob("app-*.log")
                if p.is_file() and p.stem != "app"
            ),
            key=lambda p: p.name,
            reverse=True,
        )
    except OSError:
        return
    for stale in fallbacks[keep:]:
        try:
            stale.unlink()
        except OSError:
            pass  # 可能正被另一个实例使用，忽略即可


def _make_file_handler(logfile: Path) -> RotatingFileHandler | None:
    """尝试创建滚动文件 handler；失败返回 None，绝不抛出。"""
    # 只在真正要用这个位置时才建目录，避免在备用路径留下空文件夹
    try:
        logfile.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    except Exception:  # pragma: no cover
        return None
    # 先用公开 API 探测可写性：文件可能被编辑器/tailer 占用、被杀软锁定，
    # 或因上一次滚动重命名处于 delete-pending 状态。
    # 杀软扫描新进程/新文件常只锁定极短时间，因此失败后短暂重试，
    # 避免一次瞬时占用就永久降级到备用日志。
    probe = None
    for attempt in range(3):
        try:
            probe = open(logfile, "a", encoding="utf-8")  # noqa: SIM115
            break
        except (OSError, ValueError):
            if attempt < 2:
                time.sleep(0.15)
    if probe is None:
        return None
    try:
        probe.close()
    except OSError:
        pass
    try:
        handler = RotatingFileHandler(
            logfile,
            maxBytes=4 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
            # delay=True：真正写入时才打开，避开启动瞬间的偶发锁定
            delay=True,
        )
    except (OSError, ValueError):
        return None
    handler.setFormatter(
        logging.Formatter(_LOG_FORMAT_FILE, datefmt="%Y-%m-%d %H:%M:%S")
    )
    handler._orbit = True  # type: ignore[attr-defined]
    return handler


def setup_logging(level: str = "INFO", console: bool = True) -> Path | None:
    """初始化根日志器，返回实际使用的日志文件路径（可能为 None）。

    该函数可以重复调用（例如切换日志等级），不会叠加重复 handler。
    任何文件层面的失败都会被吞掉并降级，保证调用方继续启动。
    """
    global _file_logging_error, _active_log_file
    _file_logging_error = ""
    _active_log_file = None

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # 移除本模块之前安装的 handler
    for handler in list(root.handlers):
        if getattr(handler, "_orbit", False):
            root.removeHandler(handler)
            try:
                handler.close()
            except Exception:
                pass

    logfile: Path | None = None
    file_handler: RotatingFileHandler | None = None
    for candidate in _candidate_log_files():
        file_handler = _make_file_handler(candidate)
        if file_handler is not None:
            logfile = candidate
            break
    if file_handler is not None and logfile is not None:
        root.addHandler(file_handler)
        _active_log_file = logfile
        # 用的是备用文件时，清理更早的备用文件，避免无限累积
        if logfile.name != "app.log":
            _prune_fallback_logs(logfile.parent)
    else:
        _file_logging_error = "无法在日志目录创建可写文件（可能被占用或权限不足）"

    qt_handler = QtLogHandler()
    qt_handler.setFormatter(logging.Formatter("%(message)s"))
    qt_handler.setLevel(logging.DEBUG)
    qt_handler._orbit = True  # type: ignore[attr-defined]
    root.addHandler(qt_handler)

    if console and sys.stderr is not None:
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(logging.Formatter(_LOG_FORMAT_CONSOLE, datefmt="%H:%M:%S"))
        stream.addFilter(ConsoleFilter())
        stream._orbit = True  # type: ignore[attr-defined]
        root.addHandler(stream)

    # 第三方库降噪
    for name in ("PIL", "urllib3", "comtypes", "numpy", "soundfile"):
        logging.getLogger(name).setLevel(logging.WARNING)

    app_log = logging.getLogger("orbit")
    if logfile is not None:
        app_log.info(
            "%s 日志系统已启动，级别=%s，文件=%s", APP_NAME, level.upper(), logfile
        )
        if logfile.name != "app.log":
            # 只写日志面板，不弹窗打扰用户：日志降级不影响录音
            app_log.warning(
                "主日志 app.log 暂时不可写，已自动改用备用日志：%s", logfile.name
            )
    else:
        # 文件日志失败时，仍通过界面日志面板告知用户
        app_log.warning(
            "%s 日志系统已启动（文件日志不可用：%s），级别=%s",
            APP_NAME,
            _file_logging_error,
            level.upper(),
        )
    return logfile


def set_log_level(level: str) -> None:
    level = level.upper()
    if level not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
        level = "INFO"
    new_val = getattr(logging, level)
    root = logging.getLogger()
    if root.level == new_val:
        # 级别未变化，不重复写日志
        return
    root.setLevel(new_val)
    logging.getLogger("orbit").info("日志级别切换为 %s", level)


def install_exception_hook() -> None:
    """未捕获异常写入日志并弹窗提示，避免无提示退出。"""
    previous = sys.excepthook

    def hook(exc_type, exc_value, exc_tb):  # type: ignore[no-untyped-def]
        if issubclass(exc_type, KeyboardInterrupt):
            previous(exc_type, exc_value, exc_tb)
            return
        logging.getLogger("orbit").critical(
            "未捕获异常", exc_info=(exc_type, exc_value, exc_tb)
        )
        previous(exc_type, exc_value, exc_tb)

    sys.excepthook = hook
