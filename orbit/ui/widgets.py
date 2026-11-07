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

"""自绘控件与可复用 UI 组件。"""

from __future__ import annotations

import html
import time
from pathlib import Path

import numpy as np
from PySide6.QtCore import (
    QPointF,
    QRectF,
    QSize,
    Qt,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
)
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QAbstractButton,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QSlider,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from orbit.audio.analysis import amplitude_to_db, amplitude_to_meter
from orbit.ui.theme import Colors, app_icon, icon


def hline() -> QFrame:
    line = QFrame()
    line.setObjectName("Divider")
    line.setFrameShape(QFrame.Shape.NoFrame)
    line.setFixedHeight(1)
    return line


class LogoWidget(QWidget):
    def __init__(self, size: int = 42, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._size = size
        self.setFixedSize(size, size)
        self._pix = app_icon().pixmap(size, size)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def paintEvent(self, event) -> None:  # noqa: ANN001
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self._pix.isNull():
            p.drawPixmap(0, 0, self._pix)
        else:
            p.setBrush(QColor(Colors.ACCENT))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(self.rect(), 12, 12)


class SectionHeader(QWidget):
    """卡片标题：图标 + 标题/副标题 + 右侧操作区。"""

    def __init__(
        self,
        title: str,
        subtitle: str = "",
        icon_name: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        if icon_name:
            badge = QLabel()
            badge.setObjectName("IconBadge")
            badge.setFixedSize(28, 28)
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge.setPixmap(icon(icon_name).pixmap(15, 15))
            layout.addWidget(badge)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(1)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("SectionTitle")
        text_layout.addWidget(self.title_label)
        if subtitle:
            subtitle_label = QLabel(subtitle)
            subtitle_label.setObjectName("Tiny")
            text_layout.addWidget(subtitle_label)
        layout.addLayout(text_layout)
        layout.addStretch(1)

        self.actions = QHBoxLayout()
        self.actions.setContentsMargins(0, 0, 0, 0)
        self.actions.setSpacing(4)
        layout.addLayout(self.actions)

    def add_action(self, widget: QWidget) -> None:
        self.actions.addWidget(widget)


class ElidedLabel(QLabel):
    """按宽度省略文本，避免长路径撑破布局。"""

    def __init__(self, text: str = "", mode=Qt.TextElideMode.ElideMiddle, parent=None) -> None:
        super().__init__(text, parent)
        self._mode = mode
        self._full_text = text
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setToolTip(text)

    def setText(self, text: str) -> None:  # noqa: N802
        self._full_text = text
        self.setToolTip(text)
        super().setText(text)
        self.update()

    def fullText(self) -> str:  # noqa: N802
        return self._full_text

    def paintEvent(self, event) -> None:  # noqa: ANN001
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        color = self.palette().color(QPalette.ColorRole.WindowText)
        painter.setPen(color)
        painter.setFont(self.font())
        text = QFontMetrics(self.font()).elidedText(
            self._full_text, self._mode, max(10, self.width())
        )
        painter.drawText(self.rect(), int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), text)
        painter.end()


class StatusPill(QWidget):
    def __init__(self, text: str = "就绪", color: str = Colors.GREEN, parent=None) -> None:
        super().__init__(parent)
        self._text = text
        self._color = QColor(color)
        self.setFixedHeight(28)
        self.setMinimumWidth(96)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def set_status(self, text: str, color: str, pulse: bool = False) -> None:
        self._text = text
        self._color = QColor(color)
        self.updateGeometry()
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802
        fm = QFontMetrics(self.font())
        return QSize(max(96, fm.horizontalAdvance(self._text) + 36), 28)

    def paintEvent(self, event) -> None:  # noqa: ANN001
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        bg = QColor(self._color)
        bg.setAlpha(26)
        border = QColor(self._color)
        border.setAlpha(72)
        p.setPen(QPen(border, 1))
        p.setBrush(bg)
        p.drawRoundedRect(rect, 14, 14)

        dot = QColor(self._color)
        dot.setAlpha(220)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(dot)
        p.drawEllipse(QPointF(14, self.height() / 2), 3, 3)

        font = QFont(self.font())
        font.setPointSizeF(9.0)
        font.setWeight(QFont.Weight.DemiBold)
        p.setFont(font)
        p.setPen(QColor(Colors.TEXT_SOFT))
        p.drawText(
            QRectF(22, 0, self.width() - 28, self.height()),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            self._text,
        )


class LevelMeter(QWidget):
    """双声道峰值表，带 RMS 阴影与峰值保持。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(58)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._target = [0.0, 0.0]
        self._display = [0.0, 0.0]
        self._hold = [0.0, 0.0]
        self._hold_time = [0.0, 0.0]
        self._db = [-120.0, -120.0]
        self._last_update = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._animate)
        self._timer.start()

    def set_levels(self, peaks: list[float], rms: list[float] | None = None) -> None:
        self._last_update = time.monotonic()
        for i in range(2):
            peak = peaks[i] if i < len(peaks) else 0.0
            level = amplitude_to_meter(float(peak))
            self._target[i] = level
            self._db[i] = amplitude_to_db(float(peak))
            if level >= self._hold[i]:
                self._hold[i] = level
                self._hold_time[i] = self._last_update
        self.update()

    def reset(self) -> None:
        self._target = [0.0, 0.0]
        self._display = [0.0, 0.0]
        self._hold = [0.0, 0.0]
        self._db = [-120.0, -120.0]
        self.update()

    def _animate(self) -> None:
        now = time.monotonic()
        changed = False
        for i in range(2):
            if now - self._last_update > 0.5:
                self._target[i] *= 0.86
                if self._target[i] < 0.002:
                    self._target[i] = 0.0
                    self._db[i] = -120.0
            new = self._display[i] + (self._target[i] - self._display[i]) * 0.34
            if abs(new - self._display[i]) > 0.0005:
                self._display[i] = new
                changed = True
            if now - self._hold_time[i] > 1.2 and self._hold[i] > 0:
                self._hold[i] = max(self._display[i], self._hold[i] - 0.018)
                changed = True
        if changed:
            self.update()

    def paintEvent(self, event) -> None:  # noqa: ANN001
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = self.width()
        label_w = 16
        db_w = 52
        track_x = label_w
        track_w = max(20, width - label_w - db_w - 8)
        row_h = 14
        gap = 12
        top = max(2, (self.height() - (row_h * 2 + gap)) // 2)

        font = QFont(self.font())
        font.setPointSizeF(8.2)
        font.setWeight(QFont.Weight.DemiBold)
        p.setFont(font)
        for idx, label in enumerate(("L", "R")):
            y = top + idx * (row_h + gap)
            p.setPen(QColor(Colors.MUTED))
            p.drawText(
                QRectF(0, y - 2, label_w - 4, row_h + 4),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                label,
            )
            track = QRectF(track_x, y, track_w, row_h)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#131C2E"))
            p.drawRoundedRect(track, 4, 4)

            # 基准刻度
            p.setPen(QPen(QColor(255, 255, 255, 14), 1))
            for tick in (0.25, 0.5, 0.75):
                x = track_x + track_w * tick
                p.drawLine(QPointF(x, y + 2), QPointF(x, y + row_h - 2))

            value = max(0.0, min(1.0, self._display[idx]))
            if value > 0.001:
                fill = QRectF(track_x, y, track_w * value, row_h)
                grad = QLinearGradient(track_x, 0, track_x + track_w, 0)
                grad.setColorAt(0.0, QColor(Colors.ACCENT))
                grad.setColorAt(0.78, QColor(Colors.AMBER))
                grad.setColorAt(1.0, QColor(Colors.RED))
                p.setBrush(grad)
                p.setPen(Qt.PenStyle.NoPen)
                p.drawRoundedRect(fill, 4, 4)
                # 高光
                hi = QColor(255, 255, 255, 34)
                p.setBrush(hi)
                p.drawRoundedRect(
                    QRectF(fill.x(), fill.y() + 1, fill.width(), max(2, fill.height() * 0.35)),
                    3,
                    3,
                )
            hold = self._hold[idx]
            if hold > 0.01:
                hx = track_x + track_w * min(1.0, hold)
                p.setPen(QPen(QColor("#F7FAFF"), 1.4))
                p.drawLine(QPointF(hx, y - 1), QPointF(hx, y + row_h + 1))
            db = self._db[idx]
            text = "-∞ dB" if db <= -119 else f"{db:5.1f} dB"
            p.setPen(QColor(Colors.MUTED_DIM if db <= -60 else Colors.TEXT_SOFT))
            p.drawText(
                QRectF(width - db_w, y - 1, db_w, row_h + 2),
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                text,
            )
        p.end()


def _draw_rec_badge(p: QPainter, width: float, pulse_start: float) -> None:
    """在绘制区右上角画呼吸红点 + REC，供波形与频谱共用。

    透明度与半径由正弦相位驱动；是否录制由调用方判断，
    调用方需在录制期间以约 25fps 触发重绘。
    """
    phase = (time.monotonic() - pulse_start) * 2.2
    wave = 0.5 + 0.5 * float(np.sin(phase))  # 0..1
    radius = 3.6 + 1.6 * wave
    cx, cy = width - 16.0, 13.0
    halo = QColor(Colors.RED)
    halo.setAlpha(int(38 + 52 * wave))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(halo)
    p.drawEllipse(QPointF(cx, cy), radius + 4.2, radius + 4.2)
    core = QColor(Colors.RED)
    core.setAlpha(int(150 + 105 * wave))
    p.setBrush(core)
    p.drawEllipse(QPointF(cx, cy), radius, radius)
    label_font = QFont("Segoe UI", 8)
    label_font.setWeight(QFont.Weight.DemiBold)
    p.setFont(label_font)
    text_color = QColor(Colors.RED)
    text_color.setAlpha(int(160 + 95 * wave))
    p.setPen(text_color)
    p.drawText(
        QRectF(cx - 66, cy - 9, 52, 18),
        int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        "REC",
    )


class WaveformView(QWidget):
    """实时示波器式波形。

    右上角有录制指示红点：呼吸效果由 paintEvent 内的正弦相位驱动，
    由 _pulse_timer 以约 25fps 重绘，仅在录制时运行，空闲零开销。
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(150)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._samples = np.zeros(0, dtype=np.float32)
        self._last_time = 0.0
        self._active = False
        self._recording = False
        self._pulse_start = time.monotonic()
        self._idle_timer = QTimer(self)
        self._idle_timer.setInterval(250)
        self._idle_timer.timeout.connect(self._check_idle)
        self._idle_timer.start()
        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(40)
        self._pulse_timer.timeout.connect(self.update)

    def set_recording(self, recording: bool) -> None:
        """录制中显示呼吸红点；停止后隐藏并停掉重绘定时器。"""
        if self._recording == recording:
            return
        self._recording = recording
        if recording:
            self._pulse_start = time.monotonic()
            self._pulse_timer.start()
        else:
            self._pulse_timer.stop()
        self.update()

    def set_samples(self, samples: np.ndarray) -> None:
        if samples is not None and samples.size:
            self._samples = np.asarray(samples, dtype=np.float32)[-4096:].copy()
            self._last_time = time.monotonic()
            self._active = True
        self.update()

    def clear(self) -> None:
        self._samples = np.zeros(0, dtype=np.float32)
        self._active = False
        self.update()

    def _check_idle(self) -> None:
        if self._active and time.monotonic() - self._last_time > 1.5:
            self._active = False
            self.update()

    def paintEvent(self, event) -> None:  # noqa: ANN001
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        h = self.height()
        rect = QRectF(0, 0, w, h)
        p.fillRect(rect, QColor("#0A101B"))

        # 网格
        p.setPen(QPen(QColor(255, 255, 255, 12), 1))
        for i in range(1, 8):
            x = w * i / 8
            p.drawLine(QPointF(x, 0), QPointF(x, h))
        for i in range(1, 4):
            y = h * i / 4
            p.drawLine(QPointF(0, y), QPointF(w, y))
        p.setPen(QPen(QColor(255, 255, 255, 28), 1))
        p.drawLine(QPointF(0, h / 2), QPointF(w, h / 2))

        # 左上角标签
        p.setFont(QFont("Segoe UI", 8))
        p.setPen(QColor(Colors.MUTED_DIM))
        p.drawText(QRectF(8, 4, 120, 18), int(Qt.AlignmentFlag.AlignLeft), "实时波形")
        p.drawText(
            QRectF(w - 190, 4, 102, 18),
            int(Qt.AlignmentFlag.AlignRight),
            "自动增益显示",
        )

        # 右上角录制指示：呼吸红点（透明度+半径随正弦变化）
        if self._recording:
            _draw_rec_badge(p, w, self._pulse_start)

        if not self._active or self._samples.size < 8:
            p.setPen(QColor(Colors.MUTED_DIM))
            p.setFont(QFont("Segoe UI", 10))
            p.drawText(
                rect,
                int(Qt.AlignmentFlag.AlignCenter),
                "等待音频信号" if not self._active else "",
            )
            p.end()
            return

        samples = self._samples
        peak = float(np.max(np.abs(samples)))
        gain = 1.0 if peak < 1e-5 else min(7.0, 0.84 / peak)
        # 抽稀到屏幕宽度附近，保持绘制性能
        stride = max(1, samples.size // max(300, w * 2))
        data = samples[::stride]
        if data.size < 2:
            p.end()
            return
        center = h / 2 + 4
        amp = h * 0.38
        points = data.size
        step = w / max(1, points - 1)

        path = QPainterPath()
        for i, value in enumerate(data):
            x = i * step
            y = center - float(value) * gain * amp
            if i == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
        path.lineTo(w, center)
        path.lineTo(0, center)
        path.closeSubpath()

        fill = QLinearGradient(0, 0, 0, h)
        fill.setColorAt(0.0, QColor(136, 136, 136, 28))
        fill.setColorAt(0.42, QColor(136, 136, 136, 90))
        fill.setColorAt(0.5, QColor(170, 170, 170, 120))
        fill.setColorAt(0.58, QColor(136, 136, 136, 90))
        fill.setColorAt(1.0, QColor(136, 136, 136, 28))
        p.setBrush(fill)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPath(path)

        stroke = QLinearGradient(0, 0, w, 0)
        stroke.setColorAt(0.0, QColor(170, 170, 170))
        stroke.setColorAt(0.5, QColor(136, 136, 136))
        stroke.setColorAt(1.0, QColor(170, 170, 170))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(stroke, 1.25))
        p.drawPath(path)

        # 播放头小圆点
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 180))
        p.drawEllipse(QPointF(w - 1, center), 2.1, 2.1)
        p.end()


class SpectrumView(QWidget):
    """对数频段频谱柱。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(150)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._bands = np.zeros(56, dtype=np.float32)
        self._peaks = np.zeros(56, dtype=np.float32)
        self._active = False
        self._recording = False
        self._pulse_start = time.monotonic()
        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(40)
        self._pulse_timer.timeout.connect(self.update)

    def set_recording(self, recording: bool) -> None:
        """录制中显示与波形一致的呼吸红点；停止后停止重绘定时器。"""
        if self._recording == recording:
            return
        self._recording = recording
        if recording:
            self._pulse_start = time.monotonic()
            self._pulse_timer.start()
        else:
            self._pulse_timer.stop()
        self.update()

    def set_bands(self, bands: np.ndarray) -> None:
        if bands is None:
            return
        values = np.asarray(bands, dtype=np.float32)
        if values.size != self._bands.size:
            self._bands = np.zeros(values.size, dtype=np.float32)
            self._peaks = np.zeros(values.size, dtype=np.float32)
        self._bands = np.maximum(values, self._bands * 0.72)
        self._peaks = np.maximum(self._bands, self._peaks * 0.92)
        self._active = bool(np.max(values) > 0.002)
        self.update()

    def clear(self) -> None:
        self._bands[:] = 0
        self._peaks[:] = 0
        self._active = False
        self.update()

    def paintEvent(self, event) -> None:  # noqa: ANN001
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        h = self.height()
        p.fillRect(QRectF(0, 0, w, h), QColor("#0A101B"))

        p.setFont(QFont("Segoe UI", 8))
        p.setPen(QPen(QColor(255, 255, 255, 11), 1))
        for i in range(1, 5):
            y = h * i / 5
            p.drawLine(QPointF(0, y), QPointF(w, y))
        p.setPen(QColor(Colors.MUTED_DIM))
        p.drawText(QRectF(8, 4, 150, 18), int(Qt.AlignmentFlag.AlignLeft), "频谱 · 20 Hz – 20 kHz")
        if self._recording:
            _draw_rec_badge(p, w, self._pulse_start)

        bottom = h - 24
        top = 24
        left = 8
        right = 8
        usable = w - left - right
        count = self._bands.size
        gap = max(1.5, usable / count * 0.28)
        bar_w = max(1.4, (usable - gap * (count - 1)) / count)

        # 频率刻度
        tick_values = (50, 100, 250, 500, 1000, 2000, 4000, 8000, 16000)
        for freq in tick_values:
            pos = np.log(max(freq, 35) / 35) / np.log(20000 / 35)
            x = left + usable * float(min(1.0, max(0.0, pos)))
            p.setPen(QPen(QColor(255, 255, 255, 16), 1))
            p.drawLine(QPointF(x, top), QPointF(x, bottom))
            label = f"{freq // 1000}k" if freq >= 1000 else str(freq)
            p.setPen(QColor(Colors.MUTED_DIM))
            p.drawText(
                QRectF(x - 18, bottom + 4, 36, 15),
                int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop),
                label,
            )

        for i in range(count):
            value = float(max(0.0, min(1.0, self._bands[i])))
            x = left + i * (bar_w + gap)
            bar_h = max(1.0, (bottom - top) * value)
            y = bottom - bar_h
            grad = QLinearGradient(0, bottom, 0, top)
            grad.setColorAt(0.0, QColor(136, 136, 136, 210))
            grad.setColorAt(0.55, QColor(136, 136, 136, 220))
            grad.setColorAt(1.0, QColor(170, 170, 170, 230))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(grad)
            p.drawRoundedRect(QRectF(x, y, bar_w, bar_h), min(2.0, bar_w / 2), min(2.0, bar_w / 2))

            peak = float(self._peaks[i])
            if peak > 0.01:
                py = bottom - (bottom - top) * peak
                p.setBrush(QColor(255, 255, 255, 180))
                p.drawRoundedRect(QRectF(x, max(top, py - 1), bar_w, 1.6), 0.8, 0.8)

        if not self._active:
            p.setPen(QColor(Colors.MUTED_DIM))
            p.setFont(QFont("Segoe UI", 10))
            p.drawText(
                QRectF(0, 0, w, h - 20),
                int(Qt.AlignmentFlag.AlignCenter),
                "等待音频信号",
            )
        p.end()


class RecordButton(QAbstractButton):
    """开始录音按钮。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(56, 56)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("开始录音（F9）")
        self._hover = False
        self._pressed = False
        self._recording = False

    def set_recording(self, recording: bool) -> None:
        if self._recording == recording:
            return
        self._recording = recording
        self.update()

    def enterEvent(self, event) -> None:  # noqa: ANN001
        self._hover = True
        self.update()

    def leaveEvent(self, event) -> None:  # noqa: ANN001
        self._hover = False
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: ANN001
        self._pressed = True
        self.update()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: ANN001
        self._pressed = False
        self.update()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:  # noqa: ANN001
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx, cy = self.width() / 2, self.height() / 2

        # 外圆背景
        if self._recording:
            outer_color = Colors.RED
            fill = Colors.RED
        elif self._hover:
            outer_color = Colors.BORDER_HOVER
            fill = Colors.SURFACE_3
        else:
            outer_color = Colors.BORDER_HOVER
            fill = Colors.SURFACE_2

        p.setPen(QPen(QColor(outer_color), 1.5))
        p.setBrush(QColor(fill if not self._pressed else Colors.SURFACE))
        p.drawEllipse(QPointF(cx, cy), 25, 25)

        # 中心图标：录制中为白色方块（停止），空闲为红色圆点（开始）
        p.setPen(Qt.PenStyle.NoPen)
        if self._recording:
            p.setBrush(QColor("#FFFFFF"))
            size = 12
            p.drawRoundedRect(QRectF(cx - size / 2, cy - size / 2, size, size), 2, 2)
        else:
            p.setBrush(QColor(Colors.RED))
            p.drawEllipse(QPointF(cx, cy), 9, 9)

        p.end()


class StatChip(QFrame):
    def __init__(self, label: str, value: str = "—", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Chip")
        self.setFixedHeight(27)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(9, 0, 10, 0)
        layout.setSpacing(6)
        self.key_label = QLabel(label)
        self.key_label.setObjectName("Tiny")
        self.value_label = QLabel(value)
        self.value_label.setStyleSheet(
            f"color: {Colors.TEXT_SOFT}; font-size: 11px; font-weight: 600;"
        )
        layout.addWidget(self.key_label)
        layout.addWidget(self.value_label)

    def set_value(self, value: str) -> None:
        self.value_label.setText(value)


class InlineAlert(QFrame):
    dismissed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Alert")
        self.setVisible(False)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 11, 10, 11)
        layout.setSpacing(12)

        mark = QLabel("!")
        mark.setFixedSize(24, 24)
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setStyleSheet(
            f"background: {Colors.RED}; color: white; border-radius: 12px;"
            "font-weight: 800; font-size: 13px;"
        )
        layout.addWidget(mark, 0, Qt.AlignmentFlag.AlignTop)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(2)
        self.title_label = QLabel()
        self.title_label.setStyleSheet(
            "color: #FFD8DF; font-size: 12px; font-weight: 700;"
        )
        self.detail_label = QLabel()
        self.detail_label.setObjectName("Muted")
        self.detail_label.setWordWrap(True)
        text_layout.addWidget(self.title_label)
        text_layout.addWidget(self.detail_label)
        layout.addLayout(text_layout, 1)

        close = QToolButton()
        close.setIcon(icon("close"))
        close.setIconSize(QSize(14, 14))
        close.setFixedSize(26, 26)
        close.setToolTip("关闭提示")
        close.clicked.connect(self.dismiss)
        layout.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.dismiss)

    def show_alert(self, title: str, detail: str = "", timeout_ms: int = 12000) -> None:
        self.title_label.setText(title)
        self.detail_label.setText(detail)
        self.detail_label.setVisible(bool(detail))
        self.setVisible(True)
        if timeout_ms > 0:
            self._timer.start(timeout_ms)

    def dismiss(self) -> None:
        self._timer.stop()
        self.setVisible(False)
        self.dismissed.emit()


class PlayerBar(QWidget):
    """轻量试听条（QtMultimedia），带音量调节。"""

    error = Signal(str)
    playing_changed = Signal(str, bool)
    open_external = Signal(str)
    volume_changed = Signal(int)  # 0-100，用于持久化

    def __init__(self, parent=None, volume: int = 85) -> None:
        super().__init__(parent)
        self.setObjectName("PlayerBar")
        self._path = ""
        self._duration = 0
        self._dragging = False
        self._last_volume = max(1, min(100, int(volume)))

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 5, 8, 5)
        layout.setSpacing(8)

        self.play_btn = QToolButton()
        self.play_btn.setObjectName("IconButton")
        self.play_btn.setIcon(icon("play"))
        self.play_btn.setIconSize(QSize(15, 15))
        self.play_btn.setFixedSize(30, 30)
        self.play_btn.setToolTip("播放 / 暂停")
        self.play_btn.clicked.connect(self.toggle)
        layout.addWidget(self.play_btn)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(1)
        self.title_label = ElidedLabel("选择录音文件试听", Qt.TextElideMode.ElideMiddle)
        self.title_label.setStyleSheet(f"color: {Colors.TEXT_SOFT}; font-size: 11px;")
        self.time_label = QLabel("00:00 / 00:00")
        self.time_label.setObjectName("Mono")
        text_layout.addWidget(self.title_label)
        text_layout.addWidget(self.time_label)
        layout.addLayout(text_layout, 2)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 0)
        self.slider.setFixedHeight(18)
        self.slider.sliderPressed.connect(self._slider_pressed)
        self.slider.sliderReleased.connect(self._slider_released)
        self.slider.sliderMoved.connect(self._slider_moved)
        layout.addWidget(self.slider, 3)

        self.external_btn = QToolButton()
        self.external_btn.setObjectName("IconButton")
        self.external_btn.setIcon(icon("external"))
        self.external_btn.setIconSize(QSize(14, 14))
        self.external_btn.setFixedSize(28, 28)
        self.external_btn.setToolTip("用系统播放器打开")
        self.external_btn.clicked.connect(self._external)
        self.external_btn.setEnabled(False)
        layout.addWidget(self.external_btn)

        # ---- 音量控制：静音按钮 + 滑块 + 百分比 ----
        self.mute_btn = QToolButton()
        self.mute_btn.setObjectName("IconButton")
        self.mute_btn.setIcon(icon("volume"))
        self.mute_btn.setIconSize(QSize(15, 15))
        self.mute_btn.setFixedSize(28, 28)
        self.mute_btn.setToolTip("静音 / 取消静音")
        self.mute_btn.clicked.connect(self._toggle_mute)
        layout.addWidget(self.mute_btn)

        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(max(0, min(100, int(volume))))
        self.volume_slider.setFixedWidth(84)
        self.volume_slider.setFixedHeight(18)
        self.volume_slider.setToolTip("试听音量")
        self.volume_slider.valueChanged.connect(self._on_volume_changed)
        layout.addWidget(self.volume_slider)

        self.volume_label = QLabel(f"{self.volume_slider.value()}%")
        self.volume_label.setObjectName("Mono")
        self.volume_label.setFixedWidth(34)
        self.volume_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        layout.addWidget(self.volume_label)

        self._media = QMediaPlayer(self)
        self._audio = QAudioOutput(self)
        self._audio.setVolume(self.volume_slider.value() / 100.0)
        self._media.setAudioOutput(self._audio)
        self._media.playbackStateChanged.connect(self._on_state)
        self._media.positionChanged.connect(self._on_position)
        self._media.durationChanged.connect(self._on_duration)
        self._media.errorOccurred.connect(self._on_error)
        self._media.mediaStatusChanged.connect(self._on_status)

    @property
    def path(self) -> str:
        return self._path

    def play_file(self, path: str | Path) -> None:
        path = str(path)
        if self._path == path and self._media.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._media.pause()
            return
        self._path = path
        self._media.stop()
        self._media.setSource(QUrl.fromLocalFile(path))
        self.title_label.setText(Path(path).name)
        self.external_btn.setEnabled(True)
        self._media.play()

    def toggle(self) -> None:
        if not self._path:
            return
        if self._media.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._media.pause()
        else:
            if self._media.source().isEmpty():
                self._media.setSource(QUrl.fromLocalFile(self._path))
            self._media.play()

    def stop(self) -> None:
        self._media.stop()
        self._media.setSource(QUrl())
        self._path = ""
        self._duration = 0
        self.title_label.setText("选择录音文件试听")
        self.time_label.setText("00:00 / 00:00")
        self.slider.setRange(0, 0)
        self.play_btn.setIcon(icon("play"))
        self.external_btn.setEnabled(False)

    def _external(self) -> None:
        if self._path:
            self.open_external.emit(self._path)

    # ------------------------------------------------------------- 音量
    def _on_volume_changed(self, value: int) -> None:
        self._audio.setVolume(value / 100.0)
        self.volume_label.setText(f"{value}%")
        # 拖动到非 0 时视为取消静音
        if value > 0:
            self._last_volume = value
        self._update_mute_icon(value)
        self.volume_changed.emit(value)

    def _toggle_mute(self) -> None:
        current = self.volume_slider.value()
        if current > 0:
            self._last_volume = current
            self.volume_slider.setValue(0)
        else:
            self.volume_slider.setValue(self._last_volume or 85)

    def _update_mute_icon(self, value: int) -> None:
        self.mute_btn.setIcon(icon("volume-mute" if value == 0 else "volume"))
        self.mute_btn.setToolTip(
            "取消静音" if value == 0 else "静音"
        )

    def _on_state(self, state) -> None:  # noqa: ANN001
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self.play_btn.setIcon(icon("pause" if playing else "play"))
        self.playing_changed.emit(self._path, playing)

    def _on_position(self, position: int) -> None:
        if not self._dragging:
            self.slider.setValue(position)
        self.time_label.setText(
            f"{self._fmt(position / 1000)} / {self._fmt(self._duration / 1000)}"
        )

    def _on_duration(self, duration: int) -> None:
        self._duration = duration
        self.slider.setRange(0, max(0, duration))
        self.time_label.setText(
            f"00:00 / {self._fmt(duration / 1000)}"
        )

    def _on_error(self, error, error_string: str) -> None:  # noqa: ANN001
        self.error.emit(error_string or "无法播放该文件")
        self.play_btn.setIcon(icon("play"))

    def _on_status(self, status) -> None:  # noqa: ANN001
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.play_btn.setIcon(icon("play"))
            self.playing_changed.emit(self._path, False)

    def _slider_pressed(self) -> None:
        self._dragging = True

    def _slider_released(self) -> None:
        self._dragging = False
        self._media.setPosition(self.slider.value())

    def _slider_moved(self, value: int) -> None:
        self.time_label.setText(
            f"{self._fmt(value / 1000)} / {self._fmt(self._duration / 1000)}"
        )

    @staticmethod
    def _fmt(seconds: float) -> str:
        seconds = max(0, int(seconds))
        minutes, secs = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours}:{minutes:02d}:{secs:02d}"
        return f"{minutes:02d}:{secs:02d}"


class LogConsole(QTextEdit):
    COLORS = {
        "DEBUG": "#6E7D96",
        "INFO": "#9AABC5",
        "WARNING": "#FFB454",
        "ERROR": "#FF6B86",
        "CRITICAL": "#FF6B86",
    }

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("LogConsole")
        self.setReadOnly(True)
        self.setAcceptRichText(True)
        self.document().setMaximumBlockCount(1500)
        self._min_level = 20

    def set_min_level(self, level: int) -> None:
        self._min_level = level

    def append_record(self, timestamp: str, level: str, message: str) -> None:
        level_no = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}.get(
            level, 20
        )
        if level_no < self._min_level:
            return
        bar = self.verticalScrollBar()
        at_bottom = bar.value() >= bar.maximum() - 6
        color = self.COLORS.get(level, Colors.TEXT_SOFT)
        safe = html.escape(message).replace("\n", "<br>")
        label = {"WARNING": "WARN", "CRITICAL": "CRIT"}.get(level, level)
        label = label.ljust(5).replace(" ", "&#160;")
        self.append(
            f'<span style="color:#4E5B72">{html.escape(timestamp)}</span>'
            f'&nbsp;&nbsp;<span style="color:{color}; font-weight:600">{label}</span>'
            f'&nbsp;<span style="color:{color}">{safe}</span>'
        )
        if at_bottom:
            bar.setValue(bar.maximum())


class FileRow(QFrame):
    play_requested = Signal(str)
    reveal_requested = Signal(str)
    delete_requested = Signal(str)

    BADGE_COLORS = {
        "wav": ("#1B3A55", "#67D2FF"),
        "flac": ("#123B36", "#54E3BD"),
        "m4a": ("#2B244B", "#AA9BFF"),
        "mp3": ("#3A2B16", "#FFC168"),
        "aac": ("#2B244B", "#AA9BFF"),
        "ogg": ("#21351E", "#9CE07A"),
    }

    def __init__(self, path: Path, size_text: str, date_text: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("FileRow")
        self.setProperty("playing", "false")
        self.path = path
        self.setFixedHeight(54)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        ext = path.suffix.lower().lstrip(".")
        badge_bg, badge_fg = self.BADGE_COLORS.get(ext, ("#263247", "#B8C2D8"))
        layout = QHBoxLayout(self)
        layout.setContentsMargins(9, 6, 8, 6)
        layout.setSpacing(10)

        badge = QLabel(ext.upper() or "AUDIO")
        badge.setFixedSize(42, 26)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet(
            f"background:{badge_bg}; color:{badge_fg}; border-radius:6px;"
            "font-size:9px; font-weight:700;"
        )
        layout.addWidget(badge)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(1)
        self.name_label = ElidedLabel(path.name, Qt.TextElideMode.ElideMiddle)
        self.name_label.setStyleSheet(
            f"color:{Colors.TEXT_SOFT}; font-size:12px; font-weight:600;"
        )
        meta = QLabel(f"{size_text}   ·   {date_text}")
        meta.setObjectName("Tiny")
        text_layout.addWidget(self.name_label)
        text_layout.addWidget(meta)
        layout.addLayout(text_layout, 1)

        self.play_btn = self._button("play", "试听")
        self.play_btn.clicked.connect(lambda: self.play_requested.emit(str(self.path)))
        self.reveal_btn = self._button("folder", "在资源管理器中显示")
        self.reveal_btn.clicked.connect(lambda: self.reveal_requested.emit(str(self.path)))
        self.delete_btn = self._button("trash", "删除（移至回收站）", danger=True)
        self.delete_btn.clicked.connect(lambda: self.delete_requested.emit(str(self.path)))
        layout.addWidget(self.play_btn)
        layout.addWidget(self.reveal_btn)
        layout.addWidget(self.delete_btn)

    @staticmethod
    def _button(icon_name: str, tooltip: str, danger: bool = False) -> QToolButton:
        button = QToolButton()
        button.setObjectName("DangerIcon" if danger else "IconButton")
        button.setIcon(icon(icon_name))
        button.setIconSize(QSize(14, 14))
        button.setFixedSize(28, 28)
        button.setToolTip(tooltip)
        return button

    def set_playing(self, playing: bool) -> None:
        self.setProperty("playing", "true" if playing else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: ANN001
        self.play_requested.emit(str(self.path))
        super().mouseDoubleClickEvent(event)
