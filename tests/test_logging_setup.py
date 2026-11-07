from __future__ import annotations

import logging
from pathlib import Path

from orbit import logging_setup


def _cleanup_root_handlers() -> None:
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, "_orbit", False):
            root.removeHandler(handler)
            try:
                handler.close()
            except Exception:
                pass


def test_file_logging_falls_back_when_primary_unwritable(
    tmp_path: Path, monkeypatch
) -> None:
    """主 app.log 无法写入时，应降级到备用文件而不是抛异常。"""
    _cleanup_root_handlers()
    logs = tmp_path / "logs"
    logs.mkdir()
    # 在日志路径上放一个目录：以写方式打开会抛 OSError(PermissionError/IsADirectoryError)
    (logs / "app.log").mkdir()

    monkeypatch.setattr(logging_setup, "log_dir", lambda: logs)
    monkeypatch.setattr(logging_setup, "ensure_dir", lambda p: p)

    try:
        result = logging_setup.setup_logging("INFO", console=False)
    finally:
        _cleanup_root_handlers()

    assert result is not None, "应降级到备用日志文件"
    assert result.parent == logs
    assert result.name != "app.log"
    assert result.exists()
    assert logging_setup.get_active_log_file() == result


def test_file_logging_failure_never_raises(tmp_path: Path, monkeypatch) -> None:
    """所有候选都不可写时，返回 None 且绝不抛异常。"""
    _cleanup_root_handlers()
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "app.log").mkdir()
    stamp = "20261027-000000"
    (logs / f"app-{stamp}.log").mkdir()

    monkeypatch.setattr(logging_setup, "log_dir", lambda: logs)
    monkeypatch.setattr(logging_setup, "ensure_dir", lambda p: p)
    monkeypatch.setattr(logging_setup, "datetime", _FixedDateTime(stamp))
    # 临时目录候选也失败：指向一个普通文件
    blocker = tmp_path / "tmp_is_file"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setattr(logging_setup.tempfile, "gettempdir", lambda: str(blocker))

    try:
        result = logging_setup.setup_logging("INFO", console=False)
    finally:
        _cleanup_root_handlers()

    assert result is None
    assert logging_setup.get_active_log_file() is None
    assert logging_setup.get_file_logging_error()


def test_fallback_logs_are_pruned(tmp_path: Path) -> None:
    """备用日志只保留最近若干个，避免主日志长期被占用时无限累积。"""
    logs = tmp_path / "logs"
    logs.mkdir()
    names = [f"app-2026102{i}-22000{i}.log" for i in range(9)]
    for name in names:
        (logs / name).write_text("x", encoding="utf-8")
    newest = "app-20261029-220009.log"
    (logs / newest).write_text("x", encoding="utf-8")
    (logs / "app.log").write_text("primary", encoding="utf-8")

    logging_setup._prune_fallback_logs(logs, keep=5)

    remaining = sorted(p.name for p in logs.glob("app-*.log"))
    assert len(remaining) == 5
    assert newest in remaining
    # 主日志不参与清理
    assert (logs / "app.log").read_text(encoding="utf-8") == "primary"


def test_relative_temp_is_rejected_as_candidate(tmp_path: Path, monkeypatch) -> None:
    """TEMP 被设成相对路径时，不得在当前工作目录创建 logs 文件夹。"""
    _cleanup_root_handlers()
    logs = tmp_path / "logs"
    logs.mkdir()
    stamp = "20261027-000000"
    (logs / "app.log").mkdir()          # 主日志不可写
    (logs / f"app-{stamp}.log").mkdir()  # 备用日志也不可用
    monkeypatch.setattr(logging_setup, "log_dir", lambda: logs)
    monkeypatch.setattr(logging_setup, "ensure_dir", lambda p: p)
    monkeypatch.setattr(logging_setup, "datetime", _FixedDateTime(stamp))
    monkeypatch.setattr(logging_setup.tempfile, "gettempdir", lambda: Path("relative_tmp"))

    try:
        result = logging_setup.setup_logging("INFO", console=False)
    finally:
        _cleanup_root_handlers()

    assert result is None
    assert not Path("relative_tmp").exists(), "相对 TEMP 必须被跳过，不能写进工作目录"


def test_temp_degrading_to_cwd_is_rejected(tmp_path: Path, monkeypatch) -> None:
    """TEMP 无效时 gettempdir() 会退化成当前目录（绝对路径），必须排除。

    打包版的工作目录通常就是 exe 所在目录，不过滤会在 dist 里
    创建出意外的 Orbit/logs 嵌套文件夹。
    """
    _cleanup_root_handlers()
    logs = tmp_path / "logs"
    logs.mkdir()
    stamp = "20261027-000000"
    (logs / "app.log").mkdir()
    (logs / f"app-{stamp}.log").mkdir()
    monkeypatch.setattr(logging_setup, "log_dir", lambda: logs)
    monkeypatch.setattr(logging_setup, "ensure_dir", lambda p: p)
    monkeypatch.setattr(logging_setup, "datetime", _FixedDateTime(stamp))
    monkeypatch.setattr(logging_setup.tempfile, "gettempdir", lambda: Path.cwd())

    stray = Path.cwd() / "Orbit" / "logs"
    assert not stray.exists()
    try:
        result = logging_setup.setup_logging("INFO", console=False)
    finally:
        _cleanup_root_handlers()

    assert result is None
    assert not stray.exists(), "临时目录退化成工作目录时不得在其下创建 logs"


def test_prune_survives_unreadable_directory(tmp_path: Path) -> None:
    """目录不可枚举时静默返回，不影响日志启动。"""
    missing = tmp_path / "does-not-exist"
    logging_setup._prune_fallback_logs(missing)  # 不应抛出


class _FixedDateTime:
    """只提供 setup_logging 需要的 now()/fromtimestamp()，用于固定备用文件名。"""

    def __init__(self, stamp: str) -> None:
        self._stamp = stamp

    def now(self):  # noqa: ANN201
        import datetime as _dt

        return _dt.datetime.strptime(self._stamp, "%Y%m%d-%H%M%S")

    def fromtimestamp(self, ts):  # noqa: ANN001, ANN201
        import datetime as _dt

        return _dt.datetime.fromtimestamp(ts)
