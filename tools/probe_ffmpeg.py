"""开发期自检：FFmpeg 编码器与四种转码输出。"""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

from orbit.audio.ffmpeg import inspect_ffmpeg, probe_audio, transcode
from orbit.audio.formats import OUTPUT_FORMATS, get_sample_format
from orbit.audio.sinks import WavSink

out = Path(tempfile.mkdtemp(prefix="aa_ff_"))
fs = 48000
ch = 2
n = fs * 2
t = np.arange(n) / fs
sig = np.stack(
    [0.25 * np.sin(2 * np.pi * 997 * t), 0.15 * np.sin(2 * np.pi * 440 * t)], axis=1
).astype(np.float32)

ints = np.clip(np.round(sig * 8388607), -8388608, 8388607).astype(np.int32)
packed = np.empty((n, ch, 3), np.uint8)
packed[:, :, 0] = ints & 255
packed[:, :, 1] = (ints >> 8) & 255
packed[:, :, 2] = (ints >> 16) & 255
source = out / "source.wav"
sink = WavSink(source, fs, ch, get_sample_format(24))
sink.write(packed.tobytes())
sink.finalize()

info = inspect_ffmpeg()
print("FFmpeg:", info.available, info.path, info.version)
print("encoders:", {k: info.has_encoder(k) for k in ("alac", "aac", "libmp3lame", "libvorbis")})
for key in ("alac", "mp3", "aac", "ogg"):
    fmt = OUTPUT_FORMATS[key]
    goal = out / f"out{fmt.extension}"
    try:
        transcode(
            source,
            goal,
            fmt,
            320,
            {
                "title": "测试标题",
                "artist": "测试设备",
                "comment": "hello",
                "date": "2026-10-24",
                "encoder": "Orbit",
            },
            sample_rate=fs,
            channels=ch,
            duration_seconds=2,
            progress=lambda p: None,
        )
        print(key, "OK", goal.stat().st_size, probe_audio(goal))
        if fmt.extension in (".mp3", ".ogg"):
            info2 = sf.info(goal)
            print("   sf:", info2.samplerate, info2.channels, info2.subtype, info2.duration)
    except Exception as exc:
        print(key, "FAIL", type(exc).__name__, exc)
print("out", out)
