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

"""PortAudio 跨线程访问的串行化与设备占用交接。

两条硬约束（都是实测踩出来的）：

1. PortAudio 的 WASAPI host 是**线程亲和**的：在 A 线程创建的 PyAudio
   实例，拿到 B 线程去 open() 会直接返回 -9999（Unanticipated host
   error）。所以每个工作线程必须自己创建 PyAudio，不能共享单例。

2. 但 Pa_Initialize / Pa_Terminate 操作的是 PortAudio 的**全局状态**。
   设备扫描、实时监听、录音三个线程各自创建并 terminate 实例时，
   一个线程正在 Pa_Terminate、另一个线程正在 Pa_Initialize /
   Pa_OpenStream，就会在全局锁上死锁或访问已释放的 host 结构。
   C 层死锁的线程持有 GIL，会让整个解释器（GUI 线程、退出看门狗）
   一起冻结——表现为录音时未响应。

因此：实例仍按线程各自创建，但**创建、开流、关流、terminate 全部
在 stream_guard 内串行**；并用占用登记（note_stream_opened /
wait_until_idle）让录音线程等实时监听释放设备后再开流
（WASAPI 回环同一设备同时只允许一个流）。
"""

from __future__ import annotations

import threading
import time

_lock = threading.RLock()
_idle = threading.Condition(_lock)
_active_streams = 0


class stream_guard:
    """串行化 PortAudio 的初始化、开流、关流与释放。

    用法：with stream_guard(): pa = PyAudio(); pa.open(...) / close / terminate
    可重入，允许同一线程嵌套。
    """

    def __enter__(self) -> "stream_guard":
        _lock.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        _lock.release()


def note_stream_opened() -> None:
    """预登记一个即将/已经打开的流。

    必须在 pa.open() **之前**调用：否则等待方会看到“空闲”并挤进来，
    与正在开流的线程同时占用同一个回环设备（-9999）。
    """
    global _active_streams
    with _idle:
        _active_streams += 1


def note_stream_closed() -> None:
    """撤销登记并唤醒等待者。开流失败时也必须调用，否则计数泄漏。"""
    global _active_streams
    with _idle:
        _active_streams = max(0, _active_streams - 1)
        _idle.notify_all()


def wait_until_idle(timeout: float = 2.0) -> bool:
    """等待所有已登记流释放完毕。

    必须在工作线程调用（会阻塞至多 timeout 秒），绝不能在 GUI 线程调用。
    监听线程每 ~20ms 轮询停止标志，正常几十毫秒内就会释放。
    """
    deadline = time.monotonic() + timeout
    with _idle:
        while _active_streams > 0:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            _idle.wait(remaining)
        return True


def active_streams() -> int:
    """当前登记的活动流数量（诊断/测试用）。"""
    with _lock:
        return _active_streams
