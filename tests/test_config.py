from __future__ import annotations

import json
from pathlib import Path

from orbit.config import AppConfig, ConfigStore


def test_normalize_invalid_values() -> None:
    cfg = AppConfig(
        output_format="flac",
        bit_depth=32,
        buffer_ms=500,
        sample_rate=12345,
        channels=3,
        split_minutes=-4,
        log_level="TRACE",
        schedule_time="99:99",
        name_template="",
    )
    assert cfg.output_format == "flac"
    assert cfg.bit_depth == 24
    assert cfg.buffer_ms == 200
    assert cfg.sample_rate == 0
    assert cfg.channels == 0
    assert cfg.split_minutes == 0
    assert cfg.log_level == "INFO"
    assert cfg.schedule_time == "23:00"
    assert cfg.name_template


def test_save_and_load(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path / "config.json")
    cfg = AppConfig(output_dir=str(tmp_path / "out"), bit_depth=24, buffer_ms=35)
    store.save(cfg)
    payload = json.loads(store.path.read_text(encoding="utf-8"))
    assert payload["version"] == 1
    loaded = store.load()
    assert loaded.bit_depth == 24
    assert loaded.buffer_ms == 35
    assert loaded.output_dir == str(tmp_path / "out")


def test_corrupt_config_is_backed_up(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text("{broken", encoding="utf-8")
    store = ConfigStore(path)
    cfg = store.load()
    assert cfg.output_format == "wav"
    backups = list(tmp_path.glob("config.broken-*.json"))
    assert len(backups) == 1
