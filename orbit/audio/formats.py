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

"""采样格式与输出容器定义。

设计原则：
- 32-bit 指 32-bit float，即 WASAPI 共享混音的原生格式；
- 16/24-bit 指整数 PCM。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class SampleFormat:
    key: str
    label: str
    bits: int
    is_float: bool
    pyaudio_attr: str
    numpy_dtype: str
    soundfile_subtype: str

    @property
    def bytes_per_sample(self) -> int:
        return self.bits // 8

    @property
    def description(self) -> str:
        return f"{self.bits}-bit {'float' if self.is_float else 'PCM'}"


@dataclass(frozen=True)
class OutputFormat:
    key: str
    label: str
    extension: str
    lossless: bool
    requires_ffmpeg: bool
    allowed_depths: tuple[int, ...]
    default_depth: int
    codec: str
    description: str
    supported_rates: tuple[int, ...] = ()
    default_bitrate: int = 320

    @property
    def kind_label(self) -> str:
        return "无损" if self.lossless else "有损"

    @property
    def short_description(self) -> str:
        if self.lossless:
            return f"{self.label} · 无损"
        return f"{self.label} · 有损压缩"

    def rate_supported(self, rate: int) -> bool:
        if not self.supported_rates:
            return True
        return rate in self.supported_rates


SAMPLE_FORMATS: dict[int, SampleFormat] = {
    16: SampleFormat("pcm16", "16-bit PCM", 16, False, "paInt16", "int16", "PCM_16"),
    24: SampleFormat("pcm24", "24-bit PCM", 24, False, "paInt24", "int32", "PCM_24"),
    32: SampleFormat("float32", "32-bit 浮点", 32, True, "paFloat32", "float32", "FLOAT"),
}

OUTPUT_FORMATS: dict[str, OutputFormat] = {
    "wav": OutputFormat(
        key="wav",
        label="WAV",
        extension=".wav",
        lossless=True,
        requires_ffmpeg=False,
        allowed_depths=(16, 24, 32),
        default_depth=32,
        codec="PCM / IEEE Float",
        description="原生未压缩音频，质量最高，文件最大。",
    ),
    "flac": OutputFormat(
        key="flac",
        label="FLAC",
        extension=".flac",
        lossless=True,
        requires_ffmpeg=False,
        allowed_depths=(16, 24),
        default_depth=24,
        codec="FLAC",
        description="无损压缩，兼容性好，体积约为 WAV 的 50–70%。",
    ),
    "alac": OutputFormat(
        key="alac",
        label="ALAC (M4A)",
        extension=".m4a",
        lossless=True,
        requires_ffmpeg=True,
        allowed_depths=(16, 24),
        default_depth=24,
        codec="alac",
        description="Apple 无损编码，适合 Apple 生态；需要 FFmpeg。",
    ),
    "mp3": OutputFormat(
        key="mp3",
        label="MP3",
        extension=".mp3",
        lossless=False,
        requires_ffmpeg=True,
        allowed_depths=(16, 24),
        default_depth=24,
        codec="libmp3lame",
        description="通用有损格式；不可逆地丢弃音频细节。",
        supported_rates=(32000, 44100, 48000),
        default_bitrate=320,
    ),
    "aac": OutputFormat(
        key="aac",
        label="AAC (M4A)",
        extension=".m4a",
        lossless=False,
        requires_ffmpeg=True,
        allowed_depths=(16, 24),
        default_depth=24,
        codec="aac",
        description="高效有损格式，适合移动设备；不可逆压缩。",
        supported_rates=(44100, 48000, 88200, 96000),
        default_bitrate=256,
    ),
    "ogg": OutputFormat(
        key="ogg",
        label="OGG Vorbis",
        extension=".ogg",
        lossless=False,
        requires_ffmpeg=True,
        allowed_depths=(16, 24),
        default_depth=24,
        codec="libvorbis",
        description="开放有损格式，透明度和体积平衡较好。",
        supported_rates=(44100, 48000, 88200, 96000),
        default_bitrate=320,
    ),
}

FORMAT_ORDER = ("wav", "flac", "alac", "mp3", "aac", "ogg")

SAMPLE_RATE_OPTIONS: tuple[int, ...] = (
    44100,
    48000,
    88200,
    96000,
    176400,
    192000,
)

CHANNEL_OPTIONS = (1, 2, 4, 6, 8)
BITRATE_OPTIONS = (128, 160, 192, 256, 320)


def get_output_format(key: str) -> OutputFormat:
    return OUTPUT_FORMATS.get(str(key).lower(), OUTPUT_FORMATS["wav"])


def get_sample_format(bit_depth: int) -> SampleFormat:
    return SAMPLE_FORMATS.get(int(bit_depth), SAMPLE_FORMATS[32])


def format_choices() -> Iterable[OutputFormat]:
    return (OUTPUT_FORMATS[key] for key in FORMAT_ORDER)


def validate_rate_for_format(fmt: OutputFormat, sample_rate: int) -> tuple[bool, str]:
    if sample_rate <= 0:
        return True, ""
    if fmt.rate_supported(sample_rate):
        return True, ""
    allowed = ", ".join(f"{r / 1000:g}k" for r in fmt.supported_rates)
    return (
        False,
        f"{fmt.label} 不支持 {sample_rate:,} Hz（支持：{allowed}）。"
        "本应用不会自动重采样，请改用 48 kHz 或选择 WAV/FLAC。",
    )


def describe_channels(channels: int) -> str:
    if channels == 1:
        return "单声道"
    if channels == 2:
        return "立体声"
    return f"{channels} 声道"
