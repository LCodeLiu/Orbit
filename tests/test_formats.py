from __future__ import annotations

from orbit.audio.formats import (
    get_output_format,
    get_sample_format,
    validate_rate_for_format,
)


def test_output_format_defaults() -> None:
    assert get_output_format("unknown").key == "wav"
    assert get_output_format("FLAC").key == "flac"
    assert get_output_format("alac").requires_ffmpeg
    assert not get_output_format("wav").requires_ffmpeg


def test_depths() -> None:
    assert get_output_format("wav").allowed_depths == (16, 24, 32)
    assert get_output_format("flac").allowed_depths == (16, 24)
    assert get_sample_format(24).soundfile_subtype == "PCM_24"
    assert get_sample_format(32).is_float


def test_rate_validation_without_resampling() -> None:
    mp3 = get_output_format("mp3")
    assert validate_rate_for_format(mp3, 48000)[0]
    assert not validate_rate_for_format(mp3, 96000)[0]
    assert validate_rate_for_format(get_output_format("wav"), 96000)[0]
