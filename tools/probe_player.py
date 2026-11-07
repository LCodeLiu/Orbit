"""开发期自检：QtMultimedia 试听 WAV / FLAC / M4A / MP3 / OGG。"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import soundfile as sf
from PySide6.QtWidgets import QApplication

from orbit.audio.ffmpeg import transcode
from orbit.audio.formats import OUTPUT_FORMATS
from orbit.ui.widgets import PlayerBar

out = Path(tempfile.mkdtemp(prefix="aa_player_"))
fs = 44100
n = fs * 2
t = np.arange(n) / fs
sig = (0.15 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
sf.write(out / "a.wav", np.stack([sig, sig], axis=1), fs, subtype="PCM_16")
for key in ("flac", "alac", "mp3", "aac", "ogg"):
    fmt = OUTPUT_FORMATS[key]
    if key == "flac":
        sf.write(out / "a.flac", np.stack([sig, sig], axis=1), fs, subtype="PCM_16")
    else:
        transcode(out / "a.wav", out / f"a{fmt.extension}", fmt, 192, sample_rate=fs, channels=2)

app = QApplication(sys.argv[:1])
player = PlayerBar()
errors: list[str] = []
player.error.connect(errors.append)
for path in sorted(out.iterdir()):
    print("play", path.name)
    player.play_file(path)
    end = time.monotonic() + 0.8
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.02)
    print("  state", player._media.playbackState(), "duration", player._duration, "errors", errors[-1:] if errors else [])
    player.stop()
    app.processEvents()
print("OUT", out)
