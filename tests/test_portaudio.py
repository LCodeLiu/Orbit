"""PortAudio 占用计数回归测试。"""

from __future__ import annotations

import threading
import time

from orbit.audio import portaudio


def test_stream_accounting_roundtrip() -> None:
    """登记/释放配对后，wait_until_idle 应立即返回。"""
    assert portaudio.wait_until_idle(timeout=0.2)

    portaudio.note_stream_opened()
    start = time.monotonic()
    assert not portaudio.wait_until_idle(timeout=0.3), "有活动流时不应立即空闲"
    assert time.monotonic() - start < 1.0

    portaudio.note_stream_closed()
    assert portaudio.wait_until_idle(timeout=0.2)


def test_wait_until_idle_wakes_on_release() -> None:
    """释放流应唤醒等待者，不必等满超时。"""
    portaudio.note_stream_opened()
    result: list[float] = []

    def waiter() -> None:
        t0 = time.monotonic()
        ok = portaudio.wait_until_idle(timeout=5.0)
        result.append((time.monotonic() - t0) if ok else -1.0)

    thread = threading.Thread(target=waiter)
    thread.start()
    time.sleep(0.15)
    portaudio.note_stream_closed()
    thread.join(timeout=3.0)

    assert not thread.is_alive()
    assert result and 0 <= result[0] < 2.0


def test_counter_never_goes_negative() -> None:
    """多余的释放调用不能把计数压成负数，否则会永久阻塞后续等待者。"""
    portaudio.note_stream_closed()
    portaudio.note_stream_closed()
    assert portaudio.wait_until_idle(timeout=0.2)
