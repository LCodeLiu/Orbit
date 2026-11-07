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

"""视觉主题：颜色、字体、图标与全局 QSS。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QColor, QIcon, QPixmap

import ctypes
import sys

def _apply_dark_titlebar(window) -> None:  # noqa: ANN001
    if sys.platform != "win32":
        return
    try:
        hwnd = int(window.winId())
        value = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 20, ctypes.byref(value), ctypes.sizeof(value)
        )
    except Exception:
        pass

ASSETS = Path(__file__).resolve().parents[1] / "assets"
ICONS = ASSETS / "icons"


class Colors:
    BG = "#121212"
    SURFACE = "#1E1E1E"
    SURFACE_2 = "#262626"
    SURFACE_3 = "#303030"
    BORDER = "#4E4E4E"
    BORDER_HOVER = "#5C5C5C"
    TEXT = "#ECECEC"
    TEXT_SOFT = "#CCCCCC"
    MUTED = "#8A8A8A"
    MUTED_DIM = "#6A6A6A"
    ACCENT = "#9A9A9A"
    ACCENT_LIGHT = "#BBBBBB"
    GREEN = "#4CAF50"
    AMBER = "#5C5C5C"
    RED = "#F44336"
    PINK = "#ECECEC"
    CHECK = "#0078D4"


def icon(name: str) -> QIcon:
    path = ICONS / f"{name}.svg"
    return QIcon(str(path)) if path.exists() else QIcon()


def app_icon() -> QIcon:
    # 优先使用多尺寸 ICO，Windows 任务栏在高 DPI 下更清晰
    for name in ("app.ico", "logo.svg"):
        path = ASSETS / name
        if path.exists():
            return QIcon(str(path))
    return QIcon()


def pixmap(name: str, size: int = 24) -> QPixmap:
    pm = QPixmap(str(ICONS / f"{name}.svg"))
    if pm.isNull():
        return pm
    return pm.scaled(size, size)


def color(value: str) -> QColor:
    return QColor(value)


def build_stylesheet() -> str:
    assets = ASSETS.as_posix()
    return f"""
/* ---------------------------------------------------------------- 基础 */
* {{
    outline: none;
}}
QWidget {{
    color: {Colors.TEXT};
    font-family: "Segoe UI", "Microsoft YaHei UI";
    font-size: 13px;
}}
QMainWindow, QWidget#Root {{
    background: {Colors.BG};
}}
QDialog {{
    background: {Colors.BG};
}}
QToolTip {{
    background: {Colors.SURFACE_2};
    color: {Colors.TEXT};
    border: 1px solid {Colors.BORDER};
    border-radius: 6px;
    padding: 6px 9px;
}}
QLabel {{
    background: transparent;
}}
QLabel#Overline {{
    color: {Colors.MUTED};
    font-size: 10px;
    font-weight: 600;
}}
QLabel#SectionTitle {{
    color: {Colors.TEXT};
    font-size: 15px;
    font-weight: 600;
}}
QLabel#Muted {{
    color: {Colors.MUTED};
    font-size: 12px;
}}
QLabel#Tiny {{
    color: {Colors.MUTED_DIM};
    font-size: 11px;
}}
QLabel#Timer {{
    color: {Colors.TEXT};
    font-family: "Consolas", "Segoe UI";
    font-size: 36px;
    font-weight: 400;
}}
QLabel#StateText {{
    color: {Colors.TEXT_SOFT};
    font-size: 12px;
    font-weight: 600;
}}
QLabel#PreviewName {{
    color: {Colors.TEXT_SOFT};
    font-size: 12px;
}}
QLabel#Mono {{
    color: {Colors.MUTED};
    font-family: "Consolas";
    font-size: 11px;
}}
QLabel#Warning {{
    color: {Colors.AMBER};
    font-size: 11px;
}}
QLabel#Danger {{
    color: {Colors.RED};
    font-size: 11px;
}}
QLabel#Success {{
    color: {Colors.GREEN};
    font-size: 11px;
}}

/* ---------------------------------------------------------------- 卡片 */
QFrame#Card {{
    background-color: {Colors.SURFACE};
    border: 1px solid {Colors.BORDER};
    border-radius: 8px;
}}
QFrame#TransportCard {{
    background-color: {Colors.SURFACE};
    border: 1px solid {Colors.BORDER};
    border-radius: 8px;
}}
QFrame#Alert {{
    background-color: {Colors.SURFACE_2};
    border: 1px solid {Colors.BORDER};
    border-radius: 8px;
}}
QFrame#FileRow {{
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 8px;
}}
QFrame#FileRow:hover {{
    background-color: {Colors.SURFACE_2};
    border: 1px solid {Colors.BORDER};
}}
QFrame#FileRow[playing="true"] {{
    background-color: {Colors.SURFACE_2};
    border: 1px solid {Colors.BORDER_HOVER};
}}
QFrame#Segmented {{
    background-color: {Colors.SURFACE};
    border: 1px solid {Colors.BORDER};
    border-radius: 8px;
}}
QFrame#Divider {{
    background-color: {Colors.BORDER};
    max-height: 1px;
    min-height: 1px;
    border: none;
}}
QFrame#Chip {{
    background-color: {Colors.SURFACE_2};
    border: 1px solid {Colors.BORDER};
    border-radius: 6px;
}}
QLabel#IconBadge {{
    background-color: {Colors.SURFACE_2};
    border: 1px solid {Colors.BORDER};
    border-radius: 6px;
}}
QWidget#PlayerBar {{
    background-color: {Colors.SURFACE};
    border: 1px solid {Colors.BORDER};
    border-radius: 8px;
}}
QFrame#SettingsBox {{
    background-color: {Colors.SURFACE};
    border: 1px solid {Colors.BORDER};
    border-radius: 8px;
}}
QTabWidget#SettingsTabs::pane {{
    border: none;
    background: transparent;
    top: -1px;
}}
QTabWidget#SettingsTabs QTabBar::tab {{
    background: transparent;
    color: {Colors.MUTED};
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 6px 14px;
    margin-right: 4px;
    font-size: 12px;
}}
QTabWidget#SettingsTabs QTabBar::tab:hover {{
    color: {Colors.TEXT};
}}
QTabWidget#SettingsTabs QTabBar::tab:selected {{
    background-color: {Colors.SURFACE_2};
    border-color: {Colors.BORDER};
    color: {Colors.TEXT};
}}
QTextEdit#Diagnostics {{
    background-color: {Colors.SURFACE};
    border: 1px solid {Colors.BORDER};
    border-radius: 8px;
    color: {Colors.TEXT_SOFT};
    font-family: "Consolas", "Segoe UI";
    font-size: 11px;
    padding: 8px;
}}

/* ---------------------------------------------------------------- 文本编辑/输入 */
QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox, QTimeEdit, QDateEdit {{
    background-color: {Colors.SURFACE};
    border: 1px solid {Colors.BORDER};
    border-radius: 6px;
    padding: 6px 10px;
    min-height: 20px;
    selection-background-color: {Colors.BORDER_HOVER};
    color: {Colors.TEXT};
}}
QComboBox:hover, QLineEdit:hover, QSpinBox:hover, QTimeEdit:hover {{
    border-color: {Colors.BORDER_HOVER};
}}
QComboBox:focus, QLineEdit:focus, QSpinBox:focus, QTimeEdit:focus {{
    border-color: {Colors.ACCENT};
}}
QComboBox:disabled, QLineEdit:disabled, QSpinBox:disabled, QTimeEdit:disabled {{
    color: {Colors.MUTED_DIM};
    background-color: {Colors.SURFACE};
    border-color: {Colors.BORDER};
}}
QComboBox {{
    padding-right: 30px;
}}
QComboBox::drop-down {{
    border: none;
    width: 28px;
}}
QComboBox::down-arrow {{
    image: url("{assets}/icons/chevron-down.svg");
    width: 14px;
    height: 14px;
}}
QComboBox QAbstractItemView {{
    background-color: {Colors.SURFACE};
    border: 1px solid {Colors.BORDER};
    border-radius: 6px;
    padding: 5px;
    selection-background-color: {Colors.BORDER_HOVER};
    color: {Colors.TEXT};
    outline: 0;
}}
QComboBox QAbstractItemView::item {{
    min-height: 28px;
    padding: 3px 9px;
    border-radius: 4px;
}}
QComboBox QAbstractItemView::item:selected {{
    background-color: {Colors.BORDER_HOVER};
}}
QSpinBox QLineEdit, QDoubleSpinBox QLineEdit, QTimeEdit QLineEdit {{
    padding: 0px 2px;
    background: transparent;
    border: none;
    color: {Colors.TEXT};
}}
QLineEdit#PathEdit {{
    font-family: "Consolas";
    font-size: 11px;
}}
/* 隐藏微调按钮：用宽度 0 实现（不要用 ButtonSymbols.NoButtons，
   Qt 在 QStyleSheetStyle 下会把 NoButtons 的 QSpinBox 内部 QLineEdit 压成 1px 宽，文字不可见） */
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button,
QTimeEdit::up-button, QTimeEdit::down-button {{
    width: 0px;
    height: 0px;
    border: none;
    background: transparent;
}}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow, QTimeEdit::up-arrow {{
    image: url("{assets}/icons/chevron-down.svg");
    width: 9px;
    height: 9px;
}}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow, QTimeEdit::down-arrow {{
    image: url("{assets}/icons/chevron-down.svg");
    width: 9px;
    height: 9px;
}}

/* ---------------------------------------------------------------- 按钮 */
QPushButton {{
    background-color: {Colors.SURFACE_2};
    border: 1px solid {Colors.BORDER};
    border-radius: 6px;
    padding: 6px 14px;
    color: {Colors.TEXT_SOFT};
    font-weight: 500;
}}
QPushButton:hover {{
    background-color: {Colors.SURFACE_3};
    border-color: {Colors.BORDER_HOVER};
    color: {Colors.TEXT};
}}
QPushButton:pressed {{
    background-color: {Colors.SURFACE};
}}
QPushButton:disabled {{
    color: {Colors.MUTED_DIM};
    background-color: {Colors.SURFACE};
    border-color: {Colors.BORDER};
}}
QPushButton#Primary {{
    background-color: {Colors.SURFACE_2};
    border: 1px solid {Colors.BORDER};
    color: {Colors.TEXT};
    font-weight: 600;
    padding: 8px 18px;
}}
QPushButton#Primary:hover {{
    background-color: {Colors.SURFACE_3};
    border-color: {Colors.BORDER_HOVER};
    color: {Colors.TEXT};
}}
QPushButton#Primary:pressed {{
    background-color: {Colors.SURFACE};
}}
QPushButton#Primary:disabled {{
    background-color: {Colors.SURFACE};
    border-color: {Colors.BORDER};
    color: {Colors.MUTED_DIM};
}}
QPushButton#Ghost {{
    background-color: transparent;
    border: 1px solid transparent;
    color: {Colors.MUTED};
}}
QPushButton#Ghost:hover {{
    background-color: {Colors.SURFACE_2};
    color: {Colors.TEXT};
}}
QPushButton#Danger {{
    background-color: {Colors.SURFACE_2};
    border: 1px solid {Colors.BORDER};
    color: {Colors.RED};
}}
QPushButton#Danger:hover {{
    background-color: {Colors.SURFACE_3};
    border-color: {Colors.BORDER_HOVER};
    color: {Colors.RED};
}}
QToolButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 5px;
}}
QToolButton:hover {{
    background-color: {Colors.SURFACE_2};
    border-color: {Colors.BORDER};
}}
QToolButton:pressed {{
    background-color: {Colors.SURFACE};
}}
QToolButton:disabled {{
    background: transparent;
    border-color: transparent;
}}
QToolButton#IconButton {{
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 6px;
}}
QToolButton#IconButton:hover {{
    background-color: {Colors.SURFACE_2};
    border-color: {Colors.BORDER};
}}
QToolButton#IconButton:pressed {{
    background-color: {Colors.SURFACE};
}}
QToolButton#DangerIcon:hover {{
    background-color: {Colors.SURFACE_2};
    border-color: {Colors.BORDER};
}}
QToolButton#TransportButton {{
    background-color: {Colors.SURFACE_2};
    border: 1px solid {Colors.BORDER};
    border-radius: 10px;
    padding: 0;
}}
QToolButton#TransportButton:hover {{
    background-color: {Colors.SURFACE_3};
    border-color: {Colors.BORDER_HOVER};
}}
QToolButton#TransportButton:disabled {{
    background-color: {Colors.SURFACE};
    border-color: {Colors.BORDER};
}}
QPushButton#ViewTab {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 4px 12px;
    color: {Colors.MUTED};
    font-size: 11px;
    font-weight: 600;
}}
QPushButton#ViewTab:hover {{
    color: {Colors.TEXT};
}}
QPushButton#ViewTab:checked {{
    background-color: {Colors.SURFACE_2};
    border-color: {Colors.BORDER};
    color: {Colors.TEXT};
}}

/* ---------------------------------------------------------------- 复选框 / 滑块 / 进度 */
QCheckBox {{
    spacing: 8px;
    color: {Colors.TEXT_SOFT};
    font-size: 12px;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {Colors.BORDER};
    border-radius: 4px;
    background-color: {Colors.SURFACE};
}}
QCheckBox::indicator:hover {{
    border-color: {Colors.ACCENT};
}}
QCheckBox::indicator:checked {{
    background-color: {Colors.CHECK};
    border-color: {Colors.CHECK};
    image: url("{assets}/icons/check.svg");
}}
QSlider::groove:horizontal {{
    height: 4px;
    background-color: {Colors.BORDER};
    border-radius: 2px;
}}
QSlider::sub-page:horizontal {{
    background-color: {Colors.ACCENT};
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    width: 12px;
    height: 12px;
    margin: -4px 0;
    border-radius: 6px;
    background-color: {Colors.TEXT};
    border: 1px solid {Colors.ACCENT};
}}
QSlider::handle:horizontal:hover {{
    border-color: {Colors.ACCENT_LIGHT};
}}
QProgressBar {{
    border: none;
    border-radius: 3px;
    background-color: {Colors.BORDER};
    max-height: 6px;
    min-height: 6px;
    text-align: center;
}}
QProgressBar::chunk {{
    border-radius: 3px;
    background-color: {Colors.ACCENT};
}}

/* ---------------------------------------------------------------- 滚动区 */
QScrollArea, QScrollArea > QWidget > QWidget {{
    background: transparent;
    border: none;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 9px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {Colors.BORDER};
    min-height: 26px;
    border-radius: 4px;
}}
QScrollBar::handle:vertical:hover {{
    background: {Colors.BORDER_HOVER};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 9px;
    margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: {Colors.BORDER};
    min-width: 26px;
    border-radius: 4px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}

/* ---------------------------------------------------------------- 日志 */
QTextEdit#LogConsole {{
    background-color: {Colors.SURFACE};
    border: 1px solid {Colors.BORDER};
    border-radius: 8px;
    padding: 6px 8px;
    color: {Colors.TEXT_SOFT};
    font-family: "Consolas", "Segoe UI";
    font-size: 11px;
    selection-background-color: {Colors.BORDER_HOVER};
}}
QTextEdit#LogConsole:focus {{
    border-color: {Colors.BORDER_HOVER};
}}

/* ---------------------------------------------------------------- 菜单 / 状态栏 / 分割器 */
QMenu {{
    background-color: {Colors.SURFACE};
    border: 1px solid {Colors.BORDER};
    border-radius: 6px;
    padding: 6px;
}}
QMenu::item {{
    padding: 7px 26px 7px 12px;
    border-radius: 4px;
    color: {Colors.TEXT_SOFT};
}}
QMenu::item:selected {{
    background-color: {Colors.SURFACE_2};
    color: {Colors.TEXT};
}}
QMenu::separator {{
    height: 1px;
    background-color: {Colors.BORDER};
    margin: 5px 8px;
}}
QStatusBar {{
    background: transparent;
    color: {Colors.MUTED_DIM};
    font-size: 11px;
    border: none;
}}
QStatusBar::item {{
    border: none;
}}
QSplitter::handle {{
    background: transparent;
}}
QSplitter::handle:vertical {{
    height: 6px;
}}

/* ---------------------------------------------------------------- 滚动条内容 */
QScrollArea#RightScroll > QWidget > QWidget {{
    background: transparent;
}}
"""
