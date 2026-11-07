"""交接验证：播放音频 -> 监听运行 -> 停监听+开录音 -> 录音必须拿到数据。

这是真实 UI 点“开始录音”的完整路径（_apply_state -> _sync_monitor -> stop
-> Recorder 线程开流）。播放音频是必须的：WASAPI 回环在无声时不投递数据包。
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import sounddevice as sd
from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from orbit.audio import portaudio as pa
from orbit.audio.devices import enumerate_devices
from orbit.audio.monitor import LiveMonitor
from orbit.audio.recorder import Recorder
from orbit.models import RecordingRequest

app = QCoreApplication(sys.argv)
dev = enumerate_devices().devices[0]
out = Path(tempfile.mkdtemp(prefix="aa_handoff_"))

# 持续播放测试音
fs = 48000
tone = (0.25 * np.sin(2 * np.pi * 997 * np.arange(fs * 12) / fs)).astype(np.float32)
sd.play(np.stack([tone, tone * 0.7], axis=1), fs, blocking=False)
time.sleep(0.4)

CYCLES = 5
problems: list[str] = []
ok_count = 0

for i in range(CYCLES):
    mon = LiveMonitor()
    frames = [0]
    mon.frame_ready.connect(lambda f: frames.__setitem__(0, frames[0] + 1))
    mon.start(dev.index, dev.channels, dev.sample_rate)
    # 等监听真的拿到数据（证明它持有活动流）
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline and frames[0] == 0:
        app.processEvents()
        time.sleep(0.05)
    if frames[0] == 0:
        problems.append(f"cycle{i}: 监听没有收到数据，测试无效")
    print(f"cycle{i}: monitor frames={frames[0]} streams={pa.active_streams()}")

    loop = QEventLoop()
    rec = Recorder()
    result = []
    rec.error.connect(lambda t, d: problems.append(f"cycle{i}: {t}: {d[:120]}"))
    rec.finished.connect(lambda r: (result.append(r), loop.quit()))
    req = RecordingRequest(
        device=dev,
        sample_rate=dev.sample_rate,
        channels=2,
        bit_depth=32,
        buffer_ms=20,
        output_format="wav",
        output_dir=out,
        base_name=f"handoff{i}",
        bitrate_kbps=192,
        metadata_enabled=False,
    )
    # 与 UI 一致：先停监听，再启动录音
    mon.stop()
    rec.start(req)
    QTimer.singleShot(1200, lambda: rec.stop("probe"))
    guard = QTimer()
    guard.setSingleShot(True)
    guard.timeout.connect(loop.quit)
    guard.start(15000)
    loop.exec()

    if result and result[0].frames > 0 and result[0].files:
        ok_count += 1
        print(f"  OK recorded frames={result[0].frames} file={result[0].files[0].name}")
    else:
        problems.append(
            f"cycle{i}: 录音失败 frames={result[0].frames if result else 'N/A'}"
        )
    mon.stop()
    time.sleep(0.3)

sd.stop()
print(f"\ncycles={CYCLES} ok={ok_count}")
print("problems:", problems[:6] or "none")
sys.exit(0 if ok_count == CYCLES else 1)
