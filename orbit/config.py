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

"""配置持久化。

配置保存在 .\\data\\config.json。
使用原子替换写入，损坏的配置会被备份并回退到默认值。
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass, fields
from datetime import datetime
from pathlib import Path

from orbit.audio.formats import get_output_format
from orbit.util.paths import config_path, default_output_dir

log = logging.getLogger(__name__)


@dataclass
class AppConfig:
    # 音频源
    device_name: str = ""
    device_index: int = -1
    sample_rate: int = 0  # 0 = 跟随设备原生采样率
    channels: int = 0  # 0 = 跟随设备原生声道数
    bit_depth: int = 32
    buffer_ms: int = 20

    # 输出
    output_format: str = "wav"
    output_dir: str = ""
    name_template: str = "{date}_{time}_{device}"
    metadata_enabled: bool = True
    bitrate_kbps: int = 320

    # 自动控制
    split_minutes: int = 0
    split_size_mb: int = 0
    max_minutes: int = 0
    schedule_enabled: bool = False
    schedule_time: str = "23:00"

    # 系统集成
    close_to_tray: bool = True
    notify_on_complete: bool = True
    hotkeys_enabled: bool = False
    tray_hint_shown: bool = False

    # 试听播放器
    player_volume: int = 85  # 0-100

    # 调试
    ffmpeg_path: str = ""
    log_level: str = "INFO"
    log_visible: bool = False

    # 窗口状态（Base64 编码的 QByteArray）
    window_geometry: str = ""

    def __post_init__(self) -> None:
        self.normalize()

    def normalize(self) -> None:
        """把来自旧配置或用户手改的值收敛到合法范围。"""
        if not self.output_dir:
            self.output_dir = str(default_output_dir())

        fmt = get_output_format(self.output_format)
        self.output_format = fmt.key
        if self.bit_depth not in fmt.allowed_depths:
            self.bit_depth = fmt.default_depth

        if self.sample_rate not in {0, 22050, 32000, 44100, 48000, 88200, 96000, 176400, 192000}:
            self.sample_rate = 0
        self.channels = self.channels if self.channels in {0, 1, 2, 4, 6, 8} else 0
        self.buffer_ms = min(200, max(5, int(self.buffer_ms or 20)))
        self.bitrate_kbps = min(512, max(64, int(self.bitrate_kbps or 320)))
        self.split_minutes = max(0, min(24 * 60, int(self.split_minutes or 0)))
        self.split_size_mb = max(0, min(64 * 1024, int(self.split_size_mb or 0)))
        self.max_minutes = max(0, min(24 * 60, int(self.max_minutes or 0)))

        if self.log_level not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
            self.log_level = "INFO"
        try:
            hour, minute = (int(x) for x in self.schedule_time.split(":", 1))
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError
            self.schedule_time = f"{hour:02d}:{minute:02d}"
        except Exception:
            self.schedule_time = "23:00"

        if not self.name_template.strip():
            self.name_template = "{date}_{time}_{device}"

        try:
            self.player_volume = min(100, max(0, int(self.player_volume)))
        except (TypeError, ValueError):
            self.player_volume = 85

    @property
    def split_seconds(self) -> int:
        return self.split_minutes * 60

    @property
    def split_bytes(self) -> int:
        return self.split_size_mb * 1024 * 1024

    @property
    def max_seconds(self) -> int:
        return self.max_minutes * 60

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "AppConfig":
        known = {f.name for f in fields(cls)}
        clean = {k: v for k, v in data.items() if k in known}
        return cls(**clean)


class ConfigStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path else config_path()

    def load(self) -> AppConfig:
        if not self.path.exists():
            cfg = AppConfig()
            log.info("首次运行，使用默认配置：%s", self.path)
            return cfg
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            payload = raw.get("settings", raw) if isinstance(raw, dict) else {}
            cfg = AppConfig.from_dict(payload)
            log.info("已加载配置：%s", self.path)
            return cfg
        except Exception as exc:
            backup = self.path.with_name(
                f"config.broken-{datetime.now():%Y%m%d-%H%M%S}.json"
            )
            try:
                self.path.replace(backup)
                log.error("配置损坏，已备份到 %s：%s", backup, exc)
            except OSError:
                log.exception("配置损坏且备份失败：%s", exc)
            return AppConfig()

    def save(self, cfg: AppConfig) -> None:
        cfg.normalize()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "settings": cfg.to_dict(),
        }
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        # 原子写入：临时文件 + os.replace
        fd, tmp_name = tempfile.mkstemp(
            prefix="config-", suffix=".tmp", dir=str(self.path.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, self.path)
            log.info("配置已保存：%s", self.path)
        finally:
            if os.path.exists(tmp_name):
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
