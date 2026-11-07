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

"""录音写入端。

WAV：应用内直接流式写 PCM / Float，结束后修补头部并追加 RIFF INFO 元数据。
FLAC：通过 libsndfile 流式写 16/24-bit，不产生中间 WAV。
其他格式：先写临时 WAV，再由 FFmpeg 转码（见 recorder.py）。
"""

from __future__ import annotations

import locale
import logging
import os
import struct
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Mapping

import soundfile as sf

from orbit.audio.analysis import decode_to_float
from orbit.audio.formats import SampleFormat
from orbit.constants import WAV_MAX_DATA_BYTES

log = logging.getLogger(__name__)


class SinkError(RuntimeError):
    pass


class SinkCapacityError(SinkError):
    """WAV RIFF 容量达到上限。"""


class BaseSink(ABC):
    def __init__(
        self,
        final_path: Path,
        sample_rate: int,
        channels: int,
        sample_format: SampleFormat,
    ) -> None:
        self.final_path = Path(final_path)
        self.part_path = self.final_path.with_name(self.final_path.name + ".part")
        self.sample_rate = int(sample_rate)
        self.channels = int(channels)
        self.sample_format = sample_format
        self.frames_written = 0
        self.bytes_written = 0
        self._closed = False
        self.final_path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def block_align(self) -> int:
        return self.channels * self.sample_format.bytes_per_sample

    def write(self, data: bytes) -> None:
        if self._closed:
            raise SinkError("写入端已关闭")
        if not data:
            return
        remainder = len(data) % self.block_align
        if remainder:
            data = data[: len(data) - remainder]
        if not data:
            return
        self._write(data)
        frames = len(data) // self.block_align
        self.frames_written += frames
        self.bytes_written += len(data)

    @abstractmethod
    def _write(self, data: bytes) -> None: ...

    @abstractmethod
    def finalize(
        self, metadata: Mapping[str, str] | None = None
    ) -> Path: ...

    @abstractmethod
    def abort(self) -> None: ...

    @property
    def size_bytes(self) -> int:
        try:
            return self.part_path.stat().st_size
        except OSError:
            return self.bytes_written

    @property
    def duration(self) -> float:
        return self.frames_written / self.sample_rate if self.sample_rate else 0.0


class WavSink(BaseSink):
    """手写 WAV writer，支持 16/24/32-bit PCM 与 32-bit float。

    元数据写在文件尾部的 RIFF LIST INFO 块。Windows 资源管理器对该块按
    系统 ANSI 代码页（简体中文为 GBK）解码，而不是 UTF-8；此前用 UTF-8
    编码导致“标题/作者”等显示为乱码或怪繁体字（如“耳机”→“鑰虫?”）。
    因此这里：

    - 字符串值以 GBK 编码（无法编码的字符降级为 UTF-8，避免抛异常）；
    - 每个值以 NUL 结尾（否则末字符会被 Explorer 截断）；
    - 字段映射经实测确认：INAM=标题、IART=作者/参与创作的艺术家、
      IPRD=唱片集、ICMT=备注、ICRD=发行日期、ICOP=版权、ISFT=编码器、
      ITCH=编码人员。
    """

    _INFO_KEYS = {
        "title": b"INAM",
        "artist": b"IART",
        "album": b"IPRD",
        "comment": b"ICMT",
        "date": b"ICRD",
        "copyright": b"ICOP",
        "software": b"ISFT",
        "encoder": b"ISFT",
        "device": b"ITCH",
    }

    def __init__(
        self,
        final_path: Path,
        sample_rate: int,
        channels: int,
        sample_format: SampleFormat,
    ) -> None:
        super().__init__(final_path, sample_rate, channels, sample_format)
        self._file = open(self.part_path, "w+b", buffering=1024 * 1024)
        self._fact_offset: int | None = None
        self._write_header()

    def _write_header(self) -> None:
        block_align = self.block_align
        byte_rate = self.sample_rate * block_align
        tag = 3 if self.sample_format.is_float else 1
        fmt = struct.pack(
            "<HHIIHH",
            tag,
            self.channels,
            self.sample_rate,
            byte_rate,
            block_align,
            self.sample_format.bits,
        )
        header = (
            b"RIFF"
            + struct.pack("<I", 0)
            + b"WAVE"
            + b"fmt "
            + struct.pack("<I", len(fmt))
            + fmt
        )
        if self.sample_format.is_float:
            header += b"fact" + struct.pack("<I", 4)
            self._fact_offset = len(header)
            header += struct.pack("<I", 0)
        self._data_size_offset = len(header) + 4
        header += b"data" + struct.pack("<I", 0)
        self._data_start = len(header)
        self._file.write(header)

    def _write(self, data: bytes) -> None:
        projected = self._data_start + self.bytes_written + len(data) + 262_144
        if projected > WAV_MAX_DATA_BYTES:
            raise SinkCapacityError(
                "WAV 文件接近 4 GB 上限。请启用自动分割，或改用 FLAC/ALAC。"
            )
        self._file.write(data)

    def finalize(self, metadata: Mapping[str, str] | None = None) -> Path:
        if self._closed:
            return self.final_path
        try:
            self._file.flush()
            data_size = self._file.tell() - self._data_start
            if self._fact_offset is not None:
                self._file.seek(self._fact_offset)
                self._file.write(struct.pack("<I", self.frames_written))
            self._file.seek(self._data_size_offset)
            self._file.write(struct.pack("<I", data_size))
            self._file.seek(0, os.SEEK_END)

            info = self._build_info_chunk(metadata)
            if info:
                self._file.write(info)
            file_size = self._file.tell()
            if file_size - 8 > 0xFFFFFFFF:
                raise SinkCapacityError("WAV 文件超过 4 GB，无法写入 RIFF 头")
            self._file.seek(4)
            self._file.write(struct.pack("<I", file_size - 8))
            self._file.flush()
            try:
                os.fsync(self._file.fileno())
            except OSError:
                pass
        finally:
            self._file.close()
            self._closed = True
        os.replace(self.part_path, self.final_path)
        log.info(
            "WAV 已写入：%s（%.2f 秒，%d 帧）",
            self.final_path,
            self.duration,
            self.frames_written,
        )
        return self.final_path

    def _build_info_chunk(self, metadata: Mapping[str, str] | None) -> bytes:
        if not metadata:
            return b""
        body = bytearray(b"INFO")
        written: set[bytes] = set()
        for key, value in metadata.items():
            chunk_id = self._INFO_KEYS.get(key)
            # 同一 chunk_id 只写一次（software/encoder 都映射到 ISFT）
            if not chunk_id or not value or chunk_id in written:
                continue
            written.add(chunk_id)
            payload = self._encode_info_value(str(value))
            body += chunk_id + struct.pack("<I", len(payload)) + payload
            if len(payload) % 2:
                body += b"\x00"
        if len(body) == 4:
            return b""
        if len(body) % 2:
            body += b"\x00"
        return b"LIST" + struct.pack("<I", len(body)) + bytes(body)

    @staticmethod
    def _encode_info_value(text: str) -> bytes:
        """按 Windows 资源管理器的解析规则编码 LIST INFO 字符串。

        Explorer 用系统 ANSI 代码页（简体中文为 GBK/cp936）解码 INFO 文本，
        且要求 NUL 结尾；实测：UTF-8 会显示为乱码，缺 NUL 会截掉最后一个字符。
        无法用 ANSI 编码的字符降级为 UTF-8（至少其他工具可读）。
        """
        ansi = locale.getpreferredencoding(False) or "utf-8"
        try:
            raw = text.encode(ansi)
        except (UnicodeEncodeError, LookupError):
            raw = text.encode("utf-8", errors="replace")
        return raw + b"\x00"

    def abort(self) -> None:
        try:
            if not self._closed:
                self._file.close()
        finally:
            self._closed = True
            try:
                self.part_path.unlink(missing_ok=True)
            except OSError:
                pass


class FlacSink(BaseSink):
    """libsndfile 流式 FLAC。"""

    def __init__(
        self,
        final_path: Path,
        sample_rate: int,
        channels: int,
        sample_format: SampleFormat,
        subtype: str,
    ) -> None:
        super().__init__(final_path, sample_rate, channels, sample_format)
        self._subtype = subtype
        try:
            # 默认压缩等级兼顾速度与体积，且不改变采样数据
            self._file = sf.SoundFile(
                str(self.part_path),
                mode="w",
                samplerate=self.sample_rate,
                channels=self.channels,
                format="FLAC",
                subtype=subtype,
            )
        except Exception as exc:
            raise SinkError(f"无法创建 FLAC 文件：{exc}") from exc

    def _write(self, data: bytes) -> None:
        frames = decode_to_float(data, self.sample_format, self.channels)
        try:
            self._file.write(frames)
        except Exception as exc:
            raise SinkError(f"FLAC 写入失败：{exc}") from exc

    def finalize(self, metadata: Mapping[str, str] | None = None) -> Path:
        if self._closed:
            return self.final_path
        try:
            self._file.close()
        finally:
            self._closed = True
        if not self.part_path.exists() or self.part_path.stat().st_size == 0:
            raise SinkError("FLAC 输出为空")
        os.replace(self.part_path, self.final_path)
        if metadata:
            from orbit.audio.metadata import write_flac_tags

            write_flac_tags(self.final_path, metadata)
        log.info(
            "FLAC 已写入：%s（%.2f 秒，%d 帧）",
            self.final_path,
            self.duration,
            self.frames_written,
        )
        return self.final_path

    def abort(self) -> None:
        try:
            if not self._closed:
                self._file.close()
        finally:
            self._closed = True
            try:
                self.part_path.unlink(missing_ok=True)
            except OSError:
                pass


def create_direct_sink(
    output_format: str,
    final_path: Path,
    sample_rate: int,
    channels: int,
    sample_format: SampleFormat,
) -> BaseSink:
    if output_format == "wav":
        return WavSink(final_path, sample_rate, channels, sample_format)
    if output_format == "flac":
        subtype = "PCM_16" if sample_format.bits <= 16 else "PCM_24"
        return FlacSink(final_path, sample_rate, channels, sample_format, subtype)
    raise SinkError(f"{output_format} 需要转码，不能直接写入")


def create_temp_wav(
    path: Path, sample_rate: int, channels: int, sample_format: SampleFormat
) -> WavSink:
    return WavSink(path, sample_rate, channels, sample_format)


def estimate_wav_size(seconds: float, sample_rate: int, channels: int, bits: int) -> int:
    return int(seconds * sample_rate * channels * bits / 8) + 44
