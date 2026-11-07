"""开发期自检：WAV/FLAC 写入与元数据。"""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

from orbit.audio.formats import get_sample_format
from orbit.audio.sinks import FlacSink, WavSink

out = Path(tempfile.mkdtemp(prefix="aa_sink_"))
fs = 48000
ch = 2
n = 48000
t = np.arange(n) / fs
sig = np.stack(
    [0.2 * np.sin(2 * np.pi * 440 * t), 0.1 * np.sin(2 * np.pi * 880 * t)], axis=1
).astype(np.float32)

wav = WavSink(out / "test_float.wav", fs, ch, get_sample_format(32))
wav.write(sig.tobytes())
wav.finalize(
    {"title": "测试标题", "artist": "设备", "comment": "hello", "date": "2026-10-24"}
)
info = sf.info(out / "test_float.wav")
print("wav float", info, info.subtype)
back, br = sf.read(out / "test_float.wav", dtype="float32")
print("wav maxerr", np.max(np.abs(back - sig)))
handle = sf.SoundFile(out / "test_float.wav")
print("wav meta:", handle.title, handle.artist, handle.comment, handle.date)
handle.close()

ints = np.clip(np.round(sig * 8388607), -8388608, 8388607).astype(np.int32)
packed = np.empty((n, ch, 3), np.uint8)
packed[:, :, 0] = ints & 255
packed[:, :, 1] = (ints >> 8) & 255
packed[:, :, 2] = (ints >> 16) & 255

wav24 = WavSink(out / "test_24.wav", fs, ch, get_sample_format(24))
wav24.write(packed.tobytes())
wav24.finalize({"title": "24bit"})
info = sf.info(out / "test_24.wav")
print("wav24", info, info.subtype)
back, br = sf.read(out / "test_24.wav", dtype="int32")
print("wav24 range", back.min(), back.max())

flac = FlacSink(out / "test.flac", fs, ch, get_sample_format(24), "PCM_24")
flac.write(packed.tobytes())
flac.finalize(
    {
        "title": "FLAC标题",
        "artist": "设备",
        "comment": "测试",
        "date": "2026-10-24",
        "software": "Orbit",
    }
)
info = sf.info(out / "test.flac")
print("flac", info, info.subtype)
handle = sf.SoundFile(out / "test.flac")
print("flac meta:", handle.title, handle.artist, handle.comment, handle.date, handle.software)
handle.close()
print("files", [(p.name, p.stat().st_size) for p in out.iterdir()])
print("out", out)
