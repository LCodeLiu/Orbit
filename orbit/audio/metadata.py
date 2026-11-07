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

"""FLAC 元数据写入。

libsndfile 的字符串元数据支持取决于发行版和版本，因此统一用 mutagen
写入 Vorbis Comment，兼容中文且不会触碰音频数据。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Mapping

log = logging.getLogger(__name__)

_FIELD_MAP = {
    "title": "title",
    "artist": "artist",
    "album": "album",
    "comment": "comment",
    "date": "date",
    "software": "encoder",
    "encoder": "encoder",
    "device": "device",
}


def write_flac_tags(path: Path, metadata: Mapping[str, str]) -> None:
    if not metadata:
        return
    try:
        from mutagen.flac import FLAC
    except Exception as exc:  # pragma: no cover - 可选依赖
        log.warning("mutagen 不可用，FLAC 元数据未写入：%s", exc)
        return

    audio = FLAC(str(path))
    for source_key, target_key in _FIELD_MAP.items():
        value = metadata.get(source_key)
        if value:
            audio[target_key] = str(value)
    try:
        audio.save()
        log.debug("FLAC 元数据已写入：%s", path.name)
    except Exception:
        log.exception("FLAC 元数据写入失败：%s", path)


def read_tags(path: Path) -> dict[str, str]:
    """读取 FLAC 的常用标签（供调试/文件详情使用）。"""
    try:
        from mutagen.flac import FLAC

        audio = FLAC(str(path))
        return {key: " / ".join(audio.get(key, [])) for key in audio.keys()}
    except Exception:
        return {}
