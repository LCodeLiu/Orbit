"""开发期自检：真实 WASAPI 回环录音（WAV / FLAC / ALAC / MP3）。"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf
from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer

from orbit.audio.devices import enumerate_devices
from orbit.audio.ffmpeg import probe_audio
from orbit.models import RecordingRequest, RecordingResult
from orbit.audio.recorder import Recorder

app = QCoreApplication(sys.argv)

inventory = enumerate_devices()
if not inventory.ok:
    print("DEVICE ERROR", inventory.error)
    raise SystemExit(1)
for d in inventory.devices:
    print("device", d.index, d.name, d.sample_rate, d.channels, d.is_default)
device = inventory.devices[0]

# 找 WASAPI 输出设备播放测试音
output_device = None
for idx, info in enumerate(sd.query_devices()):
    if (
        info["hostapi"] == 2
        and info["max_output_channels"] >= 2
        and int(info["default_samplerate"]) == device.sample_rate
        and "耳机" in info["name"]
    ):
        output_device = idx
        break
print("playback device", output_device)

fs = device.sample_rate
seconds = 8.0
t = np.arange(int(fs * seconds)) / fs
tone = (
    0.22 * np.sin(2 * np.pi * 997 * t) + 0.08 * np.sin(2 * np.pi * 440 * t)
).astype(np.float32)
stereo = np.stack([tone, 0.7 * tone], axis=1)
sd.play(stereo, fs, device=output_device, blocking=False)
time.sleep(0.4)

out_dir = Path(tempfile.mkdtemp(prefix="aa_rec_"))
results: list[RecordingResult] = []
errors: list[str] = []


def record(name: str, fmt: str, depth: int, seconds: float) -> None:
    print("\n=== record", name, fmt, depth, "===")
    loop = QEventLoop()
    rec = Recorder()
    req = RecordingRequest(
        device=device,
        sample_rate=fs,
        channels=2,
        bit_depth=depth,
        buffer_ms=20,
        output_format=fmt,
        output_dir=out_dir,
        base_name=name,
        bitrate_kbps=256,
        metadata_enabled=True,
    )

    rec.started.connect(lambda info: print("started", info))
    rec.stats_updated.connect(
        lambda s: None
    )
    rec.error.connect(lambda title, detail: (errors.append(detail), print("ERROR", title, detail)))
    rec.file_ready.connect(lambda path: print("file_ready", path))

    def done(result: RecordingResult) -> None:
        results.append(result)
        print(
            "finished",
            result.elapsed,
            "files=",
            [str(p) for p in result.files],
            "preserved=",
            result.preserved_sources,
            "dropped=",
            result.dropped_frames,
            "errors=",
            result.errors,
        )
        loop.quit()

    rec.finished.connect(done)
    if not rec.start(req):
        print("start failed")
        return
    QTimer.singleShot(int(seconds * 1000), lambda: rec.stop("probe"))
    QTimer.singleShot(30_000, loop.quit)
    loop.exec()

    for path in results[-1].files:
        try:
            info = sf.info(path)
            print("  check", path.name, info.samplerate, info.channels, info.subtype, info.duration)
        except Exception:
            print("  check ffprobe", path.name, probe_audio(path))


record("wav_32f", "wav", 32, 2.0)
record("flac_24", "flac", 24, 2.0)
record("alac_24", "alac", 24, 2.0)
record("mp3_24", "mp3", 24, 1.5)
record("aac_24", "aac", 24, 1.5)
record("ogg_24", "ogg", 24, 1.5)

sd.stop()
print("\nOUT", out_dir)
print("ERRORS", errors)
for p in sorted(out_dir.iterdir()):
    print(p.name, p.stat().st_size)
