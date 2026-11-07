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

"""FFmpeg / FFprobe 探测与无损/有损转码。

WAV 与 FLAC 由应用内直接写入；
ALAC、MP3、AAC、OGG 通过 FFmpeg 完成。转码前会锁定采样率与声道数，
避免 FFmpeg 在格式不支持时重采样。
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from orbit.audio.formats import OutputFormat

log = logging.getLogger(__name__)

_CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
_CACHE: dict[str, "FFmpegInfo"] = {}

ProgressCallback = Callable[[float], None]


class FFmpegError(RuntimeError):
    pass


@dataclass
class FFmpegInfo:
    path: str = ""
    ffprobe: str = ""
    version: str = ""
    encoders: set[str] = field(default_factory=set)
    error: str = ""

    @property
    def available(self) -> bool:
        return bool(self.path) and not self.error

    def has_encoder(self, name: str) -> bool:
        return name in self.encoders

    def supports(self, fmt: OutputFormat) -> bool:
        if not fmt.requires_ffmpeg:
            return True
        if not self.available:
            return False
        # 对 AAC 允许 ffmpeg 内置 encoder；其他编码器必须存在
        if fmt.codec == "aac":
            return "aac" in self.encoders or "libfdk_aac" in self.encoders
        return fmt.codec in self.encoders

    @property
    def summary(self) -> str:
        if self.available:
            return f"FFmpeg {self.version or '可用'}"
        return self.error or "未找到 FFmpeg"


def _candidate_paths(explicit: str = "") -> list[Path]:
    candidates: list[Path] = []
    if explicit:
        p = Path(explicit).expanduser()
        if p.is_dir():
            p = p / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
        candidates.append(p)
    env = os.environ.get("FFMPEG_BINARY", "").strip()
    if env:
        candidates.append(Path(env))
    found = shutil.which("ffmpeg")
    if found:
        candidates.append(Path(found))
    if os.name == "nt":
        local = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
        candidates.extend(
            [
                Path("C:/ffmpeg/bin/ffmpeg.exe"),
                Path("C:/Program Files/ffmpeg/bin/ffmpeg.exe"),
                local / "Microsoft/WinGet/Links/ffmpeg.exe",
                Path(__file__).resolve().parents[2] / "tools/ffmpeg/bin/ffmpeg.exe",
            ]
        )
    return candidates


def _run_quick(cmd: list[str], timeout: int = 12) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        creationflags=_CREATE_NO_WINDOW,
        check=False,
    )


def inspect_ffmpeg(explicit: str = "", refresh: bool = False) -> FFmpegInfo:
    """定位 FFmpeg 并读取版本/编码器；结果按路径缓存。"""
    key = explicit.strip().lower()
    if not refresh and key in _CACHE:
        return _CACHE[key]

    errors: list[str] = []
    for candidate in _candidate_paths(explicit):
        try:
            if not candidate.is_file():
                continue
            result = _run_quick([str(candidate), "-hide_banner", "-version"])
            if result.returncode != 0:
                errors.append(f"{candidate}: {result.stderr.strip()[:200]}")
                continue
            version_line = (result.stdout or "").splitlines()[0] if result.stdout else ""
            version = version_line.replace("ffmpeg version ", "").split(" Copyright")[0].strip()
            enc = _run_quick([str(candidate), "-hide_banner", "-encoders"], timeout=20)
            encoders: set[str] = set()
            for line in (enc.stdout or "").splitlines():
                parts = line.split()
                if len(parts) >= 2 and len(parts[0]) == 6:
                    encoders.add(parts[1])
            probe = candidate.with_name(
                "ffprobe.exe" if os.name == "nt" else "ffprobe"
            )
            info = FFmpegInfo(
                path=str(candidate),
                ffprobe=str(probe) if probe.is_file() else (shutil.which("ffprobe") or ""),
                version=version,
                encoders=encoders,
            )
            if not info.ffprobe:
                log.debug("未找到 ffprobe，编码后校验将跳过")
            log.info("FFmpeg 可用：%s（%s）", candidate, version)
            _CACHE[key] = info
            return info
        except Exception as exc:
            errors.append(f"{candidate}: {exc}")

    detail = explicit or "PATH"
    msg = f"未找到可用的 FFmpeg（查找来源：{detail}）。"
    if errors:
        msg += " " + " | ".join(errors[:2])
    info = FFmpegInfo(error=msg)
    _CACHE[key] = info
    log.warning(msg)
    return info


def _popen_kwargs() -> dict:
    return {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "creationflags": _CREATE_NO_WINDOW,
    }


def _codec_args(fmt: OutputFormat, bitrate_kbps: int) -> list[str]:
    if fmt.key == "alac":
        return ["-c:a", "alac"]
    if fmt.key == "mp3":
        return [
            "-c:a",
            "libmp3lame",
            "-b:a",
            f"{bitrate_kbps}k",
            "-id3v2_version",
            "3",
        ]
    if fmt.key == "aac":
        return [
            "-c:a",
            "aac",
            "-b:a",
            f"{bitrate_kbps}k",
            "-movflags",
            "+faststart",
        ]
    if fmt.key == "ogg":
        return ["-c:a", "libvorbis", "-b:a", f"{bitrate_kbps}k"]
    raise FFmpegError(f"不支持的转码目标：{fmt.key}")


def transcode(
    source: Path,
    destination: Path,
    fmt: OutputFormat,
    bitrate_kbps: int,
    metadata: dict[str, str] | None = None,
    ffmpeg_path: str = "",
    sample_rate: int = 0,
    channels: int = 0,
    duration_seconds: float = 0,
    progress: ProgressCallback | None = None,
) -> Path:
    """把临时 WAV 转为目标格式，成功后原子替换目标文件。

    失败时保留源 WAV，由 Recorder 负责重命名保留。
    """
    source = Path(source)
    destination = Path(destination)
    if not source.is_file() or source.stat().st_size == 0:
        raise FFmpegError("临时 WAV 不存在或为空")

    info = inspect_ffmpeg(ffmpeg_path)
    if not info.available:
        raise FFmpegError(info.error)
    if not info.supports(fmt):
        raise FFmpegError(f"当前 FFmpeg 不包含 {fmt.codec} 编码器，无法输出 {fmt.label}。")

    destination.parent.mkdir(parents=True, exist_ok=True)
    part = destination.with_name(f"{destination.stem}.part{destination.suffix}")
    try:
        part.unlink(missing_ok=True)
    except OSError:
        pass

    cmd = [
        info.path,
        "-hide_banner",
        "-nostdin",
        "-y",
        "-loglevel",
        "error",
        "-progress",
        "pipe:1",
        "-nostats",
        "-i",
        str(source),
        "-map",
        "0:a:0",
        "-vn",
        "-sn",
        "-dn",
        "-map_metadata",
        "-1",
    ]
    if sample_rate > 0:
        cmd += ["-ar", str(sample_rate)]
    if channels > 0:
        cmd += ["-ac", str(channels)]
    cmd += _codec_args(fmt, bitrate_kbps)

    for key, value in (metadata or {}).items():
        if value:
            cmd += ["-metadata", f"{key}={value}"]

    cmd.append(str(part))
    log.info("开始转码：%s → %s（%s）", source.name, destination.name, fmt.label)
    log.debug("FFmpeg 命令：%s", subprocess.list2cmdline(cmd))

    stderr_text = ""
    try:
        # stderr 写入临时文件，避免大量日志填满管道造成死锁
        with tempfile.TemporaryFile(
            mode="w+", encoding="utf-8", errors="replace"
        ) as stderr_file:
            kwargs = _popen_kwargs()
            kwargs["stderr"] = stderr_file
            proc = subprocess.Popen(cmd, **kwargs)
            assert proc.stdout is not None
            for raw in proc.stdout:
                line = raw.strip()
                if not line:
                    continue
                if line.startswith("out_time_us=") and duration_seconds > 0 and progress:
                    try:
                        seconds = int(line.split("=", 1)[1]) / 1_000_000
                        progress(max(0.0, min(0.99, seconds / duration_seconds)))
                    except (ValueError, ZeroDivisionError):
                        pass
                elif line == "progress=end" and progress:
                    progress(1.0)
            proc.wait(timeout=10)
            stderr_file.seek(0)
            stderr_text = stderr_file.read()
        if proc.returncode != 0:
            raise FFmpegError(
                f"FFmpeg 退出码 {proc.returncode}：{stderr_text.strip()[-900:]}"
            )
        if not part.is_file() or part.stat().st_size == 0:
            raise FFmpegError("FFmpeg 未生成有效输出文件")
        os.replace(part, destination)
        log.info("转码完成：%s（%s）", destination, _human_size(destination.stat().st_size))
        return destination
    except FileNotFoundError as exc:
        raise FFmpegError(f"无法启动 FFmpeg：{exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise FFmpegError(f"FFmpeg 无响应：{exc}") from exc
    finally:
        if part.exists():
            try:
                part.unlink()
            except OSError:
                pass


def probe_audio(path: Path, ffmpeg_path: str = "") -> dict:
    """用 ffprobe 读取实际采样率/声道/位深，用于事后校验。"""
    info = inspect_ffmpeg(ffmpeg_path)
    if not info.ffprobe:
        return {}
    cmd = [
        info.ffprobe,
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=codec_name,sample_rate,channels,bits_per_raw_sample,bits_per_sample,duration",
        "-of",
        "json",
        str(path),
    ]
    try:
        result = _run_quick(cmd, timeout=20)
        if result.returncode != 0:
            log.debug("ffprobe 失败：%s", result.stderr.strip()[:300])
            return {}
        payload = json.loads(result.stdout or "{}")
        streams = payload.get("streams") or []
        return streams[0] if streams else {}
    except Exception as exc:
        log.debug("ffprobe 异常：%s", exc)
        return {}


def _human_size(num: int) -> str:
    value = float(num)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.1f} GB"
