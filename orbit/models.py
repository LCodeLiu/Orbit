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

"""跨层数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class AudioDevice:
    index: int
    name: str
    channels: int
    sample_rate: int
    is_default: bool = False
    host_api: str = "Windows WASAPI"
    loopback: bool = True

    @property
    def clean_name(self) -> str:
        return self.name.replace(" [Loopback]", "").strip()

    @property
    def display_name(self) -> str:
        suffix = "  ·  默认" if self.is_default else ""
        return f"{self.clean_name}{suffix}"

    @property
    def native_summary(self) -> str:
        return f"{self.sample_rate:,} Hz · {self.channels} ch"


@dataclass
class DeviceInventory:
    devices: list[AudioDevice] = field(default_factory=list)
    default_index: int | None = None
    portaudio_version: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


@dataclass(frozen=True)
class RecordingRequest:
    device: AudioDevice
    sample_rate: int
    channels: int
    bit_depth: int
    buffer_ms: int
    output_format: str
    output_dir: Path
    base_name: str
    bitrate_kbps: int
    metadata_enabled: bool
    split_seconds: int = 0
    split_bytes: int = 0
    ffmpeg_path: str = ""
    max_seconds: int = 0


@dataclass
class RecordingFileInfo:
    path: Path
    size: int
    modified: datetime
    output_format: str

    @property
    def extension(self) -> str:
        return self.path.suffix.lower()

    @property
    def stem(self) -> str:
        return self.path.stem


@dataclass
class RecordingResult:
    files: list[Path] = field(default_factory=list)
    preserved_sources: list[Path] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    elapsed: float = 0.0
    frames: int = 0
    dropped_frames: int = 0
    overflows: int = 0
