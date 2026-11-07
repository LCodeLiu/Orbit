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

"""设置与诊断对话框。"""

from __future__ import annotations

import ctypes
import logging
import os
import platform
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import PySide6
import soundfile as sf
from PySide6.QtCore import QTime, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTextEdit,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from orbit import __version__
from orbit.audio.devices import enumerate_devices
from orbit.audio.ffmpeg import inspect_ffmpeg
from orbit.config import AppConfig, ConfigStore
from orbit.ui.theme import Colors, icon, _apply_dark_titlebar as _apply_dark_titlebar

from orbit.util.paths import (
    config_path,
    default_output_dir,
    log_dir,
    open_path,
)

log = logging.getLogger(__name__)


def _section(title: str, subtitle: str = "") -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("SettingsBox")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 14, 16, 14)
    layout.setSpacing(8)
    title_label = QLabel(title)
    title_label.setStyleSheet("font-size: 13px; font-weight: 600; color: #E9EDF7;")
    layout.addWidget(title_label)
    if subtitle:
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("Tiny")
        subtitle_label.setWordWrap(True)
        layout.addWidget(subtitle_label)
    return frame, layout


class SettingsDialog(QDialog):
    """设置对话框：任何控件变更立即写入配置并生效。"""

    changed = Signal()

    def __init__(
        self,
        cfg: AppConfig,
        tray_available: bool = True,
        parent: QWidget | None = None,
        store: ConfigStore | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("设置 · Orbit")
        self.setWindowIcon(icon("settings"))
        self.setModal(True)
        self.resize(720, 640)
        self.setMinimumSize(660, 560)
        self.cfg = cfg
        self.result_config = cfg
        self._tray_available = tray_available
        self._store = store
        self._loading = True

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 16)
        root.setSpacing(14)

        header = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(icon("settings").pixmap(26, 26))
        header.addWidget(logo)
        titles = QVBoxLayout()
        titles.setSpacing(1)
        title = QLabel("设置")
        title.setStyleSheet("font-size: 20px; font-weight: 650; color: #F4F6FC;")
        subtitle = QLabel("更改会自动保存并立即生效；录音进行中时部分选项不可用。")
        subtitle.setObjectName("Muted")
        titles.addWidget(title)
        titles.addWidget(subtitle)
        header.addLayout(titles)
        header.addStretch(1)
        root.addLayout(header)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("SettingsTabs")
        self.tabs.addTab(self._build_recording_tab(), "录音与文件")
        self.tabs.addTab(self._build_schedule_tab(), "定时任务")
        self.tabs.addTab(self._build_system_tab(), "系统集成")
        self.tabs.addTab(self._build_debug_tab(), "调试")
        root.addWidget(self.tabs, 1)

        footer = QHBoxLayout()
        self.path_hint = QLabel("")
        self.path_hint.setObjectName("Tiny")
        footer.addWidget(self.path_hint, 1)
        cancel = QPushButton("关闭")
        cancel.setObjectName("Ghost")
        cancel.clicked.connect(self.reject)
        save = QPushButton("保存设置")
        save.setObjectName("Primary")
        save.clicked.connect(self._save)
        footer.addWidget(cancel)
        footer.addWidget(save)

        self._connect_autosave()
        self._loading = False

    def showEvent(self, event) -> None:  # noqa: ANN001
        super().showEvent(event)
        QTimer.singleShot(30, lambda: _apply_dark_titlebar(self))

    # ------------------------------------------------------------------ 标签页
    def _build_recording_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(2, 14, 2, 2)
        layout.setSpacing(12)

        box, box_layout = _section(
            "缓冲与自动控制",
            "较小的缓冲降低延迟，但更容易受系统负载影响。默认 20 ms 可兼顾稳定性。",
        )
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)

        row = 0
        grid.addWidget(QLabel("音频缓冲"), row, 0)
        self.buffer_spin = QSpinBox()
        self.buffer_spin.setRange(5, 200)
        self.buffer_spin.setSuffix(" ms")
        self.buffer_spin.setValue(self.cfg.buffer_ms)
        self.buffer_spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.buffer_spin.setToolTip("WASAPI 回调每次处理的音频时长")
        grid.addWidget(self.buffer_spin, row, 1)
        row += 1

        grid.addWidget(QLabel("最长录制"), row, 0)
        self.max_spin = QSpinBox()
        self.max_spin.setRange(0, 24 * 60)
        self.max_spin.setSuffix(" 分钟")
        self.max_spin.setSpecialValueText("不限")
        self.max_spin.setValue(self.cfg.max_minutes)
        self.max_spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        grid.addWidget(self.max_spin, row, 1)
        row += 1

        grid.addWidget(QLabel("按时长分割"), row, 0)
        self.split_min_spin = QSpinBox()
        self.split_min_spin.setRange(0, 24 * 60)
        self.split_min_spin.setSuffix(" 分钟")
        self.split_min_spin.setSpecialValueText("关闭")
        self.split_min_spin.setValue(self.cfg.split_minutes)
        self.split_min_spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        grid.addWidget(self.split_min_spin, row, 1)
        row += 1

        grid.addWidget(QLabel("按大小分割"), row, 0)
        self.split_mb_spin = QSpinBox()
        self.split_mb_spin.setRange(0, 64 * 1024)
        self.split_mb_spin.setSuffix(" MB")
        self.split_mb_spin.setSpecialValueText("关闭")
        self.split_mb_spin.setValue(self.cfg.split_size_mb)
        self.split_mb_spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        grid.addWidget(self.split_mb_spin, row, 1)
        box_layout.addLayout(grid)
        note = QLabel(
            "两个分割阈值同时存在时，先达到任一条件即切换新文件。"
            "分割不中断采集，每个分段独立写入与编码。"
        )
        note.setObjectName("Tiny")
        note.setWordWrap(True)
        box_layout.addWidget(note)
        layout.addWidget(box)

        box2, box2_layout = _section(
            "WAV 容量提醒",
            "标准 WAV 使用 32 位长度字段，单文件上限约 4 GB。"
            "录制超长内容时建议启用按时长分割（例如 60 分钟），或使用 FLAC。",
        )
        wav_note = QLabel(
            "32-bit / 48 kHz / 立体声约 1.38 GB/小时；24-bit 约 1.04 GB/小时。"
        )
        wav_note.setObjectName("Muted")
        wav_note.setWordWrap(True)
        box2_layout.addWidget(wav_note)
        layout.addWidget(box2)
        layout.addStretch(1)
        return page

    def _build_schedule_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(2, 14, 2, 2)
        layout.setSpacing(12)
        box, box_layout = _section(
            "每日定时录制",
            "应用需保持运行，可最小化到系统托盘。到点后自动开始录音；"
            "如果此时已在录音，则跳过当天。",
        )
        self.schedule_check = QCheckBox("启用每日定时录制")
        self.schedule_check.setChecked(self.cfg.schedule_enabled)
        box_layout.addWidget(self.schedule_check)

        time_row = QHBoxLayout()
        time_row.setSpacing(10)
        time_row.addWidget(QLabel("开始时间"))
        self.schedule_time = QTimeEdit()
        self.schedule_time.setDisplayFormat("HH:mm")
        hour, minute = (int(x) for x in self.cfg.schedule_time.split(":"))
        self.schedule_time.setTime(QTime(hour, minute))
        self.schedule_time.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.schedule_time.setFixedWidth(110)
        time_row.addWidget(self.schedule_time)
        time_row.addStretch(1)
        box_layout.addLayout(time_row)
        box_layout.addWidget(
            QLabel("最长录制时间与自动分割在“录音与文件”页配置。")
        )
        layout.addWidget(box)
        layout.addStretch(1)
        return page

    def _build_system_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(2, 14, 2, 2)
        layout.setSpacing(12)

        box, box_layout = _section("窗口与托盘")
        self.tray_check = QCheckBox("关闭窗口时最小化到系统托盘，继续在后台运行")
        self.tray_check.setChecked(self.cfg.close_to_tray)
        self.tray_check.setEnabled(self._tray_available)
        box_layout.addWidget(self.tray_check)
        self.notify_check = QCheckBox("录音完成或出错时显示系统通知")
        self.notify_check.setChecked(self.cfg.notify_on_complete)
        box_layout.addWidget(self.notify_check)
        self.hotkey_check = QCheckBox(
            "启用全局快捷键：Ctrl+Alt+F9 开始/停止，"
            "Ctrl+Alt+F10 暂停/继续，Ctrl+Alt+F11 打开录音目录"
        )
        self.hotkey_check.setChecked(self.cfg.hotkeys_enabled)
        box_layout.addWidget(self.hotkey_check)
        if not self._tray_available:
            tip = QLabel("当前系统未提供托盘区域，相关选项不可用。")
            tip.setObjectName("Warning")
            box_layout.addWidget(tip)
        layout.addWidget(box)

        box2, box2_layout = _section(
            "FFmpeg（ALAC / MP3 / AAC / OGG 需要）",
            "应用内置 WAV 与 FLAC 写入。其他格式使用外部 FFmpeg；"
            "转换时会锁定原采样率与声道数，不会自动重采样。",
        )
        path_row = QHBoxLayout()
        self.ffmpeg_edit = QLineEdit(self.cfg.ffmpeg_path)
        self.ffmpeg_edit.setObjectName("PathEdit")
        self.ffmpeg_edit.setPlaceholderText("留空自动在 PATH 中查找")
        browse = QPushButton("浏览")
        browse.setObjectName("Ghost")
        browse.clicked.connect(self._browse_ffmpeg)
        test = QPushButton("检测")
        test.setObjectName("Ghost")
        test.clicked.connect(self._test_ffmpeg)
        path_row.addWidget(self.ffmpeg_edit, 1)
        path_row.addWidget(browse)
        path_row.addWidget(test)
        box2_layout.addLayout(path_row)
        self.ffmpeg_status = QLabel("")
        self.ffmpeg_status.setObjectName("Tiny")
        self.ffmpeg_status.setWordWrap(True)
        box2_layout.addWidget(self.ffmpeg_status)
        self._test_ffmpeg(initial=True)
        layout.addWidget(box2)
        layout.addStretch(1)
        return page

    def _build_debug_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(2, 14, 2, 2)
        layout.setSpacing(12)

        box, box_layout = _section(
            "日志与诊断",
            "日志写入滚动文件，面板可显示 DEBUG 级细节（设备格式、缓冲、队列、丢帧等）。",
        )
        level_row = QHBoxLayout()
        level_row.addWidget(QLabel("日志级别"))
        self.level_combo = QComboBox()
        for text, value in (
            ("信息（推荐）", "INFO"),
            ("详细调试", "DEBUG"),
            ("仅警告", "WARNING"),
            ("仅错误", "ERROR"),
        ):
            self.level_combo.addItem(text, value)
        idx = self.level_combo.findData(self.cfg.log_level)
        self.level_combo.setCurrentIndex(max(0, idx))
        level_row.addWidget(self.level_combo, 1)
        box_layout.addLayout(level_row)

        path_label = QLabel(f"日志目录：{log_dir()}")
        path_label.setObjectName("Mono")
        path_label.setWordWrap(True)
        box_layout.addWidget(path_label)

        button_row = QHBoxLayout()
        open_logs = QPushButton("打开日志目录")
        open_logs.setObjectName("Ghost")
        open_logs.clicked.connect(lambda: self._open(log_dir()))
        diagnose = QPushButton("运行环境诊断")
        diagnose.setObjectName("Ghost")
        diagnose.clicked.connect(self._show_diagnostics)
        button_row.addWidget(open_logs)
        button_row.addWidget(diagnose)
        button_row.addStretch(1)
        box_layout.addLayout(button_row)
        layout.addWidget(box)

        about, about_layout = _section("关于")
        text = QLabel(
            f"Orbit {__version__} · Windows WASAPI Loopback\n"
            f"配置：{config_path()}\n"
            f"默认输出：{default_output_dir()}"
        )
        text.setObjectName("Muted")
        text.setWordWrap(True)
        about_layout.addWidget(text)
        layout.addWidget(about)
        layout.addStretch(1)
        return page

    # ------------------------------------------------------------------ 动作
    def _browse_ffmpeg(self) -> None:
        start = self.ffmpeg_edit.text().strip() or str(Path.home())
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 ffmpeg.exe", start, "FFmpeg (ffmpeg.exe);;所有文件 (*.*)"
        )
        if path:
            self.ffmpeg_edit.setText(path)
            self._test_ffmpeg()

    def _test_ffmpeg(self, initial: bool = False) -> None:
        info = inspect_ffmpeg(self.ffmpeg_edit.text().strip(), refresh=not initial)
        if info.available:
            self.ffmpeg_status.setText(
                f"✓ FFmpeg 可用：{info.version}\n{info.path}"
            )
            self.ffmpeg_status.setStyleSheet(f"color: {Colors.GREEN}; font-size: 11px;")
        else:
            self.ffmpeg_status.setText(f"✗ {info.error}")
            self.ffmpeg_status.setStyleSheet(f"color: {Colors.AMBER}; font-size: 11px;")

    def _open(self, path: Path) -> None:
        try:
            path.mkdir(parents=True, exist_ok=True)
            open_path(path)
        except Exception as exc:
            log.warning("无法打开路径 %s：%s", path, exc)

    def _show_diagnostics(self) -> None:
        dialog = DiagnosticsDialog(self)
        dialog.exec()

    def _connect_autosave(self) -> None:
        """把所有控件的信号接到自动保存。"""
        pairs = [
            (self.buffer_spin, self.buffer_spin.valueChanged),
            (self.max_spin, self.max_spin.valueChanged),
            (self.split_min_spin, self.split_min_spin.valueChanged),
            (self.split_mb_spin, self.split_mb_spin.valueChanged),
            (self.schedule_check, self.schedule_check.toggled),
            (self.schedule_time, self.schedule_time.timeChanged),
            (self.tray_check, self.tray_check.toggled),
            (self.notify_check, self.notify_check.toggled),
            (self.hotkey_check, self.hotkey_check.toggled),
            (self.ffmpeg_edit, self.ffmpeg_edit.textChanged),
            (self.level_combo, self.level_combo.currentIndexChanged),
        ]
        for _widget, signal in pairs:
            signal.connect(self._on_widget_changed)

    def _collect(self) -> None:
        cfg = self.cfg
        cfg.buffer_ms = self.buffer_spin.value()
        cfg.max_minutes = self.max_spin.value()
        cfg.split_minutes = self.split_min_spin.value()
        cfg.split_size_mb = self.split_mb_spin.value()
        cfg.schedule_enabled = self.schedule_check.isChecked()
        cfg.schedule_time = self.schedule_time.time().toString("HH:mm")
        cfg.close_to_tray = self.tray_check.isChecked() if self._tray_available else False
        cfg.notify_on_complete = self.notify_check.isChecked()
        cfg.hotkeys_enabled = self.hotkey_check.isChecked()
        cfg.ffmpeg_path = self.ffmpeg_edit.text().strip()
        cfg.log_level = self.level_combo.currentData() or "INFO"
        cfg.normalize()
        self.result_config = cfg

    def _on_widget_changed(self, *_args) -> None:
        if self._loading:
            return
        self._collect()
        if self._store is not None:
            try:
                self._store.save(self.cfg)
            except Exception as exc:
                log.exception("设置自动保存失败：%s", exc)
        self.changed.emit()

    def _save(self) -> None:
        self._collect()
        if self._store is not None:
            try:
                self._store.save(self.cfg)
            except Exception as exc:
                log.exception("设置保存失败：%s", exc)
        self.changed.emit()
        self.accept()

class DiagnosticsDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("运行环境诊断")
        self.setWindowIcon(icon("terminal"))
        self.resize(780, 620)
        self.setMinimumSize(660, 480)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)
        title = QLabel("运行环境诊断")
        title.setStyleSheet("font-size: 18px; font-weight: 650;")
        layout.addWidget(title)
        subtitle = QLabel("排查采集/编码问题时，请把以下信息完整提供给开发者。")
        subtitle.setObjectName("Muted")
        layout.addWidget(subtitle)

        self.text = QTextEdit()
        self.text.setObjectName("Diagnostics")
        self.text.setReadOnly(True)
        self.text.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(self.text, 1)

        buttons = QHBoxLayout()
        copy_btn = QPushButton("复制全部")
        copy_btn.setObjectName("Primary")
        copy_btn.clicked.connect(self._copy)
        open_logs = QPushButton("打开日志目录")
        open_logs.setObjectName("Ghost")
        open_logs.clicked.connect(lambda: self._open(log_dir()))
        close = QPushButton("关闭")
        close.setObjectName("Ghost")
        close.clicked.connect(self.accept)
        buttons.addWidget(open_logs)
        buttons.addStretch(1)
        buttons.addWidget(copy_btn)
        buttons.addWidget(close)
        layout.addLayout(buttons)

        self.text.setPlainText(self._collect())

    def showEvent(self, event) -> None:  # noqa: ANN001
        super().showEvent(event)
        QTimer.singleShot(30, lambda: _apply_dark_titlebar(self))

    def _collect(self) -> str:
        lines: list[str] = []
        lines.append(f"Orbit {__version__}")
        lines.append(f"时间: {datetime.now().isoformat(timespec='seconds')}")
        lines.append(f"Python: {sys.version.splitlines()[0]}")
        lines.append(f"Executable: {sys.executable}")
        lines.append(f"Platform: {platform.platform()}")
        lines.append(f"PySide6: {PySide6.__version__}")
        try:
            from PySide6.QtCore import qVersion

            lines.append(f"Qt: {qVersion()}")
        except Exception:
            pass
        try:
            import pyaudiowpatch as pyaudio

            lines.append(f"PyAudioWPatch: {getattr(pyaudio, '__version__', '?')}")
            try:
                lines.append(f"PortAudio: {pyaudio.get_portaudio_version_text()}")
            except Exception:
                pass
        except Exception as exc:
            lines.append(f"PyAudioWPatch: 不可用 ({exc})")
        lines.append(f"NumPy: {np.__version__}")
        lines.append(f"soundfile: {sf.__version__} / libsndfile {sf.__libsndfile_version__}")

        info = inspect_ffmpeg()
        lines.append("")
        lines.append("[FFmpeg]")
        lines.append(f"Available: {info.available}")
        lines.append(f"Path: {info.path or '-'}")
        lines.append(f"Version: {info.version or '-'}")
        lines.append(f"Probe: {info.ffprobe or '-'}")
        lines.append(
            "Encoders: "
            + ", ".join(
                name
                for name in ("alac", "aac", "libmp3lame", "libvorbis")
                if info.has_encoder(name)
            )
        )
        if info.error:
            lines.append(f"Error: {info.error}")

        lines.append("")
        lines.append("[WASAPI Loopback Devices]")
        inventory = enumerate_devices()
        if inventory.error:
            lines.append(f"ERROR: {inventory.error}")
        else:
            lines.append(f"PortAudio: {inventory.portaudio_version}")
            for d in inventory.devices:
                lines.append(
                    f"[{d.index}] {d.name} | {d.sample_rate} Hz | {d.channels} ch"
                    f" | {'DEFAULT' if d.is_default else 'available'}"
                )

        lines.append("")
        lines.append("[Paths]")
        lines.append(f"Config: {config_path()}")
        lines.append(f"Logs: {log_dir()}")
        lines.append(f"Default output: {default_output_dir()}")
        lines.append(f"APPDATA: {os.environ.get('APPDATA', '')}")
        lines.append(f"LOCALAPPDATA: {os.environ.get('LOCALAPPDATA', '')}")
        log_file = log_dir() / "app.log"
        if log_file.exists():
            lines.append(f"Log size: {log_file.stat().st_size} bytes")
        return "\n".join(lines)

    def _copy(self) -> None:
        QApplication.clipboard().setText(self.text.toPlainText())

    def _open(self, path: Path) -> None:
        try:
            path.mkdir(parents=True, exist_ok=True)
            open_path(path)
        except Exception:
            pass
