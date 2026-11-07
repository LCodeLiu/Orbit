"""开发期自检：录制真实测试音，并检查无声音时的回环回调。"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf
from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer

from orbit.audio.devices import enumerate_devices
from orbit.audio.recorder import Recorder
from orbit.models import RecordingRequest, RecordingResult

app = QCoreApplication(sys.argv)
inventory = enumerate_devices()
device = inventory.devices[0]
print("device", device)
out_dir = Path(tempfile.mkdtemp(prefix="aa_quality_"))


def run(name: str, fmt: str, depth: int, seconds: float, play_tone: bool) -> RecordingResult:
    loop = QEventLoop()
    rec = Recorder()
    result: list[RecordingResult] = []
    errors: list[str] = []
    req = RecordingRequest(
        device=device,
        sample_rate=device.sample_rate,
        channels=2,
        bit_depth=depth,
        buffer_ms=20,
        output_format=fmt,
        output_dir=out_dir,
        base_name=name,
        bitrate_kbps=320,
        metadata_enabled=True,
    )
    rec.error.connect(lambda title, detail: errors.append(f"{title}: {detail}"))
    rec.device_lost.connect(lambda m: print("device_lost", m))
    rec.finished.connect(lambda r: (result.append(r), loop.quit()))
    print("start", name)
    rec.start(req)
    if play_tone:
        fs = 48000
        t = np.arange(int(fs * (seconds + 0.3))) / fs
        tone = (0.25 * np.sin(2 * np.pi * 997 * t)).astype(np.float32)
        stereo = np.stack([tone, 0.6 * tone], axis=1)
        sd.play(stereo, fs, blocking=False)
    QTimer.singleShot(int(seconds * 1000), lambda: rec.stop("probe"))
    QTimer.singleShot(30_000, loop.quit)
    loop.exec()
    sd.stop()
    print("errors", errors)
    print("result", result[0] if result else None)
    return result[0] if result else RecordingResult(errors=errors)


r = run("silence_8s", "wav", 32, 8.0, False)
print("silence files", r.files)

r = run("tone_wav", "wav", 32, 2.5, True)
for p in r.files:
    data, fs = sf.read(p, dtype="float32", always_2d=True)
    mono = data[:, 0]
    print("wav", fs, data.shape, "peak", float(np.max(np.abs(data))), "rms", float(np.sqrt(np.mean(mono**2))))
    spec = np.abs(np.fft.rfft(mono * np.hanning(mono.size)))
    freqs = np.fft.rfftfreq(mono.size, 1 / fs)
    top = np.argsort(spec)[-3:][::-1]
    print("top", [(round(float(freqs[i]), 1), round(float(spec[i]), 1)) for i in top])

r = run("tone_flac", "flac", 24, 2.5, True)
for p in r.files:
    data, fs = sf.read(p, dtype="float32", always_2d=True)
    mono = data[:, 0]
    print("flac", fs, data.shape, "peak", float(np.max(np.abs(data))), "rms", float(np.sqrt(np.mean(mono**2))))
    spec = np.abs(np.fft.rfft(mono * np.hanning(mono.size)))
    freqs = np.fft.rfftfreq(mono.size, 1 / fs)
    top = np.argsort(spec)[-3:][::-1]
    print("top", [(round(float(freqs[i]), 1), round(float(spec[i]), 1)) for i in top])

print("OUT", out_dir)
