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

"""路径、文件大小与系统外壳相关工具。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from orbit.constants import ORG_NAME


def app_data_dir() -> Path:
    """配置目录：%APPDATA%\\Orbit。"""
    base = os.environ.get("APPDATA")
    root = Path(base) if base else Path.home() / "AppData" / "Roaming"
    return root / ORG_NAME


def local_data_dir() -> Path:
    """日志目录：%LOCALAPPDATA%\\Orbit。"""
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) if base else Path.home() / "AppData" / "Local"
    return root / ORG_NAME


def config_path() -> Path:
    return app_data_dir() / "config.json"


def log_dir() -> Path:
    return local_data_dir() / "logs"


def default_output_dir() -> Path:
    music = Path.home() / "Music"
    if not music.exists():
        music = Path.home() / "音乐"
    if not music.exists():
        music = Path.home()
    return music / "Orbit"


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def human_size(num_bytes: int | float) -> str:
    n = float(max(0, num_bytes))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(n)} B"
            return f"{n:.2f} {unit}"
        n /= 1024
    return f"{n:.2f} TB"


def format_duration(seconds: float, tenths: bool = False) -> str:
    seconds = max(0.0, float(seconds))
    whole = int(seconds)
    hours, rem = divmod(whole, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        base = f"{hours:02d}:{minutes:02d}:{secs:02d}"
    else:
        base = f"{minutes:02d}:{secs:02d}"
    if tenths:
        base += f".{int((seconds - whole) * 10) % 10}"
    return base


def open_path(path: Path) -> None:
    """用系统默认程序打开文件或文件夹。"""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    if sys.platform == "win32":
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def reveal_path(path: Path) -> None:
    """在资源管理器中定位文件。"""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    if sys.platform == "win32":
        subprocess.Popen(["explorer", "/select,", str(path)])
    else:
        open_path(path.parent)


def shorten_path(path: Path, max_chars: int = 52) -> str:
    text = str(path)
    if len(text) <= max_chars:
        return text
    keep = max_chars - 3
    head = max(8, keep // 3)
    tail = keep - head
    return f"{text[:head]}...{text[-tail:]}"


def is_windows() -> bool:
    return sys.platform == "win32"
