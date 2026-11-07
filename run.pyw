"""Orbit 启动入口（pythonw / 无控制台窗口）。

- 双击本文件（Windows 上 .pyw 默认由 pythonw 执行）即可打开主界面；
- 调试时用 `python run.py`（保留控制台输出）；
- 依赖需先安装：pip install -r requirements.txt（或运行 install.bat）。

窗口化（pythonw）下 sys.stdout / sys.stderr 为 None：logging_setup 会
自动跳过控制台 handler，日志只写文件与界面面板，无需特殊处理。
启动阶段若发生异常（如缺依赖），用系统消息框提示。
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

# 保证以任意工作目录双击时都能导入项目包
sys.path.insert(0, str(Path(__file__).resolve().parent))


def _fatal(message: str) -> None:
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(
            None, message, "Orbit 启动失败", 0x10
        )
    except Exception:
        print(message, file=sys.stderr or sys.__stderr__)


try:
    from orbit.app import main  # noqa: E402
except Exception:  # 依赖缺失等启动期错误
    _fatal("无法加载程序核心模块：\n\n" + traceback.format_exc())
    raise SystemExit(1)

if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except SystemExit:
        raise
    except Exception:
        _fatal("程序发生未处理异常：\n\n" + traceback.format_exc())
        raise SystemExit(1)
