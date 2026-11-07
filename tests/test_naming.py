from __future__ import annotations

from datetime import datetime
from pathlib import Path

from orbit.util.naming import (
    build_tokens,
    preview_filename,
    render_template,
    sanitize_filename,
    unique_path,
)


def test_sanitize_windows_chars() -> None:
    assert sanitize_filename('a:b*c?d"e<f>g|h') == "a_b_c_d_e_f_g_h"
    assert sanitize_filename("  ...  ") == "Recording"
    assert sanitize_filename("CON") == "_CON"
    assert sanitize_filename("x" * 300)[:1] == "x"
    assert len(sanitize_filename("x" * 300)) <= 120


def test_nested_device_parentheses() -> None:
    tokens = build_tokens(
        "耳机 (2- Realtek(R) Audio)",
        "wav",
        48000,
        32,
        2,
        when=datetime(2026, 10, 24, 9, 30, 0),
    )
    assert tokens["device"] == "耳机"
    assert tokens["date"] == "2026-10-24"
    assert tokens["time"] == "09-30-00"
    assert render_template("{date}_{time}_{device}", tokens) == "2026-10-24_09-30-00_耳机"


def test_unknown_token_is_kept() -> None:
    tokens = build_tokens("Speakers", "flac", 44100, 24, 2)
    assert "{unknown}" in render_template("{date}_{unknown}", tokens)


def test_preview_filename() -> None:
    text = preview_filename(
        "{date}_{device}_{format}_{bit_depth}bit",
        "扬声器 (Realtek Audio)",
        "flac",
        48000,
        24,
        2,
        ".flac",
        when=datetime(2026, 1, 2, 3, 4, 5),
    )
    assert text == "2026-01-02_扬声器_FLAC_24bit.flac"


def test_unique_path(tmp_path: Path) -> None:
    first = tmp_path / "a.wav"
    first.write_bytes(b"x")
    reserved = {tmp_path / "a (2).wav"}
    result = unique_path(tmp_path, "a", ".wav", reserved)
    assert result.name == "a (3).wav"
