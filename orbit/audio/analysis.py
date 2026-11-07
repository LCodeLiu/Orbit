# Copyright 2026 LCode
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""PCM 解码、电平统计与频谱分析。

所有可视化计算都使用 float32
"""

from __future__ import annotations

import numpy as np

from orbit.audio.formats import SampleFormat


def decode_pcm24(data: bytes) -> np.ndarray:
    """把紧排的 24-bit little-endian PCM 解码为归一化 float32。"""
    raw = np.frombuffer(data, dtype=np.uint8)
    if raw.size % 3 != 0:
        raw = raw[: raw.size - raw.size % 3]
    triples = raw.reshape(-1, 3).astype(np.int32)
    values = triples[:, 0] | (triples[:, 1] << 8) | (triples[:, 2] << 16)
    values = (values ^ 0x800000) - 0x800000  # 符号扩展
    return (values.astype(np.float32) / 8_388_608.0).astype(np.float32, copy=False)


def decode_to_float(
    data: bytes, sample_format: SampleFormat, channels: int
) -> np.ndarray:
    """返回 (frames, channels) 的 float32 数组，范围约 [-1, 1]。"""
    channels = max(1, int(channels))
    if sample_format.key == "float32":
        arr = np.frombuffer(data, dtype="<f4").astype(np.float32, copy=False)
        usable = arr.size - (arr.size % channels)
        return arr[:usable].reshape(-1, channels)
    if sample_format.key == "pcm16":
        arr = np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768.0
        usable = arr.size - (arr.size % channels)
        return arr[:usable].reshape(-1, channels)
    if sample_format.key == "pcm24":
        arr = decode_pcm24(data)
        usable = arr.size - (arr.size % channels)
        return arr[:usable].reshape(-1, channels)
    if sample_format.key == "pcm32":
        arr = np.frombuffer(data, dtype="<i4").astype(np.float32) / 2_147_483_648.0
        usable = arr.size - (arr.size % channels)
        return arr[:usable].reshape(-1, channels)
    raise ValueError(f"未知采样格式：{sample_format.key}")


def block_levels(frames: np.ndarray) -> tuple[list[float], list[float]]:
    """逐声道返回 (峰值, RMS)，线性幅度。"""
    if frames.size == 0:
        return [], []
    peaks = np.max(np.abs(frames), axis=0)
    rms = np.sqrt(np.mean(frames.astype(np.float64) ** 2, axis=0))
    return peaks.astype(float).tolist(), rms.astype(float).tolist()


def amplitude_to_meter(amplitude: float, floor_db: float = -60.0) -> float:
    """把线性幅度映射到 0..1 的显示区间。"""
    if amplitude <= 1e-9:
        return 0.0
    db = 20.0 * np.log10(max(amplitude, 1e-9))
    return float(min(1.0, max(0.0, (db - floor_db) / -floor_db)))


def amplitude_to_db(amplitude: float) -> float:
    if amplitude <= 1e-9:
        return -120.0
    return float(20.0 * np.log10(amplitude))


def spectrum_bands(
    samples: np.ndarray,
    sample_rate: int,
    band_count: int = 56,
    min_hz: float = 35.0,
    max_hz: float = 20_000.0,
) -> np.ndarray:
    """对数频段能量，返回 0..1 的数组。"""
    if samples.size < 512 or sample_rate <= 0:
        return np.zeros(band_count, dtype=np.float32)
    usable = min(samples.size, 8192)
    x = samples[-usable:].astype(np.float32, copy=False)
    x = x - float(np.mean(x))
    window = np.hanning(x.size).astype(np.float32)
    spectrum = np.abs(np.fft.rfft(x * window))
    freqs = np.fft.rfftfreq(x.size, 1.0 / sample_rate)
    max_hz = min(max_hz, sample_rate / 2.0)
    if max_hz <= min_hz:
        return np.zeros(band_count, dtype=np.float32)
    edges = np.geomspace(min_hz, max_hz, band_count + 1)
    out = np.zeros(band_count, dtype=np.float32)
    norm = max(1.0, x.size / 2.0)
    for i in range(band_count):
        mask = (freqs >= edges[i]) & (freqs < edges[i + 1])
        if not np.any(mask):
            idx = int(np.searchsorted(freqs, (edges[i] + edges[i + 1]) / 2))
            idx = min(idx, spectrum.size - 1)
            value = spectrum[idx]
        else:
            value = float(np.max(spectrum[mask]))
        db = 20.0 * np.log10(max(value / norm, 1e-9))
        out[i] = min(1.0, max(0.0, (db + 72.0) / 72.0))
    return out


def waveform_points(samples: np.ndarray, points: int = 240) -> np.ndarray:
    """把一段波形降采样为对称包络点（取分块峰值）。"""
    if samples.size == 0:
        return np.zeros(points, dtype=np.float32)
    x = np.abs(samples.astype(np.float32, copy=False))
    if x.size <= points:
        padded = np.zeros(points, dtype=np.float32)
        padded[-x.size :] = x
        return padded
    chunk = x.size // points
    usable = chunk * points
    return x[:usable].reshape(points, chunk).max(axis=1)
