"""生成 README 用界面截图（不参与实际录音）。"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import soundfile as sf
from PySide6.QtWidgets import QApplication

from orbit.config import AppConfig, ConfigStore
from orbit.ui.main_window import MainWindow
from orbit.ui.theme import build_stylesheet

PROJECT = Path(__file__).resolve().parents[1]
DOCS = PROJECT / "docs"
DOCS.mkdir(exist_ok=True)
out = Path(tempfile.mkdtemp(prefix="orbit_ui_"))
for i, (ext, subtype) in enumerate(
    ((".wav", "PCM_24"), (".flac", "PCM_24"), (".ogg", "VORBIS"))
):
    n = 48000
    t = np.arange(n) / 48000
    signal = (0.2 * np.sin(2 * np.pi * (440 + i * 110) * t)).astype(np.float32)
    sf.write(
        out / f"2026-10-24_09-{22 + i}-{10 + i}_耳机{ext}",
        np.stack([signal, signal * 0.7], axis=1),
        48000,
        subtype=subtype,
    )

app = QApplication(sys.argv[:1])
app.setStyle("Fusion")
app.setStyleSheet(build_stylesheet())
cfg = AppConfig(output_dir=str(out), log_visible=False)
window = MainWindow(cfg, ConfigStore(out / "config.json"))
window.resize(1440, 940)
window.show()

for _ in range(50):
    app.processEvents()
    time.sleep(0.04)

n = 2048
t = np.arange(n) / 48000
mono = (0.35 * np.sin(2 * np.pi * 440 * t) + 0.13 * np.sin(2 * np.pi * 1320 * t)).astype(np.float32)
window._on_visual(
    {"samples": mono, "peaks": [0.48, 0.34], "rms": [0.25, 0.18], "sample_rate": 48000}
)
window._last_samples = mono
window.level_meter.set_levels([0.48, 0.34], [0.25, 0.18])
window.timer_label.setText("00:12:36.4")
window._apply_state("recording", "正在采集系统音频")
window.state_label.setText("正在采集系统音频")
window.metric_size.set_value("1.42 GB")
window.metric_rate.set_value("48,000 Hz")
window.metric_buffer.set_value("960 帧 / 20 ms")
window.metric_dropped.set_value("0")
window.metric_segment.set_value("第 1 段")
window.peak_label.setText("峰值 -6.4 dBFS")
window.rms_label.setText("RMS -12.0 dBFS")
window.file_count.setText("3 个文件")
window._refresh_files()
window.spectrum.set_bands(np.linspace(0.1, 0.9, 56) * np.random.default_rng(7).random(56))
window.dir_edit.setText(r"C:\Users\Jack\Music\Orbit")
app.processEvents()
time.sleep(0.15)
app.processEvents()
window.grab().save(str(DOCS / "main.png"))
print("saved", DOCS / "main.png")

# 展开日志面板，模拟一段真实的调试输出
window.log_toggle_btn.setChecked(True)
window._toggle_log_visible()
window.detail_check.setChecked(True)
window.log_filter.setCurrentIndex(0)
window._on_log_filter()
logs = [
    ("09:32:18.042", "INFO", "Orbit 1.0.0 启动"),
    (
        "09:32:18.050",
        "INFO",
        r"配置=C:\Users\Jack\AppData\Roaming\Orbit\config.json",
    ),
    (
        "09:32:18.211",
        "DEBUG",
        "发现 2 个回环设备，PortAudio=PortAudio V19.7.0-devel",
    ),
    (
        "09:32:18.214",
        "INFO",
        r"界面初始化完成，输出目录=C:\Users\Jack\Music\Orbit",
    ),
    (
        "09:32:23.884",
        "INFO",
        "打开回环流：device=[17] 耳机 (2- Realtek(R) Audio), 48000 Hz, 2 ch, "
        "32-bit 浮点, buffer=960 frames (20.0 ms)",
    ),
    (
        "09:32:23.902",
        "INFO",
        "音频流已启动：实际 48000 Hz / 2 ch / 32-bit 浮点 / 缓冲 960 帧 / 延迟 40.0 ms",
    ),
    ("09:32:24.005", "DEBUG", "队列=0, 丢帧=0, 溢出=0, 已写入=0.00 MB"),
    ("09:32:33.908", "DEBUG", "队列峰值=3, 丢帧=0, 溢出=0, 已写入=78.9 MB"),
    ("09:32:38.416", "WARNING", "检测到一次 WASAPI 输入溢出，已计入统计"),
    (
        "09:32:43.910",
        "INFO",
        r"录音文件完成：C:\Users\Jack\Music\Orbit\2026-10-24_09-32-23_耳机.wav",
    ),
    ("09:32:43.944", "INFO", "录音结束：756.00 秒，36288000 帧，1 个文件，丢帧 0，溢出 1"),
]
for timestamp, level, message in logs:
    window._on_log(timestamp, level, message)
window.file_count.setText("3 个文件")
app.processEvents()
time.sleep(0.12)
app.processEvents()
window.grab().save(str(DOCS / "logs.png"))
print("saved", DOCS / "logs.png")

window._force_quit = True
window.close()
print("OUT", out)
