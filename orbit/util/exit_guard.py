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

"""退出看门狗：关闭请求后若主线程卡死，强制结束进程。

打包版在关闭窗口时曾出现“未响应”：closeEvent 之后的清理
（PortAudio 流释放、QtMultimedia 停止、解释器 finalization）在冻结
环境下可能同步阻塞 GUI 线程。此时任何 QTimer 都不会再触发（事件循环
已停），因此看门狗必须是独立线程：

- 真正退出分支开始时 arm（隐藏到托盘不算退出）；
- 正常退出时进程自然结束，看门狗随进程消失；
- 若 GUI 线程被卡住超过 delay 秒，看门狗 os._exit(0) 强制结束。

数据安全性：录音的封存/转码在停止流程中已同步等待完成，配置文件在
arm 之前已落盘，因此强制退出不丢用户数据。
"""

from __future__ import annotations

import os
import threading
import time

_armed = threading.Event()


def arm_exit_watchdog(delay_seconds: float = 3.0) -> None:
    """启动一次性看门狗；重复调用只生效一次。"""
    if _armed.is_set():
        return
    _armed.set()

    def watch() -> None:
        time.sleep(delay_seconds)
        # 走到这里说明正常退出流程没有完成，强杀前先尽量刷新日志
        try:
            import logging

            logging.shutdown()
        except Exception:
            pass
        os._exit(0)

    threading.Thread(target=watch, name="ExitWatchdog", daemon=True).start()
