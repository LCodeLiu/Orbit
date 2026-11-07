from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from orbit.audio import sinks as sinks_module
from orbit.audio.formats import get_sample_format
from orbit.audio.sinks import FlacSink, SinkCapacityError, WavSink


def _sine(frames: int = 4800, channels: int = 2) -> np.ndarray:
    t = np.arange(frames) / 48000
    mono = 0.23 * np.sin(2 * np.pi * 997 * t)
    return np.stack([mono * (1.0 - 0.1 * i) for i in range(channels)], axis=1).astype(np.float32)


def _pack24(samples: np.ndarray) -> bytes:
    ints = np.clip(np.round(samples * 8_388_607), -8_388_608, 8_388_607).astype(np.int32)
    packed = np.empty((*ints.shape, 3), dtype=np.uint8)
    packed[..., 0] = ints & 0xFF
    packed[..., 1] = (ints >> 8) & 0xFF
    packed[..., 2] = (ints >> 16) & 0xFF
    return packed.tobytes()


def _read_info_chunk(path: Path) -> dict[bytes, bytes]:
    """解析 WAV 尾部 LIST/INFO，返回 {子块ID: 原始字节}。"""
    import struct

    data = path.read_bytes()
    assert data[:4] == b"RIFF" and data[8:12] == b"WAVE"
    pos = 12
    info: dict[bytes, bytes] = {}
    while pos + 8 <= len(data):
        cid = data[pos : pos + 4]
        size = struct.unpack("<I", data[pos + 4 : pos + 8])[0]
        body = data[pos + 8 : pos + 8 + size]
        if cid == b"LIST" and body[:4] == b"INFO":
            inner = 4
            while inner + 8 <= len(body):
                sub = body[inner : inner + 4]
                sub_size = struct.unpack("<I", body[inner + 4 : inner + 8])[0]
                info[sub] = body[inner + 8 : inner + 8 + sub_size]
                inner += 8 + sub_size + (sub_size % 2)
            break
        pos += 8 + size + (size % 2)
    return info


def test_wav_float_roundtrip_with_metadata(tmp_path: Path) -> None:
    data = _sine()
    path = tmp_path / "float.wav"
    sink = WavSink(path, 48000, 2, get_sample_format(32))
    sink.write(data.tobytes())
    sink.finalize({"title": "测试标题", "artist": "设备", "date": "2026-10-24"})
    assert path.exists()
    assert not sink.part_path.exists()
    info = sf.info(path)
    assert info.samplerate == 48000
    assert info.channels == 2
    assert info.subtype == "FLOAT"
    back, _ = sf.read(path, dtype="float32")
    assert np.max(np.abs(back - data)) == 0.0

    # Windows 资源管理器按系统 ANSI 代码页（简体中文=GBK）解码 LIST INFO，
    # 并要求 NUL 结尾。这里验证写入的原始字节符合该规则（而非 UTF-8）。
    import locale

    ansi = locale.getpreferredencoding(False) or "utf-8"
    chunks = _read_info_chunk(path)
    assert chunks[b"INAM"].endswith(b"\x00")
    assert chunks[b"INAM"].rstrip(b"\x00").decode(ansi) == "测试标题"
    assert chunks[b"IART"].rstrip(b"\x00").decode(ansi) == "设备"
    assert chunks[b"ICRD"].rstrip(b"\x00").decode(ansi) == "2026-10-24"


def test_wav_16bit(tmp_path: Path) -> None:
    samples = _sine()
    ints = np.clip(np.round(samples * 32767), -32768, 32767).astype(np.int16)
    path = tmp_path / "pcm16.wav"
    sink = WavSink(path, 48000, 2, get_sample_format(16))
    sink.write(ints.tobytes())
    sink.finalize()
    info = sf.info(path)
    assert info.subtype == "PCM_16"
    back, _ = sf.read(path, dtype="int16")
    assert np.array_equal(back, ints)


def test_wav_24bit(tmp_path: Path) -> None:
    samples = _sine()
    path = tmp_path / "pcm24.wav"
    sink = WavSink(path, 48000, 2, get_sample_format(24))
    sink.write(_pack24(samples))
    sink.finalize()
    info = sf.info(path)
    assert info.subtype == "PCM_24"
    back, _ = sf.read(path, dtype="float32")
    assert np.max(np.abs(back - samples)) < 2e-6


def test_flac_24bit_and_tags(tmp_path: Path) -> None:
    samples = _sine()
    path = tmp_path / "lossless.flac"
    sink = FlacSink(path, 48000, 2, get_sample_format(24), "PCM_24")
    sink.write(_pack24(samples))
    sink.finalize(
        {
            "title": "FLAC 标题",
            "artist": "设备",
            "comment": "测试",
            "date": "2026-10-24",
            "software": "Orbit",
        }
    )
    info = sf.info(path)
    assert info.subtype == "PCM_24"
    assert info.samplerate == 48000
    back, _ = sf.read(path, dtype="float32")
    assert np.max(np.abs(back - samples)) < 2e-6

    from mutagen.flac import FLAC

    tags = FLAC(str(path))
    assert tags["title"] == ["FLAC 标题"]
    assert tags["artist"] == ["设备"]
    assert tags["encoder"] == ["Orbit"]


def test_wav_capacity_guard(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(sinks_module, "WAV_MAX_DATA_BYTES", 100)
    path = tmp_path / "limit.wav"
    sink = WavSink(path, 48000, 2, get_sample_format(32))
    with pytest.raises(SinkCapacityError):
        sink.write(b"\x00" * 1024)
    sink.abort()
    assert not path.exists()
    assert not sink.part_path.exists()
