"""开发期自检：16-bit / 单声道 / 非原生采样率。"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import soundfile as sf
from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer

from orbit.audio.devices import enumerate_devices
from orbit.audio.recorder import Recorder
from orbit.models import RecordingRequest, RecordingResult

app = QCoreApplication(sys.argv)
device = enumerate_devices().devices[0]
out = Path(tempfile.mkdtemp(prefix="aa_formats_"))


def run(name: str, fmt: str, depth: int, rate: int, channels: int) -> None:
    loop = QEventLoop()
    rec = Recorder()
    result: list[RecordingResult] = []
    errors: list[str] = []
    rec.error.connect(lambda t, d: errors.append(f"{t}: {d}"))
    rec.finished.connect(lambda r: (result.append(r), loop.quit()))
    req = RecordingRequest(
        device=device,
        sample_rate=rate,
        channels=channels,
        bit_depth=depth,
        buffer_ms=20,
        output_format=fmt,
        output_dir=out,
        base_name=name,
        bitrate_kbps=192,
        metadata_enabled=True,
    )
    rec.start(req)
    QTimer.singleShot(1300, lambda: rec.stop("probe"))
    QTimer.singleShot(15000, loop.quit)
    loop.exec()
    print("\n", name, "errors", errors)
    if result:
        r = result[0]
        print("  elapsed", r.elapsed, "files", [p.name for p in r.files])
        for p in r.files:
            info = sf.info(p)
            print(
                "  ",
                p.name,
                info.samplerate,
                info.channels,
                info.subtype,
                info.duration,
                p.stat().st_size,
            )


run("pcm16", "wav", 16, 48000, 2)
run("flac16", "flac", 16, 48000, 2)
run("mono", "wav", 32, 48000, 1)
run("rate44", "wav", 32, 44100, 2)
print("OUT", out)
