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

"""录音文件自动命名。"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_MULTI_SPACE = re.compile(r"\s+")
_WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
_TOKEN_RE = re.compile(r"\{([a-zA-Z_]+)\}")


def sanitize_filename(text: str, max_chars: int = 120) -> str:
    """生成 Windows 合法文件名（不含扩展名）。"""
    value = _INVALID_CHARS.sub("_", str(text))
    value = _MULTI_SPACE.sub(" ", value).strip(" .")
    if not value:
        value = "Recording"
    if value.upper() in _WINDOWS_RESERVED:
        value = f"_{value}"
    value = value[:max_chars].rstrip(" .")
    return value or "Recording"


def _device_short(device_name: str) -> str:
    """去掉设备名末尾的驱动/序号括号，保留可读的端点名。

    设备名可能包含嵌套括号，例如“耳机 (2- Realtek(R) Audio)”。
    因此从末尾反复剥离完整括号组，而不是匹配第一个右括号。
    """
    short = device_name.replace("[Loopback]", "").strip()
    pattern = re.compile(r"\s*\([^()]*(?:\([^()]*\)[^()]*)*\)\s*$")
    for _ in range(3):
        new_value = pattern.sub("", short).strip()
        if new_value == short:
            break
        short = new_value
    return short or device_name


def build_tokens(
    device_name: str,
    output_format: str,
    sample_rate: int,
    bit_depth: int,
    channels: int,
    when: datetime | None = None,
    part: int | None = None,
) -> dict[str, str]:
    when = when or datetime.now()
    if channels == 1:
        channel_text = "Mono"
    elif channels == 2:
        channel_text = "Stereo"
    else:
        channel_text = f"{channels}ch"
    tokens = {
        "date": when.strftime("%Y-%m-%d"),
        "time": when.strftime("%H-%M-%S"),
        "datetime": when.strftime("%Y-%m-%d_%H-%M-%S"),
        "device": _device_short(device_name),
        "device_full": device_name,
        "format": output_format.upper(),
        "sample_rate": str(sample_rate),
        "bit_depth": str(bit_depth),
        "channels": channel_text,
    }
    if part is not None:
        tokens["part"] = f"{part:02d}"
    return tokens


def render_template(template: str, tokens: dict[str, str]) -> str:
    """替换 {token}；未知 token 原样保留，便于用户发现问题。"""
    # 兼容用户误输入 {{date}} 的情况
    normalized = template.replace("{{", "{").replace("}}", "}")

    def repl(match: re.Match[str]) -> str:
        return tokens.get(match.group(1), match.group(0))

    rendered = _TOKEN_RE.sub(repl, normalized)
    return sanitize_filename(rendered)


def preview_filename(
    template: str,
    device_name: str,
    output_format: str,
    sample_rate: int,
    bit_depth: int,
    channels: int,
    extension: str,
    when: datetime | None = None,
) -> str:
    tokens = build_tokens(
        device_name, output_format, sample_rate, bit_depth, channels, when=when
    )
    return f"{render_template(template, tokens)}{extension}"


def unique_path(directory: Path, stem: str, extension: str, reserved: set[Path] | None = None) -> Path:
    """避免覆盖已有文件；返回带 (2)、(3) 后缀的路径。"""
    directory = Path(directory)
    reserved = reserved or set()
    extension = extension if extension.startswith(".") else f".{extension}"
    candidate = directory / f"{stem}{extension}"
    index = 2
    while candidate.exists() or candidate in reserved:
        candidate = directory / f"{stem} ({index}){extension}"
        index += 1
    return candidate
