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

"""Orbit 主窗口。"""

from __future__ import annotations

import logging
import tempfile
from datetime import datetime
from pathlib import Path

import numpy as np
from PySide6.QtCore import (
    QByteArray,
    QDateTime,
    QFileSystemWatcher,
    QSize,
    Qt,
    QTime,
    QTimer,
)
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QSystemTrayIcon,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from orbit import __version__
from orbit.audio.analysis import (
    amplitude_to_db,
    spectrum_bands,
)
from orbit.audio.devices import DeviceScanner
from orbit.audio.monitor import LiveMonitor
from orbit.audio.ffmpeg import inspect_ffmpeg
from orbit.audio.formats import (
    BITRATE_OPTIONS,
    SAMPLE_RATE_OPTIONS,
    describe_channels,
    format_choices,
    get_output_format,
    validate_rate_for_format,
)
from orbit.audio.recorder import Recorder
from orbit.config import AppConfig, ConfigStore
from orbit.constants import SUPPORTED_AUDIO_EXTENSIONS, WINDOW_TITLE
from orbit.logging_setup import get_log_bridge, set_log_level
from orbit.models import (
    AudioDevice,
    DeviceInventory,
    RecordingFileInfo,
    RecordingRequest,
    RecordingResult,
)
from orbit.ui.settings import SettingsDialog

from orbit.ui.theme import Colors, app_icon, icon

def _dark_titlebar(window) -> None:  # noqa: ANN001
    try:
        from orbit.app import _apply_dark_titlebar as _fn

        _fn(window)
    except Exception:
        pass
from orbit.ui.widgets import (
    FileRow,
    InlineAlert,
    LevelMeter,
    LogConsole,
    LogoWidget,
    PlayerBar,
    RecordButton,
    SectionHeader,
    SpectrumView,
    StatChip,
    StatusPill,
    WaveformView,
    hline,
)
from orbit.util.hotkeys import GlobalHotkeys
from orbit.util.naming import build_tokens, preview_filename, render_template, sanitize_filename
from orbit.util.paths import (
    format_duration,
    human_size,
    open_path,
    reveal_path,
    shorten_path,
)
from orbit.util.shell import recycle_path

log = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self, cfg: AppConfig, store: ConfigStore | None = None) -> None:
        super().__init__()
        self.cfg = cfg
        self.store = store or ConfigStore()
        self._state = "idle"
        self._loading = True
        self._inventory = DeviceInventory()
        self._current_device: AudioDevice | None = None
        self._scan_silent = False
        self._file_infos: list[RecordingFileInfo] = []
        self._file_rows: list[FileRow] = []
        self._playing_path = ""
        self._last_samples: np.ndarray | None = None
        self._last_stats: dict = {}
        self._lossy_notice_shown = False
        self._native_notice_shown = False
        self._quit_after_finish = False
        self._force_quit = False
        self._global_hotkeys: GlobalHotkeys | None = None
        self._schedule_target: QDateTime | None = None
        self._stream_info: dict = {}

        self.setWindowTitle(WINDOW_TITLE)
        self.setWindowIcon(app_icon())
        self.setMinimumSize(1100, 640)
        self.setObjectName("MainWindow")

        self._scanner = DeviceScanner(self)
        self._monitor = LiveMonitor(self)
        self._monitor_device: int | None = None
        self._recorder = Recorder(self)
        self._build_ui()
        self._connect_signals()
        self._setup_timers()
        self._setup_shortcuts()
        self._setup_tray()
        self._setup_hotkeys()
        self._apply_config_to_ui()
        self._restore_geometry()
        self._refresh_files()
        self._set_watch_dir(Path(self.cfg.output_dir))
        self._loading = False
        self._update_output_hints()
        self._apply_state("idle", "准备就绪")
        log.info("界面初始化完成，输出目录=%s", self.cfg.output_dir)
        self._request_scan(force=True, silent=False)
        self._reschedule_daily()

    # ================================================================== 构建界面
    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(22, 16, 22, 10)
        outer.setSpacing(14)

        outer.addWidget(self._build_header())

        self.alert = InlineAlert()
        outer.addWidget(self.alert)

        outer.addWidget(self._build_transport())

        self.main_splitter = QSplitter(Qt.Orientation.Vertical)
        self.main_splitter.setChildrenCollapsible(False)
        self.main_splitter.setHandleWidth(8)
        self.main_splitter.addWidget(self._build_body())
        self.main_splitter.addWidget(self._build_log())
        self.main_splitter.setStretchFactor(0, 7)
        self.main_splitter.setStretchFactor(1, 2)
        self.main_splitter.setSizes([620, 170])
        outer.addWidget(self.main_splitter, 1)

        self._build_statusbar()

    def _build_header(self) -> QWidget:
        header = QWidget()
        layout = QHBoxLayout(header)
        layout.setContentsMargins(2, 0, 2, 0)
        layout.setSpacing(12)

        layout.addWidget(LogoWidget(42))

        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        title = QLabel("Orbit")
        title.setStyleSheet(
            "font-family: 'Segoe UI Variable Display', 'Segoe UI';"
            "font-size: 20px; font-weight: 650; color: #F6F8FD;"
        )
        subtitle = QLabel("通过 Windows WASAPI 采集原始音频")
        subtitle.setObjectName("Muted")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        layout.addLayout(title_box)
        layout.addSpacing(6)
        layout.addStretch(1)
        self.state_dot = QLabel("●")
        self.status_pill = StatusPill("就绪", Colors.GREEN)
        layout.addWidget(self.status_pill)

        self.folder_btn = self._header_button("folder", "打开录音目录")
        self.folder_btn.clicked.connect(self._open_output_folder)
        self.settings_btn = self._header_button("settings", "设置")
        self.settings_btn.clicked.connect(self._open_settings)
        self.log_toggle_btn = self._header_button("terminal", "显示 / 隐藏调试日志")
        self.log_toggle_btn.setCheckable(True)
        self.log_toggle_btn.setChecked(self.cfg.log_visible)
        self.log_toggle_btn.clicked.connect(self._toggle_log_visible)
        layout.addWidget(self.folder_btn)
        layout.addWidget(self.log_toggle_btn)
        layout.addWidget(self.settings_btn)
        return header

    @staticmethod
    def _header_button(icon_name: str, tooltip: str) -> QToolButton:
        button = QToolButton()
        button.setObjectName("IconButton")
        button.setIcon(icon(icon_name))
        button.setIconSize(QSize(18, 18))
        button.setFixedSize(34, 34)
        button.setToolTip(tooltip)
        return button

    def _build_transport(self) -> QWidget:
        card = QFrame()
        card.setObjectName("TransportCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(22, 16, 22, 12)
        layout.setSpacing(12)

        top = QHBoxLayout()
        top.setSpacing(26)

        time_box = QVBoxLayout()
        time_box.setSpacing(0)
        overline = QLabel("录音时长")
        overline.setObjectName("Overline")
        self.timer_label = QLabel("00:00:00.0")
        self.timer_label.setObjectName("Timer")
        self.timer_label.setMinimumWidth(255)
        state_row = QHBoxLayout()
        state_row.setSpacing(8)
        # self.state_dot = QLabel("●")
        self.state_dot.setStyleSheet(f"color: {Colors.GREEN}; font-size: 9px;")
        self.state_label = QLabel("准备就绪")
        self.state_label.setObjectName("StateText")
        self.format_summary = QLabel("WAV · 48 kHz · 32-bit 浮点 · 立体声")
        self.format_summary.setObjectName("Tiny")
        state_row.addWidget(self.state_dot)
        state_row.addWidget(self.state_label)
        state_row.addSpacing(2)
        state_row.addWidget(self.format_summary)
        state_row.addStretch(1)
        time_box.addWidget(overline)
        time_box.addWidget(self.timer_label)
        time_box.addLayout(state_row)
        top.addLayout(time_box, 4)

        meter_box = QVBoxLayout()
        meter_box.setSpacing(3)
        meter_head = QHBoxLayout()
        meter_title = QLabel("输出电平")
        meter_title.setObjectName("Overline")
        meter_hint = QLabel("峰值")
        meter_hint.setObjectName("Tiny")
        meter_head.addWidget(meter_title)
        meter_head.addStretch(1)
        meter_head.addWidget(meter_hint)
        meter_box.addLayout(meter_head)
        self.level_meter = LevelMeter()
        meter_box.addWidget(self.level_meter)
        top.addLayout(meter_box, 3)

        controls = QHBoxLayout()
        controls.setSpacing(10)
        self.record_btn = RecordButton()
        self.record_btn.setToolTip("开始录音（Ctrl+Alt+F9）")
        self.record_btn.clicked.connect(self._start_recording)
        self.pause_btn = self._transport_button("pause", "暂停")
        self.pause_btn.setToolTip("暂停录音（Ctrl+Alt+F10）")
        self.pause_btn.clicked.connect(self._toggle_pause)
        self.pause_btn.setEnabled(False)
        self.stop_btn = self._transport_button("stop", "停止")
        self.stop_btn.setToolTip("停止录音（Ctrl+Alt+F9）")
        self.stop_btn.clicked.connect(self._stop_recording)
        self.stop_btn.setEnabled(False)
        controls.addWidget(self.record_btn)
        controls.addWidget(self.pause_btn)
        controls.addWidget(self.stop_btn)
        top.addLayout(controls, 0)

        layout.addLayout(top)
        layout.addWidget(hline())

        metrics = QHBoxLayout()
        metrics.setSpacing(7)
        self.metric_size = StatChip("已写入", "0 B")
        self.metric_rate = StatChip("实际采样率", "—")
        self.metric_buffer = StatChip("缓冲", "—")
        self.metric_dropped = StatChip("丢帧", "0")
        self.metric_segment = StatChip("分段", "1")
        for chip, width in (
            (self.metric_size, 118),
            (self.metric_rate, 126),
            (self.metric_buffer, 158),
            (self.metric_dropped, 82),
            (self.metric_segment, 86),
        ):
            chip.setMinimumWidth(width)
            metrics.addWidget(chip)
        metrics.addStretch(1)
        self.encoding_label = QLabel("")
        self.encoding_label.setObjectName("Tiny")
        metrics.addWidget(self.encoding_label)
        layout.addLayout(metrics)
        return card

    @staticmethod
    def _transport_button(icon_name: str, text: str) -> QToolButton:
        button = QToolButton()
        button.setObjectName("TransportButton")
        button.setIcon(icon(icon_name))
        button.setIconSize(QSize(18, 18))
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        button.setText(text)
        button.setFixedSize(58, 62)
        button.setToolTip(text)
        return button

    def _build_body(self) -> QWidget:
        body = QWidget()
        layout = QHBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        left = QVBoxLayout()
        left.setSpacing(16)
        left.addWidget(self._build_visualizer(), 4)
        left.addWidget(self._build_files(), 5)
        layout.addLayout(left, 3)

        right_scroll = QScrollArea()
        right_scroll.setObjectName("RightScroll")
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QFrame.Shape.NoFrame)
        right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        right_scroll.setMinimumWidth(390)
        right_scroll.setMaximumWidth(470)
        right_host = QWidget()
        right_layout = QVBoxLayout(right_host)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(16)
        right_layout.addWidget(self._build_source_card())
        right_layout.addWidget(self._build_output_card())
        right_layout.addStretch(1)
        right_scroll.setWidget(right_host)
        layout.addWidget(right_scroll, 2)
        return body

    def _build_visualizer(self) -> QWidget:
        card = QFrame()
        card.setObjectName("Card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 14, 18, 12)
        layout.setSpacing(8)

        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(10)
        section = SectionHeader("实时监测")
        header_layout.addWidget(section, 1)

        self.peak_label = QLabel("峰值 -∞ dBFS")
        self.peak_label.setObjectName("Mono")
        self.rms_label = QLabel("RMS -∞ dBFS")
        self.rms_label.setObjectName("Mono")
        header_layout.addWidget(self.peak_label)
        header_layout.addWidget(self.rms_label)

        segmented = QFrame()
        segmented.setObjectName("Segmented")
        seg_layout = QHBoxLayout(segmented)
        seg_layout.setContentsMargins(2, 2, 2, 2)
        seg_layout.setSpacing(1)
        self.wave_tab = self._view_tab("波形", 0)
        self.spec_tab = self._view_tab("频谱", 1)
        seg_layout.addWidget(self.wave_tab)
        seg_layout.addWidget(self.spec_tab)
        header_layout.addWidget(segmented)
        layout.addWidget(header)

        self.view_stack = QStackedWidget()
        self.waveform = WaveformView()
        self.spectrum = SpectrumView()
        self.view_stack.addWidget(self.waveform)
        self.view_stack.addWidget(self.spectrum)
        layout.addWidget(self.view_stack, 1)
        self.wave_tab.setChecked(True)

        self.view_group = QButtonGroup(self)
        self.view_group.setExclusive(True)
        self.view_group.addButton(self.wave_tab, 0)
        self.view_group.addButton(self.spec_tab, 1)
        self.view_group.idClicked.connect(self._switch_view)
        return card

    def _view_tab(self, text: str, index: int) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("ViewTab")
        button.setCheckable(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setProperty("view_index", index)
        return button

    def _build_files(self) -> QWidget:
        card = QFrame()
        card.setObjectName("Card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(8)

        header = SectionHeader("录音文件")
        self.file_count = QLabel("0 个文件")
        self.file_count.setObjectName("Tiny")
        header.add_action(self.file_count)
        refresh = self._small_button("refresh", "刷新文件列表")
        refresh.clicked.connect(self._refresh_files)
        open_dir = self._small_button("folder", "打开录音目录")
        open_dir.clicked.connect(self._open_output_folder)
        header.add_action(refresh)
        header.add_action(open_dir)
        layout.addWidget(header)

        self.player = PlayerBar(volume=self.cfg.player_volume)
        self.player.error.connect(self._on_player_error)
        self.player.playing_changed.connect(self._on_playing_changed)
        self.player.open_external.connect(self._open_external)
        self.player.volume_changed.connect(self._on_player_volume_changed)
        layout.addWidget(self.player)

        self.file_scroll = QScrollArea()
        self.file_scroll.setWidgetResizable(True)
        self.file_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.file_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.file_host = QWidget()
        self.file_layout = QVBoxLayout(self.file_host)
        self.file_layout.setContentsMargins(0, 2, 0, 2)
        self.file_layout.setSpacing(2)
        self.file_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.file_scroll.setWidget(self.file_host)
        layout.addWidget(self.file_scroll, 1)
        return card

    @staticmethod
    def _small_button(icon_name: str, tooltip: str) -> QToolButton:
        button = QToolButton()
        button.setObjectName("IconButton")
        button.setIcon(icon(icon_name))
        button.setIconSize(QSize(14, 14))
        button.setFixedSize(28, 28)
        button.setToolTip(tooltip)
        return button

    def _build_source_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("Card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 12, 18, 12)
        layout.setSpacing(7)

        header = SectionHeader("音频源")
        self.refresh_btn = self._small_button("refresh", "刷新音频设备")
        self.refresh_btn.clicked.connect(lambda: self._request_scan(force=True, silent=False))
        header.add_action(self.refresh_btn)
        layout.addWidget(header)

        self.device_combo = QComboBox()
        self.device_combo.setMinimumContentsLength(24)
        self.device_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.device_combo.setPlaceholderText("正在扫描音频设备…")
        self.device_combo.currentIndexChanged.connect(self._on_device_changed)
        layout.addWidget(self.device_combo)
        self.native_label = QLabel("正在扫描 WASAPI 回环设备…")
        self.native_label.setObjectName("Tiny")
        self.native_label.setWordWrap(True)
        layout.addWidget(self.native_label)

        layout.addWidget(hline())

        rate_label = QLabel("采样率")
        rate_label.setObjectName("Overline")
        self.rate_combo = QComboBox()
        self.rate_combo.currentIndexChanged.connect(self._on_source_option_changed)
        layout.addWidget(rate_label)
        layout.addWidget(self.rate_combo)

        grid = QHBoxLayout()
        grid.setSpacing(10)
        depth_box = QVBoxLayout()
        depth_box.setSpacing(3)
        depth_label = QLabel("位深")
        depth_label.setObjectName("Overline")
        self.depth_combo = QComboBox()
        self.depth_combo.setMinimumContentsLength(9)
        self.depth_combo.currentIndexChanged.connect(self._on_source_option_changed)
        depth_box.addWidget(depth_label)
        depth_box.addWidget(self.depth_combo)
        grid.addLayout(depth_box, 1)

        channels_box = QVBoxLayout()
        channels_box.setSpacing(3)
        channels_label = QLabel("声道")
        channels_label.setObjectName("Overline")
        self.channels_combo = QComboBox()
        self.channels_combo.setMinimumContentsLength(9)
        self.channels_combo.currentIndexChanged.connect(self._on_source_option_changed)
        channels_box.addWidget(channels_label)
        channels_box.addWidget(self.channels_combo)
        grid.addLayout(channels_box, 1)
        layout.addLayout(grid)

        self.source_hint = QLabel("")
        self.source_hint.setObjectName("Tiny")
        self.source_hint.setWordWrap(True)
        layout.addWidget(self.source_hint)

        self.schedule_hint = QLabel("")
        self.schedule_hint.setObjectName("Tiny")
        self.schedule_hint.setWordWrap(True)
        layout.addWidget(self.schedule_hint)
        return card

    def _build_output_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("Card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 12, 18, 12)
        layout.setSpacing(6)

        header = SectionHeader("输出设置")
        self.open_dir_btn = self._small_button("folder", "打开录音目录")
        self.open_dir_btn.clicked.connect(self._open_output_folder)
        header.add_action(self.open_dir_btn)
        layout.addWidget(header)

        format_row = QHBoxLayout()
        format_row.setSpacing(8)
        self.format_combo = QComboBox()
        for fmt in format_choices():
            self.format_combo.addItem(f"{fmt.label}   ·   {fmt.kind_label}", fmt.key)
        self.format_combo.currentIndexChanged.connect(self._on_format_changed)
        format_row.addWidget(self.format_combo, 1)
        self.format_badge = QLabel("无损")
        self.format_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.format_badge.setFixedSize(46, 26)
        format_row.addWidget(self.format_badge)
        layout.addLayout(format_row)

        self.format_desc = QLabel("")
        self.format_desc.setObjectName("Tiny")
        self.format_desc.setWordWrap(True)
        layout.addWidget(self.format_desc)

        dir_label = QLabel("保存目录")
        dir_label.setObjectName("Overline")
        layout.addWidget(dir_label)
        dir_row = QHBoxLayout()
        dir_row.setSpacing(6)
        self.dir_edit = QLineEdit()
        self.dir_edit.setObjectName("PathEdit")
        self.dir_edit.setToolTip("录音文件保存目录")
        self.dir_edit.editingFinished.connect(self._on_output_dir_changed)
        browse = self._small_button("folder", "选择目录")
        browse.clicked.connect(self._browse_output_dir)
        dir_row.addWidget(self.dir_edit, 1)
        dir_row.addWidget(browse)
        layout.addLayout(dir_row)

        name_label = QLabel("文件名模板")
        name_label.setObjectName("Overline")
        layout.addWidget(name_label)
        self.name_edit = QLineEdit()
        self.name_edit.setToolTip(
            "可用变量：{date} {time} {datetime} {device} {device_short} "
            "{format} {sample_rate} {bit_depth} {channels} {part}"
        )
        self.name_edit.textChanged.connect(self._on_name_template_changed)
        layout.addWidget(self.name_edit)
        self.name_preview = QLabel("")
        self.name_preview.setObjectName("Tiny")
        self.name_preview.setWordWrap(True)
        layout.addWidget(self.name_preview)

        options = QHBoxLayout()
        options.setSpacing(10)
        self.metadata_check = QCheckBox("写入元数据")
        self.metadata_check.setToolTip("日期、设备、格式、软件版本等")
        self.metadata_check.toggled.connect(self._on_metadata_changed)
        options.addWidget(self.metadata_check)
        options.addStretch(1)
        self.bitrate_label = QLabel("码率")
        self.bitrate_label.setObjectName("Overline")
        self.bitrate_combo = QComboBox()
        for rate in BITRATE_OPTIONS:
            self.bitrate_combo.addItem(f"{rate} kbps", rate)
        self.bitrate_combo.currentIndexChanged.connect(self._on_bitrate_changed)
        options.addWidget(self.bitrate_label)
        options.addWidget(self.bitrate_combo)
        layout.addLayout(options)

        self.lossy_warning = QLabel("")
        self.lossy_warning.setObjectName("Warning")
        self.lossy_warning.setWordWrap(True)
        layout.addWidget(self.lossy_warning)
        self.ffmpeg_warning = QLabel("")
        self.ffmpeg_warning.setObjectName("Tiny")
        self.ffmpeg_warning.setWordWrap(True)
        layout.addWidget(self.ffmpeg_warning)
        self.split_hint = QLabel("")
        self.split_hint.setObjectName("Tiny")
        self.split_hint.setWordWrap(True)
        layout.addWidget(self.split_hint)
        return card

    def _build_log(self) -> QWidget:
        card = QFrame()
        card.setObjectName("Card")
        self.log_card = card
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 12, 18, 12)
        layout.setSpacing(7)
        header = SectionHeader("调试日志")
        self.detail_check = QCheckBox("详细")
        self.detail_check.setToolTip("DEBUG 日志")
        self.detail_check.toggled.connect(self._on_detail_toggled)
        header.add_action(self.detail_check)
        self.log_filter = QComboBox()
        for text, level in (("全部", 10), ("信息", 20), ("警告", 30), ("错误", 40)):
            self.log_filter.addItem(text, level)
        self.log_filter.setFixedWidth(92)
        self.log_filter.currentIndexChanged.connect(self._on_log_filter)
        clear_btn = QPushButton("清空")
        clear_btn.setObjectName("Ghost")
        clear_btn.setFixedHeight(27)
        clear_btn.clicked.connect(lambda: self.log_console.clear())
        log_path_btn = self._small_button("external", "打开日志文件")
        log_path_btn.clicked.connect(self._open_log_file)
        header.add_action(self.log_filter)
        header.add_action(clear_btn)
        header.add_action(log_path_btn)
        layout.addWidget(header)

        self.log_console = LogConsole()
        layout.addWidget(self.log_console, 1)
        self.log_console.set_min_level(20)
        return card

    def _build_statusbar(self) -> None:
        bar = self.statusBar()
        bar.setSizeGripEnabled(False)
        bar.setFixedHeight(25)
        self.footer_state = QLabel("正在初始化…")
        self.footer_meta = QLabel(f"Orbit {__version__}")
        self.footer_state.setObjectName("Tiny")
        self.footer_meta.setObjectName("Tiny")
        bar.addWidget(self.footer_state, 1)
        bar.addPermanentWidget(self.footer_meta)

    # ================================================================== 信号
    def _connect_signals(self) -> None:
        get_log_bridge().message.connect(self._on_log)
        self._scanner.finished.connect(self._on_devices_scanned)
        self._monitor.frame_ready.connect(self._on_monitor_frame)

        self._recorder.state_changed.connect(self._on_recorder_state)
        self._recorder.started.connect(self._on_recorder_started)
        self._recorder.paused_changed.connect(self._on_paused_changed)
        self._recorder.stats_updated.connect(self._on_stats)
        self._recorder.visual_updated.connect(self._on_visual)
        self._recorder.segment_started.connect(self._on_segment_started)
        self._recorder.file_ready.connect(self._on_file_ready)
        self._recorder.processing.connect(self._on_processing)
        self._recorder.error.connect(self._on_recorder_error)
        self._recorder.device_lost.connect(self._on_device_lost)
        self._recorder.finished.connect(self._on_finished)

    def _setup_timers(self) -> None:
        self._device_timer = QTimer(self)
        self._device_timer.setInterval(9000)
        self._device_timer.timeout.connect(self._auto_scan)
        self._device_timer.start()

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(350)
        self._save_timer.timeout.connect(self._save_config)

        self._file_refresh_timer = QTimer(self)
        self._file_refresh_timer.setSingleShot(True)
        self._file_refresh_timer.setInterval(600)
        self._file_refresh_timer.timeout.connect(self._refresh_files)

        self._schedule_timer = QTimer(self)
        self._schedule_timer.setSingleShot(True)
        self._schedule_timer.timeout.connect(self._on_schedule_fired)

        self._watcher = QFileSystemWatcher(self)
        self._watcher.directoryChanged.connect(self._on_directory_changed)

    def _setup_shortcuts(self) -> None:
        for key, slot in (
            ("F9", self._hotkey_record),
            ("F10", self._hotkey_pause),
            ("F11", self._open_output_folder),
            ("Ctrl+,", self._open_settings),
        ):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.activated.connect(slot)

    def _setup_hotkeys(self) -> None:
        if self._global_hotkeys:
            self._global_hotkeys.unregister()
            self._global_hotkeys.deleteLater()
            self._global_hotkeys = None
        if not self.cfg.hotkeys_enabled:
            return
        app = QApplication.instance()
        if app is None:
            return
        self._global_hotkeys = GlobalHotkeys(app, self)
        self._global_hotkeys.triggered.connect(self._on_global_hotkey)
        self._global_hotkeys.register()
        if self._global_hotkeys.errors:
            self._show_alert(
                "部分全局快捷键注册失败",
                "；".join(self._global_hotkeys.errors)
                + "。可能被其他软件占用，可在设置中关闭全局快捷键。",
            )

    # ================================================================== 配置装载
    def _apply_config_to_ui(self) -> None:
        self._loading = True
        try:
            idx = self.format_combo.findData(self.cfg.output_format)
            self.format_combo.setCurrentIndex(max(0, idx))
            self.dir_edit.setText(self.cfg.output_dir)
            self.name_edit.setText(self.cfg.name_template)
            self.metadata_check.setChecked(self.cfg.metadata_enabled)
            b_idx = self.bitrate_combo.findData(self.cfg.bitrate_kbps)
            if b_idx < 0:
                self.bitrate_combo.addItem(f"{self.cfg.bitrate_kbps} kbps", self.cfg.bitrate_kbps)
                b_idx = self.bitrate_combo.count() - 1
            self.bitrate_combo.setCurrentIndex(b_idx)
            debug_enabled = self.cfg.log_level == "DEBUG"
            self.log_filter.setCurrentIndex(0 if debug_enabled else 1)
            self.log_console.set_min_level(10 if debug_enabled else 20)
            self.detail_check.blockSignals(True)
            self.detail_check.setChecked(debug_enabled)
            self.detail_check.blockSignals(False)
            self.log_card.setVisible(self.cfg.log_visible)
            self.log_toggle_btn.setChecked(self.cfg.log_visible)
            self._populate_depth_options(self.cfg.bit_depth)
            self._on_format_changed()
            self._update_preview_name()
            self._update_split_hint()
        finally:
            self._loading = False
        if not self.cfg.log_visible:
            QTimer.singleShot(0, lambda: self.main_splitter.setSizes([1, 0]))

    def _restore_geometry(self) -> None:
        if self.cfg.window_geometry:
            try:
                data = QByteArray.fromBase64(self.cfg.window_geometry.encode("ascii"))
                if self.restoreGeometry(data):
                    return
            except Exception:
                pass
        screen = QApplication.primaryScreen()
        if screen:
            avail = screen.availableGeometry()
            width = min(1320, max(1100, avail.width() - 70))
            height = min(860, max(640, avail.height() - 60))
            self.resize(width, height)
            self.move(
                avail.x() + (avail.width() - width) // 2,
                avail.y() + max(0, (avail.height() - height) // 2 - 10),
            )
        else:
            self.resize(1280, 820)

    def _save_config(self) -> None:
        if self._loading:
            return
        try:
            self.store.save(self.cfg)
        except Exception as exc:
            log.exception("保存配置失败")
            self.footer_state.setText(f"配置保存失败：{exc}")

    def _persist_later(self) -> None:
        if not self._loading:
            self._save_timer.start()

    # ================================================================== 设备
    def _request_scan(self, force: bool = False, silent: bool = True) -> None:
        if self._recorder.active:
            return
        if self._scanner.busy:
            return
        self._scan_silent = silent
        if not silent:
            self.footer_state.setText("正在扫描 WASAPI 回环设备…")
            self.refresh_btn.setEnabled(False)
        self._scanner.scan()

    def _auto_scan(self) -> None:
        if self._state == "idle" and not self._recorder.active:
            self._request_scan(force=False, silent=True)

    def _on_devices_scanned(self, inventory: DeviceInventory) -> None:
        if self._recorder.active or self._state != "idle":
            # 录音期间不接受设备枚举结果，避免影响当前流与 UI 选择
            self._scan_silent = False
            return
        self._inventory = inventory
        self.refresh_btn.setEnabled(True)
        previous_name = self._current_device.name if self._current_device else self.cfg.device_name
        previous_index = self._current_device.index if self._current_device else self.cfg.device_index
        signature = tuple(
            (d.index, d.name, d.sample_rate, d.channels, d.is_default)
            for d in inventory.devices
        )
        old_signature = getattr(self, "_device_signature", None)
        first = old_signature is None
        changed = signature != old_signature
        self._device_signature = signature

        if inventory.error and not inventory.devices:
            log.warning("设备扫描失败：%s", inventory.error)
            self.device_combo.blockSignals(True)
            self.device_combo.clear()
            self.device_combo.blockSignals(False)
            self.device_combo.setEnabled(False)
            self._current_device = None
            self.native_label.setText("没有可用的 WASAPI 回环设备")
            self.native_label.setStyleSheet(f"color: {Colors.AMBER};")
            self.footer_state.setText("未找到音频设备")
            self._apply_state("idle", "无可用音频设备")
            if not self._scan_silent or first:
                self._show_alert(
                    "未找到可用的系统音频设备",
                    inventory.error
                    + "\n请确认已连接播放设备，并在 Windows 声音设置中允许应用访问音频。",
                )
            self._scan_silent = False
            return

        if not (first or changed):
            # 静默扫描没有变化时不重建下拉框，避免打断用户操作
            self._scan_silent = False
            return

        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        for device in inventory.devices:
            self.device_combo.addItem(device.display_name, device)
            self.device_combo.setItemData(
                self.device_combo.count() - 1,
                f"{device.sample_rate:,} Hz · {device.channels} 声道 · 回环",
                Qt.ItemDataRole.ToolTipRole,
            )
        target = -1
        for i, device in enumerate(inventory.devices):
            if device.name == previous_name:
                target = i
                break
        if target < 0:
            for i, device in enumerate(inventory.devices):
                if device.index == previous_index:
                    target = i
                    break
        if target < 0:
            for i, device in enumerate(inventory.devices):
                if device.is_default:
                    target = i
                    break
        if target < 0 and inventory.devices:
            target = 0
        self.device_combo.setCurrentIndex(target)
        self.device_combo.setEnabled(True)
        self.device_combo.blockSignals(False)
        self._current_device = self.device_combo.currentData()
        self._populate_source_options()
        self._update_source_hints()
        self._update_preview_name()
        self._update_config_from_source()
        self._apply_state(self._state)
        self.footer_state.setText(
            f"WASAPI 回环 · {len(inventory.devices)} 台设备 · "
            f"{inventory.portaudio_version or 'PortAudio'}"
        )
        if first:
            log.info(
                "发现 %d 台 WASAPI 回环设备，默认设备=%s",
                len(inventory.devices),
                self._current_device.clean_name if self._current_device else "无",
            )
        elif changed and not self._scan_silent:
            log.info("设备列表已更新（%d 台）", len(inventory.devices))
        self._scan_silent = False
        self._apply_state(self._state)

    def _sync_monitor(self) -> None:
        """空闲且窗口可见时开启实时监听；录音中/隐藏时关闭。

        由 _apply_state 统一调用：状态或所选设备变化统一经过。
        """
        device = self._current_device
        want = (
            self._state == "idle"
            and device is not None
            and self.isVisible()
            and not self._recorder.active
        )
        if not want:
            if self._monitor.running:
                self._monitor.stop()
                self._monitor_device = None
            return
        if self._monitor.running and self._monitor_device == device.index:
            return
        if self._monitor.running:
            self._monitor.restart(device.index, device.channels, device.sample_rate)
        else:
            self._monitor.start(device.index, device.channels, device.sample_rate)
        self._monitor_device = device.index

    def _on_monitor_frame(self, frame: dict) -> None:
        """空闲监听数据"""
        if self._state != "idle":
            return
        samples = frame.get("samples")
        peaks = frame.get("peaks") or []
        rms = frame.get("rms") or []
        if samples is None or not len(samples):
            return
        self._last_samples = samples
        self.waveform.set_samples(samples)
        self.level_meter.set_levels(peaks, rms)
        peak = max(peaks) if peaks else 0.0
        rms_value = max(rms) if rms else 0.0
        self.peak_label.setText(f"峰值 {amplitude_to_db(peak):.1f} dBFS")
        self.rms_label.setText(f"RMS {amplitude_to_db(rms_value):.1f} dBFS")
        if self.view_stack.currentIndex() == 1:
            rate = int(frame.get("sample_rate") or 48000)
            self.spectrum.set_bands(spectrum_bands(samples, rate))

    def _on_device_changed(self, index: int) -> None:
        device = self.device_combo.currentData()
        if not isinstance(device, AudioDevice):
            return
        self._current_device = device
        self._populate_source_options()
        self._update_source_hints()
        self._update_preview_name()
        self._update_config_from_source()
        self._apply_state(self._state)
        if not self._loading:
            log.info(
                "选择音频设备：[%d] %s | %d Hz | %d ch",
                device.index,
                device.clean_name,
                device.sample_rate,
                device.channels,
            )
            self._persist_later()

    def _populate_source_options(self) -> None:
        device = self._current_device
        if not device:
            return
        self._loading = True
        try:
            old_rate = self.rate_combo.currentData()
            old_channels = self.channels_combo.currentData()
            self.rate_combo.clear()
            self.rate_combo.addItem(f"原生 · {device.sample_rate:,} Hz", 0)
            for rate in SAMPLE_RATE_OPTIONS:
                if rate == device.sample_rate:
                    continue
                self.rate_combo.addItem(f"{rate / 1000:g} kHz", rate)
            preferred_rate = self.cfg.sample_rate if self.cfg.sample_rate is not None else old_rate
            idx = self.rate_combo.findData(preferred_rate)
            if idx < 0:
                idx = 0
            self.rate_combo.setCurrentIndex(idx)

            self.channels_combo.clear()
            self.channels_combo.addItem(
                f"原生 · {describe_channels(device.channels)}", 0
            )
            for channel in (1, 2, 4, 6, 8):
                if channel == device.channels or channel > device.channels:
                    continue
                self.channels_combo.addItem(describe_channels(channel), channel)
            preferred_ch = self.cfg.channels if self.cfg.channels is not None else old_channels
            idx = self.channels_combo.findData(preferred_ch)
            if idx < 0:
                idx = 0
            self.channels_combo.setCurrentIndex(idx)

            self.native_label.setText(
                f"设备原生：{device.sample_rate:,} Hz · {device.channels} 声道"
                f"{' · 默认设备' if device.is_default else ''} · WASAPI Loopback"
            )
            self.native_label.setStyleSheet(f"color: {Colors.MUTED}; font-size: 11px;")
        finally:
            self._loading = False

    def _effective_source(self) -> tuple[int, int, int]:
        device = self._current_device
        rate = self.rate_combo.currentData() if self.rate_combo.count() else 0
        channels = self.channels_combo.currentData() if self.channels_combo.count() else 0
        depth = self.depth_combo.currentData() if self.depth_combo.count() else self.cfg.bit_depth
        rate = int(rate or (device.sample_rate if device else 48000))
        channels = int(channels or (device.channels if device else 2))
        return rate, channels, int(depth or 32)

    def _update_config_from_source(self) -> None:
        device = self._current_device
        if not device:
            return
        rate, channels, depth = self._effective_source()
        self.cfg.device_name = device.name
        self.cfg.device_index = device.index
        self.cfg.sample_rate = 0 if rate == device.sample_rate else rate
        self.cfg.channels = 0 if channels == device.channels else channels
        self.cfg.bit_depth = depth
        self._update_format_summary()

    def _update_source_hints(self) -> None:
        device = self._current_device
        if not device:
            self.source_hint.setText("")
            return
        rate, channels, depth = self._effective_source()
        fmt = get_output_format(self.format_combo.currentData())
        messages: list[str] = []
        color = Colors.GREEN
        if rate != device.sample_rate:
            messages.append(
                f"非原生采样率 {rate:,} Hz：WASAPI 共享回环通常只接受设备混音率"
                f"（{device.sample_rate:,} Hz），启动时可能被拒绝；应用不会自动重采样。"
            )
            color = Colors.AMBER
        if channels != device.channels:
            messages.append(
                f"非原生声道数 {channels}：系统可能上混/下混。"
            )
            color = Colors.AMBER
        if not messages:
            messages.append("原生格式")
        if depth != 32 and fmt.key in ("wav", "flac"):
            messages.append(f"{depth}-bit 整数 PCM 写入会量化原始浮点混音。")
        self.source_hint.setText(" ".join(messages))
        self.source_hint.setStyleSheet(f"color: {color}; font-size: 11px;")
        self._update_format_summary()

    def _update_format_summary(self) -> None:
        if not self._current_device:
            return
        rate, channels, depth = self._effective_source()
        fmt = get_output_format(self.format_combo.currentData())
        self.format_summary.setText(
            f"{fmt.label} · {rate:,} Hz · {depth}-bit "
            f"{'浮点' if depth == 32 else 'PCM'} · {describe_channels(channels)}"
        )

    # ================================================================== 输出设置
    def _on_format_changed(self) -> None:
        if self._loading:
            return
        fmt = get_output_format(self.format_combo.currentData())
        self.cfg.output_format = fmt.key
        current_depth = self.depth_combo.currentData() if self.depth_combo.count() else self.cfg.bit_depth
        self._populate_depth_options(
            current_depth if current_depth in fmt.allowed_depths else fmt.default_depth
        )
        self._update_output_hints()
        self._update_preview_name()
        self._update_source_hints()
        self._persist_later()

    def _populate_depth_options(self, preferred: int) -> None:
        fmt = get_output_format(self.format_combo.currentData())
        self.depth_combo.blockSignals(True)
        self.depth_combo.clear()
        for depth in sorted(fmt.allowed_depths, reverse=True):
            label = "32-bit 浮点" if depth == 32 else f"{depth}-bit PCM"
            self.depth_combo.addItem(label, depth)
            self.depth_combo.setItemData(
                self.depth_combo.count() - 1,
                "与 WASAPI 混音格式一致，最接近原始数据" if depth == 32 else "整数 PCM，动态范围略低",
                Qt.ItemDataRole.ToolTipRole,
            )
        idx = self.depth_combo.findData(preferred)
        if idx < 0:
            idx = self.depth_combo.findData(fmt.default_depth)
        self.depth_combo.setCurrentIndex(max(0, idx))
        self.depth_combo.blockSignals(False)
        self.cfg.bit_depth = int(self.depth_combo.currentData() or fmt.default_depth)

    def _update_output_hints(self) -> None:
        fmt = get_output_format(self.format_combo.currentData())
        if fmt.lossless:
            self.format_badge.setText("无损")
            self.format_badge.setStyleSheet(
                "background: #12362D; color: #38BD3C; border: 1px solid #1F5949;"
                "border-radius: 6px; font-size: 10px; font-weight: 700;"
            )
        else:
            self.format_badge.setText("有损")
            self.format_badge.setStyleSheet(
                "background: #3B2A17; color: #FFC168; border: 1px solid #5E4321;"
                "border-radius: 6px; font-size: 10px; font-weight: 700;"
            )
        self.format_desc.setText(fmt.description)
        lossy = not fmt.lossless
        self.lossy_warning.setVisible(lossy)
        if lossy:
            self.lossy_warning.setText(
                "有损格式，会导致部分细节丢失"
                "需要最高保真请选择 WAV / FLAC / ALAC。"
            )
        self.bitrate_label.setVisible(lossy)
        self.bitrate_combo.setVisible(lossy)
        if fmt.requires_ffmpeg:
            info = inspect_ffmpeg(self.cfg.ffmpeg_path)
            if info.available and info.supports(fmt):
                self.ffmpeg_warning.setText(f"FFmpeg：{Path(info.path).name} · 已就绪")
                self.ffmpeg_warning.setStyleSheet(f"color: {Colors.MUTED_DIM}; font-size: 11px;")
            else:
                self.ffmpeg_warning.setText(
                    "需要 FFmpeg 才能输出此格式。请在 设置 → 系统集成 中指定 ffmpeg.exe。"
                )
                self.ffmpeg_warning.setStyleSheet(f"color: {Colors.RED}; font-size: 11px;")
        else:
            self.ffmpeg_warning.setText("")
        self.ffmpeg_warning.setVisible(self.ffmpeg_warning.text() != "")
        self._update_format_summary()

    def _update_split_hint(self) -> None:
        parts = []
        if self.cfg.split_minutes:
            parts.append(f"每 {self.cfg.split_minutes} 分钟")
        if self.cfg.split_size_mb:
            parts.append(f"每 {self.cfg.split_size_mb} MB")
        if self.cfg.max_minutes:
            parts.append(f"最长 {self.cfg.max_minutes} 分钟")
        self.split_hint.setText("自动分割：" + "，".join(parts) if parts else "")
        self.split_hint.setVisible(bool(parts))
        if self.cfg.schedule_enabled:
            self.schedule_hint.setText(
                f"每日定时录制：{self.cfg.schedule_time}（应用需保持运行）"
            )
            self.schedule_hint.setVisible(True)
        else:
            self.schedule_hint.setText("")
            self.schedule_hint.setVisible(False)

    def _on_source_option_changed(self) -> None:
        if self._loading:
            return
        self._update_source_hints()
        self._update_preview_name()
        self._update_config_from_source()
        self._persist_later()

    def _on_name_template_changed(self, text: str) -> None:
        if self._loading:
            return
        self.cfg.name_template = text
        self._update_preview_name()
        self._persist_later()

    def _on_metadata_changed(self, checked: bool) -> None:
        if self._loading:
            return
        self.cfg.metadata_enabled = checked
        self._persist_later()

    def _on_bitrate_changed(self) -> None:
        if self._loading:
            return
        self.cfg.bitrate_kbps = int(self.bitrate_combo.currentData() or 320)
        self._persist_later()

    def _update_preview_name(self) -> None:
        device = self._current_device
        rate, channels, depth = self._effective_source()
        fmt = get_output_format(self.format_combo.currentData())
        name = device.clean_name if device else "系统音频"
        try:
            preview = preview_filename(
                self.cfg.name_template or "{date}_{time}_{device}",
                name,
                fmt.key,
                rate,
                depth,
                channels,
                fmt.extension,
            )
        except Exception:
            preview = f"<模板错误>{fmt.extension}"
        self.name_preview.setText(f"示例：{preview}")
        self.name_preview.setStyleSheet(f"color: {Colors.MUTED_DIM}; font-size: 11px;")

    def _on_output_dir_changed(self) -> None:
        text = self.dir_edit.text().strip()
        if not text:
            return
        path = Path(text).expanduser()
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self._show_alert("保存目录不可用", f"{path}\n{exc}")
            return
        self.cfg.output_dir = str(path)
        self._set_watch_dir(path)
        self._refresh_files()
        self._persist_later()
        log.info("输出目录：%s", path)

    def _browse_output_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择录音保存目录", self.cfg.output_dir)
        if path:
            self.dir_edit.setText(path)
            self._on_output_dir_changed()

    def _open_output_folder(self) -> None:
        path = Path(self.cfg.output_dir)
        try:
            path.mkdir(parents=True, exist_ok=True)
            open_path(path)
        except Exception as exc:
            self._show_alert("无法打开录音目录", str(exc))

    def _open_settings(self) -> None:
        if self._recorder.active:
            self._show_alert("录音进行中", "请先停止录音，再修改高级设置。")
            return
        dialog = SettingsDialog(
            self.cfg,
            QSystemTrayIcon.isSystemTrayAvailable(),
            self,
            store=self.store,
        )
        dialog.changed.connect(self._on_settings_changed)
        dialog.exec()
        # 对话框关闭后同步一次界面（自动保存已生效，这里只刷新显示）
        self._on_settings_changed()

    def _on_settings_changed(self) -> None:
        """设置对话框中任何变更实时生效。"""
        # 对话框关闭时不再重复应用
        set_log_level(self.cfg.log_level)
        self.detail_check.blockSignals(True)
        self.detail_check.setChecked(self.cfg.log_level == "DEBUG")
        self.detail_check.blockSignals(False)
        if self.cfg.log_level == "DEBUG":
            self.log_filter.setCurrentIndex(0)
            self.log_console.set_min_level(10)
        self._setup_hotkeys()
        self._update_split_hint()
        self._update_output_hints()
        self._update_source_hints()
        self._reschedule_daily()
        if self.cfg.close_to_tray and not QSystemTrayIcon.isSystemTrayAvailable():
            self._show_alert("系统托盘不可用", "当前环境没有系统托盘，关闭窗口将直接退出。")
        self.footer_state.setText("设置已保存")

    # ================================================================== 日志
    def _on_log(self, timestamp: str, level: str, message: str) -> None:
        self.log_console.append_record(timestamp, level, message)

    def _on_log_filter(self) -> None:
        self.log_console.set_min_level(int(self.log_filter.currentData() or 20))

    def _on_detail_toggled(self, checked: bool) -> None:
        if self._loading:
            return
        self.cfg.log_level = "DEBUG" if checked else "INFO"
        set_log_level(self.cfg.log_level)
        if checked:
            self.log_filter.setCurrentIndex(0)
            self.log_console.set_min_level(10)
        self._persist_later()

    def _open_log_file(self) -> None:
        from orbit.logging_setup import get_active_log_file
        from orbit.util.paths import log_dir

        # 优先打开实际生效的日志（主文件被占用时会落到备用文件）
        active = get_active_log_file()
        path = active if active is not None else log_dir() / "app.log"
        try:
            if path.is_file():
                open_path(path)
                return
            parent = path.parent
            parent.mkdir(parents=True, exist_ok=True)
            open_path(parent)
        except Exception as exc:
            self._show_alert("无法打开日志", str(exc))

    def _toggle_log_visible(self) -> None:
        visible = self.log_toggle_btn.isChecked()
        self.cfg.log_visible = visible
        self.log_card.setVisible(visible)
        if visible:
            total = max(420, self.main_splitter.height())
            self.main_splitter.setSizes([max(300, total - 205), 205])
        else:
            self.main_splitter.setSizes([1, 0])
        self._persist_later()

    def _switch_view(self, index: int) -> None:
        self.view_stack.setCurrentIndex(index)
        if index == 1 and self._last_samples is not None and self._last_samples.size:
            rate, _, _ = self._effective_source()
            self.spectrum.set_bands(spectrum_bands(self._last_samples, rate))

    # ================================================================== 录音
    def _build_request(self) -> RecordingRequest | None:
        device = self._current_device
        if not device:
            self._show_alert("没有可用的音频设备", "请刷新设备并确认播放设备已启用。")
            return None
        fmt = get_output_format(self.format_combo.currentData())
        rate, channels, depth = self._effective_source()
        ok, message = validate_rate_for_format(fmt, rate)
        if not ok:
            self._show_alert("当前格式不支持该采样率", message)
            return None
        if depth not in fmt.allowed_depths:
            self._show_alert("位深不受支持", f"{fmt.label} 不支持 {depth}-bit。")
            return None
        if fmt.requires_ffmpeg:
            info = inspect_ffmpeg(self.cfg.ffmpeg_path)
            if not info.available or not info.supports(fmt):
                self._show_alert(
                    "需要 FFmpeg",
                    (info.error or f"缺少 {fmt.codec} 编码器")
                    + "\n请在 设置 → 系统集成 中指定 ffmpeg.exe，或改用 WAV/FLAC。",
                    timeout_ms=18000,
                )
                return None
        output_dir = Path(self.cfg.output_dir).expanduser()
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                prefix=".aa_write_test_", dir=output_dir, delete=True
            ):
                pass
        except OSError as exc:
            self._show_alert("保存目录不可写", f"{output_dir}\n{exc}")
            return None

        tokens = build_tokens(
            device.clean_name, fmt.key, rate, depth, channels, when=datetime.now()
        )
        template = self.cfg.name_template or "{date}_{time}_{device}"
        base_name = render_template(template, tokens) or sanitize_filename("Recording")
        for ext in SUPPORTED_AUDIO_EXTENSIONS:
            if base_name.lower().endswith(ext):
                base_name = base_name[: -len(ext)]
                break
        base_name = sanitize_filename(base_name)
        return RecordingRequest(
            device=device,
            sample_rate=rate,
            channels=channels,
            bit_depth=depth,
            buffer_ms=self.cfg.buffer_ms,
            output_format=fmt.key,
            output_dir=output_dir,
            base_name=base_name,
            bitrate_kbps=self.cfg.bitrate_kbps,
            metadata_enabled=self.cfg.metadata_enabled,
            split_seconds=self.cfg.split_seconds,
            split_bytes=self.cfg.split_bytes,
            ffmpeg_path=self.cfg.ffmpeg_path,
            max_seconds=self.cfg.max_seconds,
        )

    def _start_recording(self, scheduled: bool = False) -> None:
        if self._state != "idle" or self._recorder.active:
            return
        request = self._build_request()
        if request is None:
            return
        fmt = get_output_format(request.output_format)
        rate = request.sample_rate
        channels = request.channels
        if not fmt.lossless and not self._lossy_notice_shown:
            if scheduled:
                log.warning("定时录制使用有损格式：%s", fmt.label)
                self._lossy_notice_shown = True
            elif not self._confirm(
                "使用有损格式？",
                f"{fmt.label} 为有损压缩，无法保留原始音频的全部细节。"
                "如果目标是保留音质差异，建议使用 WAV 或 FLAC。",
                "仍要录制",
            ):
                return
            else:
                self._lossy_notice_shown = True
        if self._current_device and (
            rate != self._current_device.sample_rate
            or channels != self._current_device.channels
        ):
            if scheduled:
                log.warning(
                    "定时录制使用非原生格式：%d Hz / %d ch（设备原生 %d Hz / %d ch）",
                    rate,
                    channels,
                    self._current_device.sample_rate,
                    self._current_device.channels,
                )
                self._native_notice_shown = True
            elif not self._native_notice_shown:
                if not self._confirm(
                    "使用非原生格式？",
                    "当前采样率/声道数不是设备原生格式。Windows 共享混音器可能进行"
                    "重采样或声道混合，从而影响位完美性。\n\n"
                    "如需最大保真，请选择“原生”采样率与声道数。",
                    "继续录制",
                ):
                    return
                self._native_notice_shown = True
        self.player.stop()
        self.waveform.clear()
        self.spectrum.clear()
        self.level_meter.reset()
        self._last_samples = None
        self._last_stats = {}
        self.peak_label.setText("峰值 -∞ dBFS")
        self.rms_label.setText("RMS -∞ dBFS")
        self.timer_label.setText("00:00:00.0")
        self.encoding_label.setText("")
        self.metric_size.set_value("0 B")
        self.metric_dropped.set_value("0")
        self.metric_segment.set_value("1")
        self._apply_state("starting", "正在启动录音…")
        ok = self._recorder.start(request)
        if not ok:
            self._apply_state("idle", "录音启动失败")
        else:
            log.info("录音请求：%s", request)

    def _stop_recording(self) -> None:
        if self._recorder.active:
            self._recorder.stop()

    def _toggle_pause(self) -> None:
        self._recorder.toggle_pause()

    def _hotkey_record(self) -> None:
        if self._recorder.active:
            self._recorder.stop()
        else:
            self._start_recording()

    def _hotkey_pause(self) -> None:
        if self._recorder.active:
            self._recorder.toggle_pause()

    def _on_global_hotkey(self, action: str) -> None:
        if action == "toggle_record":
            if self._recorder.active:
                self._recorder.stop()
            else:
                self._start_recording()
        elif action == "toggle_pause":
            if self._recorder.active:
                self._recorder.toggle_pause()
        elif action == "open_folder":
            self._open_output_folder()

    def _on_recorder_state(self, state: str, message: str) -> None:
        self._apply_state(state, message)

    def _on_recorder_started(self, info: dict) -> None:
        self._stream_info = info
        self.metric_rate.set_value(f"{info.get('sample_rate', 0):,} Hz")
        self.metric_buffer.set_value(
            f"{info.get('buffer_frames', 0)} 帧 / {info.get('buffer_ms', 0):g} ms"
        )
        self.metric_dropped.set_value("0")
        self.metric_segment.set_value("1")
        self.footer_meta.setText(
            f"{info.get('output_format', '')} · {info.get('sample_format', '')} · "
            f"PortAudio"
        )
        log.info("录音 UI 已连接：%s", info.get("output_path", ""))

    def _on_paused_changed(self, paused: bool) -> None:
        if paused:
            self.level_meter.reset()
            self.peak_label.setText("峰值 -∞ dBFS")
            self.rms_label.setText("RMS -∞ dBFS")
            self.state_label.setText("录音已暂停")
        else:
            self.state_label.setText("正在采集系统音频")
        self._update_pause_button()

    def _on_stats(self, stats: dict) -> None:
        self._last_stats = stats
        elapsed = float(stats.get("elapsed", 0.0))
        self.timer_label.setText(self._format_elapsed(elapsed))
        self.metric_size.set_value(human_size(float(stats.get("bytes", 0))))
        rate = int(stats.get("sample_rate", 0))
        if rate:
            self.metric_rate.set_value(f"{rate:,} Hz")
        self.metric_buffer.set_value(
            f"{stats.get('buffer_frames', 0)} 帧 / "
            f"{round(stats.get('buffer_frames', 0) / max(1, rate) * 1000):d} ms"
        )
        dropped = int(stats.get("dropped_frames", 0))
        overflows = int(stats.get("overflows", 0))
        self.metric_dropped.set_value(f"{dropped:,}")
        self.metric_dropped.value_label.setStyleSheet(
            f"color: {Colors.RED if dropped else Colors.TEXT_SOFT};"
            "font-size: 11px; font-weight: 600;"
        )
        self.metric_dropped.setToolTip(
            f"应用队列丢帧：{dropped:,}\n"
            f"PortAudio 输入溢出事件：{overflows:,}\n"
            "非零值会同时写入调试日志。"
        )
        self.metric_dropped.value_label.setToolTip(self.metric_dropped.toolTip())
        self.metric_segment.set_value(f"第 {stats.get('segment', 1)} 段")
        current = stats.get("current_file")
        if current:
            self.footer_state.setText(shorten_path(Path(current), 84))
        queue = int(stats.get("queue", 0))
        if queue > 8:
            self.state_label.setText(f"正在采集系统音频 · 队列 {queue}")
        elif not stats.get("paused") and self._state == "recording":
            self.state_label.setText("正在采集系统音频")

    def _on_visual(self, frame: dict) -> None:
        samples = frame.get("samples")
        peaks = frame.get("peaks") or []
        rms = frame.get("rms") or []
        if samples is None or not len(samples):
            return
        self._last_samples = samples
        self.waveform.set_samples(samples)
        self.level_meter.set_levels(peaks, rms)
        peak = max(peaks) if peaks else 0.0
        rms_value = max(rms) if rms else 0.0
        self.peak_label.setText(f"峰值 {amplitude_to_db(peak):.1f} dBFS")
        self.rms_label.setText(f"RMS {amplitude_to_db(rms_value):.1f} dBFS")
        if self.view_stack.currentIndex() == 1:
            rate = int(frame.get("sample_rate") or self._effective_source()[0])
            self.spectrum.set_bands(spectrum_bands(samples, rate))

    def _on_segment_started(self, path: str, part: int) -> None:
        self.metric_segment.set_value(f"第 {part} 段")
        self.footer_state.setText(f"正在写入：{shorten_path(Path(path), 80)}")
        log.info("当前分段：%s", path)

    def _on_file_ready(self, path: str) -> None:
        log.info("录音文件已生成：%s", path)
        self._file_refresh_timer.start()
        self.footer_state.setText(f"已保存：{shorten_path(Path(path), 84)}")

    def _on_processing(self, name: str, progress: float) -> None:
        pct = int(max(0.0, min(1.0, progress)) * 100)
        self.encoding_label.setText(f"编码 {name} · {pct}%")
        if self._state in ("stopping", "finishing"):
            self.state_label.setText(f"正在编码 {name} · {pct}%")

    def _on_recorder_error(self, title: str, detail: str) -> None:
        log.error("%s：%s", title, detail)
        self._show_alert(title, detail, timeout_ms=18000)
        if self.cfg.notify_on_complete and self.tray and self.tray.isVisible():
            self.tray.showMessage(title, detail[:180], QSystemTrayIcon.MessageIcon.Warning, 6000)

    def _on_device_lost(self, message: str) -> None:
        self.footer_state.setText("音频设备连接中断")
        log.warning("设备中断：%s", message)
        QTimer.singleShot(1200, lambda: self._request_scan(force=True, silent=False))

    def _on_finished(self, result: RecordingResult) -> None:
        self._apply_state("idle", "录音已保存" if result.files else "就绪")
        self._last_stats = {}
        self.encoding_label.setText("")
        saved_paths = [*result.files, *result.preserved_sources]
        self.metric_size.set_value(
            human_size(sum(p.stat().st_size for p in saved_paths if p.exists()))
            if saved_paths
            else "0 B"
        )
        if result.files:
            names = "、".join(p.name for p in result.files[:3])
            if len(result.files) > 3:
                names += f" 等 {len(result.files)} 个文件"
            self.footer_state.setText(f"已保存 {names}")
            self.state_label.setText(
                f"已保存 {len(result.files)} 个文件 · "
                f"{format_duration(result.elapsed)}"
            )
            self._notify_finished(
                "录音已保存",
                f"{names}\n{format_duration(result.elapsed)} · "
                f"丢帧 {result.dropped_frames}",
            )
        elif result.preserved_sources:
            self.state_label.setText("已保留原始 WAV（转码失败）")
        else:
            self.state_label.setText("未采集到音频")
            self._show_alert(
                "没有生成录音文件",
                "录音时间过短或音频设备未返回数据。请检查播放设备并重试。",
            )
        if result.errors:
            self._show_alert(
                "录音过程中出现错误",
                "\n".join(result.errors[:3]),
                timeout_ms=20000,
            )
        if self.cfg.notify_on_complete:
            log.info("录音结束通知：%s", result)
        self._refresh_files()
        self._update_tray_actions()
        QTimer.singleShot(1500, lambda: self._request_scan(force=True, silent=True))
        QTimer.singleShot(2500, self.level_meter.reset)
        if self._quit_after_finish:
            QTimer.singleShot(250, self._quit_now)

    def _format_elapsed(self, seconds: float) -> str:
        seconds = max(0.0, seconds)
        whole = int(seconds)
        hours, rem = divmod(whole, 3600)
        minutes, secs = divmod(rem, 60)
        tenth = int((seconds - whole) * 10) % 10
        return f"{hours:02d}:{minutes:02d}:{secs:02d}.{tenth}"

    # ================================================================== 状态
    def _apply_state(self, state: str, message: str = "") -> None:
        self._state = state
        active = state in ("starting", "recording", "paused", "stopping", "finishing")
        editable = state == "idle"
        has_device = self._current_device is not None

        self.record_btn.setEnabled(editable and has_device)
        self.record_btn.set_recording(state in ("starting", "recording", "paused", "stopping", "finishing"))
        self.pause_btn.setEnabled(state in ("recording", "paused"))
        self.stop_btn.setEnabled(state in ("starting", "recording", "paused"))
        self._update_pause_button()
        self.settings_btn.setEnabled(editable)

        for widget in (
            self.device_combo,
            self.refresh_btn,
            self.rate_combo,
            self.depth_combo,
            self.channels_combo,
            self.format_combo,
            self.dir_edit,
            self.name_edit,
            self.metadata_check,
            self.bitrate_combo,
            self.open_dir_btn,
        ):
            widget.setEnabled(editable)
        self.refresh_btn.setEnabled(editable and not self._scanner.busy)
        self.player.setEnabled(editable)

        if state == "idle":
            color = Colors.GREEN
            pulse = False
            pill = "无设备" if not has_device else "就绪"
            if message:
                self.state_label.setText(message)
        elif state == "starting":
            color = Colors.AMBER
            pulse = True
            pill = "启动中"
        elif state == "recording":
            color = Colors.RED
            pulse = True
            pill = "录音中"
        elif state == "paused":
            color = Colors.AMBER
            pulse = False
            pill = "已暂停"
        elif state == "stopping":
            color = Colors.ACCENT_LIGHT
            pulse = True
            pill = "保存中"
        else:  # finishing
            color = Colors.ACCENT_LIGHT
            pulse = True
            pill = "编码中"
        self.status_pill.set_status(pill, color, pulse)
        self.state_dot.setStyleSheet(f"color: {color}; font-size: 9px;")
        if message and state != "idle":
            self.state_label.setText(message)
        self._update_tray_actions()
        if active:
            self.player.stop()
        self._update_format_summary()
        # 状态变化统一驱动实时监听：空闲开、录音中关
        self.waveform.set_recording(state in ("recording", "paused"))
        self.spectrum.set_recording(state in ("recording", "paused"))
        self._sync_monitor()

    def _update_pause_button(self) -> None:
        paused = self._state == "paused"
        self.pause_btn.setIcon(icon("play" if paused else "pause"))
        self.pause_btn.setText("继续" if paused else "暂停")
        self.pause_btn.setToolTip("继续录音（Ctrl+Alt+F10）" if paused else "暂停录音（Ctrl+Alt+F10）")

    # ================================================================== 文件
    def _set_watch_dir(self, path: Path) -> None:
        try:
            path.mkdir(parents=True, exist_ok=True)
            watched = self._watcher.directories()
            if watched:
                self._watcher.removePaths(watched)
            if not self._watcher.addPath(str(path)):
                log.debug("无法监视目录：%s", path)
        except Exception:
            log.debug("设置目录监视失败：%s", path, exc_info=True)

    def _on_directory_changed(self, path: str) -> None:
        self._file_refresh_timer.start()

    def _refresh_files(self) -> None:
        directory = Path(self.cfg.output_dir)
        infos: list[RecordingFileInfo] = []
        if directory.exists():
            try:
                for entry in directory.iterdir():
                    if not entry.is_file():
                        continue
                    if entry.name.startswith(".") or entry.name.endswith(".part"):
                        continue
                    if entry.suffix.lower() not in SUPPORTED_AUDIO_EXTENSIONS:
                        continue
                    try:
                        stat = entry.stat()
                    except OSError:
                        continue
                    ext = entry.suffix.lower()
                    infos.append(
                        RecordingFileInfo(
                            path=entry,
                            size=stat.st_size,
                            modified=datetime.fromtimestamp(stat.st_mtime),
                            output_format=ext.lstrip(".").upper(),
                        )
                    )
            except OSError:
                log.debug("读取录音目录失败", exc_info=True)
        infos.sort(key=lambda i: i.modified, reverse=True)
        self._file_infos = infos[:200]
        self._rebuild_file_rows()
        self.file_count.setText(f"{len(self._file_infos)} 个文件")
        self._set_watch_dir(directory)

    def _rebuild_file_rows(self) -> None:
        while self.file_layout.count():
            item = self.file_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self._file_rows.clear()
        if not self._file_infos:
            empty = QLabel("还没有录音文件\n完成录音后会显示在这里")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setObjectName("Tiny")
            empty.setMinimumHeight(90)
            self.file_layout.addWidget(empty)
            return
        for info in self._file_infos:
            row = FileRow(
                info.path,
                human_size(info.size),
                info.modified.strftime("%m-%d %H:%M"),
            )
            row.play_requested.connect(self._play_file)
            row.reveal_requested.connect(self._reveal_file)
            row.delete_requested.connect(self._delete_file)
            if str(info.path) == self._playing_path:
                row.set_playing(True)
            self._file_rows.append(row)
            self.file_layout.addWidget(row)

    def _play_file(self, path: str) -> None:
        if self._recorder.active:
            self._show_alert("录音进行中", "为避免把试听声音再次录入，请先结束录音。")
            return
        if not Path(path).exists():
            self._refresh_files()
            return
        self._playing_path = path
        self.player.play_file(path)
        self._update_playing_rows()

    def _reveal_file(self, path: str) -> None:
        try:
            reveal_path(Path(path))
        except Exception as exc:
            self._show_alert("无法定位文件", str(exc))

    def _delete_file(self, path: str) -> None:
        target = Path(path)
        if not target.exists():
            self._refresh_files()
            return
        box = QMessageBox(self)
        box.setWindowTitle("删除录音")
        box.setIcon(QMessageBox.Icon.Question)
        box.setText(f"将“{target.name}”移至回收站？")
        box.setInformativeText("此操作不会影响正在进行的录音。")
        delete_btn = box.addButton("移至回收站", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        QTimer.singleShot(0, lambda: _dark_titlebar(box))
        box.exec()
        if box.clickedButton() is not delete_btn:
            return
        if self.player.path == str(target):
            self.player.stop()
            self._playing_path = ""
        ok = recycle_path(target)
        if not ok:
            self._show_alert("删除失败", "无法将文件移至回收站，文件仍保留在原位置。")
            return
        log.info("录音文件已移至回收站：%s", target)
        self._refresh_files()
        self.footer_state.setText(f"已移至回收站：{target.name}")

    def _on_playing_changed(self, path: str, playing: bool) -> None:
        if not playing and path == self._playing_path:
            self._playing_path = path
            self._update_playing_rows()
        elif playing:
            self._playing_path = path
            self._update_playing_rows()

    def _update_playing_rows(self) -> None:
        for row in self._file_rows:
            row.set_playing(str(row.path) == self._playing_path and self.player.path == self._playing_path)

    def _on_player_error(self, message: str) -> None:
        log.warning("试听失败：%s", message)
        self.footer_state.setText(f"无法试听：{message}")
        self._show_alert(
            "无法试听该文件",
            f"{message}\n可能是 Qt 当前后端不支持该编码，可点击试听条右侧按钮用系统播放器打开。",
            timeout_ms=9000,
        )

    def _open_external(self, path: str) -> None:
        try:
            if path:
                open_path(Path(path))
        except Exception as exc:
            self._show_alert("无法打开文件", str(exc))

    def _on_player_volume_changed(self, value: int) -> None:
        """试听音量改变：写入配置并延迟保存。"""
        self.cfg.player_volume = int(value)
        self._persist_later()

    # ================================================================== 托盘/热键/日程
    def _setup_tray(self) -> None:
        self.tray: QSystemTrayIcon | None = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            log.info("系统托盘不可用")
            return
        self.tray = QSystemTrayIcon(app_icon(), self)
        self.tray.setToolTip("Orbit · 系统音频采集")
        menu = QMenu(self)
        self.tray_menu = menu
        self.tray_show_action = QAction("显示主界面", self)
        self.tray_show_action.triggered.connect(self._show_from_tray)
        self.tray_start_action = QAction("开始录音", self)
        self.tray_start_action.triggered.connect(self._start_recording)
        self.tray_pause_action = QAction("暂停录音", self)
        self.tray_pause_action.triggered.connect(self._toggle_pause)
        self.tray_stop_action = QAction("停止录音", self)
        self.tray_stop_action.triggered.connect(self._stop_recording)
        self.tray_folder_action = QAction("打开录音目录", self)
        self.tray_folder_action.triggered.connect(self._open_output_folder)
        self.tray_quit_action = QAction("退出", self)
        self.tray_quit_action.triggered.connect(self._request_quit_from_tray)
        menu.addAction(self.tray_show_action)
        menu.addSeparator()
        menu.addAction(self.tray_start_action)
        menu.addAction(self.tray_pause_action)
        menu.addAction(self.tray_stop_action)
        menu.addSeparator()
        menu.addAction(self.tray_folder_action)
        menu.addSeparator()
        menu.addAction(self.tray_quit_action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()
        self._update_tray_actions()

    def _update_tray_actions(self) -> None:
        if not self.tray:
            return
        self.tray_start_action.setEnabled(self._state == "idle" and self._current_device is not None)
        self.tray_pause_action.setEnabled(self._state in ("recording", "paused"))
        self.tray_pause_action.setText("继续录音" if self._state == "paused" else "暂停录音")
        self.tray_stop_action.setEnabled(self._state in ("starting", "recording", "paused"))
        self.tray_show_action.setText("显示主界面")

    def _on_tray_activated(self, reason) -> None:  # noqa: ANN001
        if reason in (
            QSystemTrayIcon.ActivationReason.DoubleClick,
            QSystemTrayIcon.ActivationReason.Trigger,
        ):
            self._show_from_tray()

    def _show_from_tray(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _on_schedule_fired(self) -> None:
        log.info("每日定时任务触发")
        if self._state == "idle" and not self._recorder.active:
            self._start_recording(scheduled=True)
        else:
            log.info("定时任务跳过：当前正在录音")
            self._show_alert("定时任务已跳过", "当前已有录音正在进行，本次定时未执行。", timeout_ms=8000)
        self._reschedule_daily()

    def _reschedule_daily(self) -> None:
        if not self.cfg.schedule_enabled:
            self._schedule_timer.stop()
            self._schedule_target = None
            self._update_split_hint()
            return
        try:
            hour, minute = (int(x) for x in self.cfg.schedule_time.split(":"))
        except Exception:
            hour, minute = 23, 0
        now = QDateTime.currentDateTime()
        target = QDateTime(now.date(), QTime(hour, minute, 0))
        if target <= now.addSecs(2):
            target = target.addDays(1)
        self._schedule_target = target
        ms = max(1000, min(2_147_000_000, now.msecsTo(target)))
        self._schedule_timer.start(ms)
        self._update_split_hint()
        log.info("下次定时录制：%s", target.toString("yyyy-MM-dd HH:mm"))

    # ================================================================== 通知/提示
    def _notify_finished(self, title: str, body: str) -> None:
        if not (self.cfg.notify_on_complete and self.tray):
            return
        if self.isVisible() and not self.isMinimized():
            return
        self.tray.showMessage(title, body, QSystemTrayIcon.MessageIcon.Information, 6000)

    def _show_alert(self, title: str, detail: str = "", timeout_ms: int = 12000) -> None:
        self.alert.show_alert(title, detail, timeout_ms)
        if self.cfg.notify_on_complete and self.tray and not self.isVisible():
            self.tray.showMessage(title, detail[:180], QSystemTrayIcon.MessageIcon.Warning, 5000)

    def _confirm(self, title: str, text: str, confirm_text: str) -> bool:
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText(text)
        ok = box.addButton(confirm_text, QMessageBox.ButtonRole.AcceptRole)
        box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        QTimer.singleShot(0, lambda: _dark_titlebar(box))
        box.exec()
        return box.clickedButton() is ok

    # ================================================================== 关闭
    def _save_window_state(self) -> None:
        try:
            self.cfg.window_geometry = bytes(self.saveGeometry().toBase64()).decode("ascii")
            self.store.save(self.cfg)
        except Exception:
            log.exception("保存窗口状态失败")

    def _request_quit_from_tray(self) -> None:
        if self._recorder.active:
            self.showNormal()
            self.raise_()
            self.activateWindow()
            if not self._confirm(
                "正在录音",
                "当前录音尚未结束。停止录音、保存文件并退出吗？",
                "停止并退出",
            ):
                return
            self._quit_after_finish = True
            self._recorder.stop()
            return
        self._quit_now()

    def _quit_now(self) -> None:
        self._force_quit = True
        if self._recorder.active:
            self._quit_after_finish = True
            self._recorder.stop()
            return
        self._begin_shutdown()

    def _begin_shutdown(self) -> None:
        """
        打包环境下 PortAudio/QtMultimedia 的释放可能长时间阻塞主线程，
        表现为“未响应”。先 hide 让用户立刻看到窗口关闭，看门狗保证
        即使清理卡死，进程也会在数秒内结束。
        """
        from orbit.util.exit_guard import arm_exit_watchdog

        arm_exit_watchdog(3.0)
        self._save_window_state()
        self.hide()
        self._monitor.stop()
        if self._global_hotkeys:
            self._global_hotkeys.unregister()
        self.player.stop()
        if self.tray:
            self.tray.hide()
        QApplication.quit()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self._force_quit:
            self._save_window_state()
            self._monitor.stop()
            event.accept()
            return
        if self._recorder.active:
            if not self._confirm(
                "正在录音",
                "当前录音正在进行。停止录音、保存文件后退出吗？",
                "停止并退出",
            ):
                event.ignore()
                return
            self._quit_after_finish = True
            self._recorder.stop()
            event.ignore()
            return
        if self.cfg.close_to_tray and self.tray and self.tray.isVisible():
            self.hide()  # 先隐藏，让窗口立刻从屏幕消失（hideEvent 会停监听）
            event.ignore()
            if not self.cfg.tray_hint_shown:
                self.cfg.tray_hint_shown = True
                self._persist_later()
                self.tray.showMessage(
                    "Orbit 仍在运行",
                    "已最小化到系统托盘，双击图标可恢复窗口。",
                    QSystemTrayIcon.MessageIcon.Information,
                    4000,
                )
            return
        self._begin_shutdown()
        event.accept()

    def showEvent(self, event) -> None:  # noqa: ANN001
        super().showEvent(event)
        if self.cfg.log_visible and self.main_splitter.sizes()[1] < 100:
            QTimer.singleShot(0, lambda: self.main_splitter.setSizes([560, 170]))
        # 从托盘恢复时重新开启实时监听
        self._sync_monitor()

    def hideEvent(self, event) -> None:  # noqa: ANN001
        super().hideEvent(event)
        # 最小化到托盘时停止监听，避免无谓的 CPU/设备占用
        if self._monitor.running:
            self._monitor.stop()
            self._monitor_device = None
