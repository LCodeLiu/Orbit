from __future__ import annotations

import numpy as np

from orbit.audio.analysis import (
    amplitude_to_db,
    amplitude_to_meter,
    block_levels,
    decode_to_float,
    spectrum_bands,
)
from orbit.audio.formats import get_sample_format


def test_decode_int16_and_float() -> None:
    values = np.array([-32768, 0, 16384, 32767], dtype=np.int16)
    decoded = decode_to_float(values.tobytes(), get_sample_format(16), 2)
    assert decoded.shape == (2, 2)
    assert decoded[0, 0] == -1.0
    assert 0.49 < decoded[1, 0] < 0.51

    floats = np.array([[-0.5, 0.5], [0.25, -0.25]], dtype=np.float32)
    decoded = decode_to_float(floats.tobytes(), get_sample_format(32), 2)
    assert np.array_equal(decoded, floats)


def test_decode_24bit_sign() -> None:
    raw = np.array([0x00, 0x00, 0x80, 0xFF, 0xFF, 0x7F], dtype=np.uint8).tobytes()
    decoded = decode_to_float(raw, get_sample_format(24), 1)
    assert decoded[0, 0] == -1.0
    assert 0.999999 < decoded[1, 0] <= 1.0


def test_levels_and_meter() -> None:
    frames = np.array([[1.0], [0.0], [-1.0], [0.0]], dtype=np.float32)
    peaks, rms = block_levels(frames)
    assert peaks[0] == 1.0
    assert abs(rms[0] - 0.70710678) < 1e-5
    assert amplitude_to_meter(1.0) == 1.0
    assert amplitude_to_meter(0.0) == 0.0
    assert amplitude_to_db(0.0) < -100


def test_spectrum_peak_at_tone() -> None:
    fs = 48000
    t = np.arange(4096) / fs
    tone = np.sin(2 * np.pi * 1000 * t).astype(np.float32)
    bands = spectrum_bands(tone, fs)
    assert bands.shape == (56,)
    assert bands.max() > 0.8
    assert np.argmax(bands) > 0
