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

"""应用级常量。"""

from __future__ import annotations

APP_NAME = "Orbit"
APP_NAME_CN = "Orbit音频采集"
ORG_NAME = "Orbit"
VERSION = "1.0.9"
BACKEND_NAME = "WASAPI Loopback"
WINDOW_TITLE = "Orbit 音频采集"

# 应用生成的录音不会写入这些临时文件
TEMP_PREFIX = ".orbit_tmp_"
PART_SUFFIX = ".part"

# WAV 单文件容量上限（RIFF 为 32 位长度字段，预留元数据空间）
WAV_MAX_DATA_BYTES = 3_900_000_000

SUPPORTED_AUDIO_EXTENSIONS = {
    ".wav",
    ".flac",
    ".m4a",
    ".mp3",
    ".aac",
    ".ogg",
}
