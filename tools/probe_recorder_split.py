"""开发期自检：自动分割、最长时长、无效设备。"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import soundfile as sf
from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer

from orbit.audio.devices import enumerate_devices
from orbit.audio.recorder import Recorder
from orbit.models import AudioDevice, RecordingRequest, RecordingResult

app = QCoreApplication(sys.argv)
inventory = enumerate_devices()
device = inventory.devices[0]
out = Path(tempfile.mkdtemp(prefix="aa_split_"))


def record(name: str, fmt: str, seconds: float, **kwargs) -> RecordingResult:
    print("\n=== ", name, fmt, seconds, kwargs)
    loop = QEventLoop()
    rec = Recorder()
    errors: list[str] = []
    result: list[RecordingResult] = []
    rec.error.connect(lambda t, d: errors.append(f"{t}: {d}"))
    rec.finished.connect(lambda r: (result.append(r), loop.quit()))
    req = RecordingRequest(
        device=device,
        sample_rate=device.sample_rate,
        channels=2,
        bit_depth=kwargs.pop("depth", 24),
        buffer_ms=20,
        output_format=fmt,
        output_dir=out,
        base_name=name,
        bitrate_kbps=192,
        metadata_enabled=True,
        **kwargs,
    )
    ok = rec.start(req)
    if not ok:
        print("start failed", errors)
        return RecordingResult(errors=errors)
    QTimer.singleShot(int(seconds * 1000), lambda: rec.stop("probe"))
    QTimer.singleShot(40_000, loop.quit)
    loop.exec()
    print("errors", errors)
    if result:
        r = result[0]
        print("elapsed", r.elapsed, "frames", r.frames, "file_count", len(r.files))
        for p in r.files:
            try:
                info = sf.info(p)
                print("  ", p.name, info.duration)
            except Exception:
                print("  ", p.name, p.stat().st_size)
        return r
    return RecordingResult(errors=errors)


record("split_wav", "wav", 3.4, split_seconds=1)
record("split_flac", "flac", 3.4, split_seconds=1)
record("split_mp3", "mp3", 2.6, split_seconds=1)
record("max_wav", "wav", 4.0, max_seconds=1)

bad = AudioDevice(index=9999, name="Missing", channels=2, sample_rate=48000)
loop = QEventLoop()
rec = Recorder()
errs: list[str] = []
finished: list[RecordingResult] = []
rec.error.connect(lambda t, d: errs.append(f"{t}: {d}"))
rec.finished.connect(lambda r: (finished.append(r), loop.quit()))
req = RecordingRequest(
    device=bad,
    sample_rate=48000,
    channels=2,
    bit_depth=24,
    buffer_ms=20,
    output_format="wav",
    output_dir=out,
    base_name="invalid_device",
    bitrate_kbps=192,
    metadata_enabled=True,
)
rec.start(req)
QTimer.singleShot(5000, loop.quit)
loop.exec()
print("\ninvalid device errors", errs, "finished", finished)
print("OUT", out)
