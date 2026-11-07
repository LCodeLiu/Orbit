"""冒烟：空闲实时监听 + 录制红点（单次运行）。"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import sounddevice as sd
from PySide6.QtWidgets import QApplication

from orbit.config import AppConfig, ConfigStore
from orbit.ui.main_window import MainWindow
from orbit.ui.theme import build_stylesheet

import tempfile

out = Path(tempfile.mkdtemp(prefix="aa_mon_"))
app = QApplication(sys.argv[:1])
app.setStyle("Fusion")
app.setStyleSheet(build_stylesheet())
window = MainWindow(AppConfig(output_dir=str(out)), ConfigStore(out / "c.json"))
window.resize(1400, 900)
window.show()

def pump(sec: float) -> None:
    end = time.monotonic() + sec
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.02)

pump(2.5)  # 等设备扫描
print("device:", window._current_device)
print("monitor running (idle):", window._monitor.running)

# 播放测试音，监听应显示波形
fs = 48000
t = np.arange(int(fs * 6)) / fs
tone = (0.25 * np.sin(2 * np.pi * 997 * t)).astype(np.float32)
sd.play(np.stack([tone, tone * 0.6], axis=1), fs, blocking=False)
pump(1.5)
wf = window._last_samples
print("idle waveform active:", wf is not None and wf.size > 0, "peak:", float(np.max(np.abs(wf))) if wf is not None else None)
print("peak label:", window.peak_label.text())

# 开始录音：监听应停止、录音数据继续驱动波形、红点开启
window._start_recording()
pump(1.5)
print("state:", window._state, "monitor running:", window._monitor.running, "rec dot:", window.waveform._recording)
pump(1.0)
wf2 = window._last_samples
print("recording waveform:", wf2 is not None and wf2.size > 0)

window._stop_recording()
pump(2.5)
sd.stop()
print("after stop state:", window._state, "monitor running:", window._monitor.running, "rec dot:", window.waveform._recording)

# 截图：空闲监听状态
pump(1.0)
window.grab().save(str(Path(__file__).resolve().parents[1] / "docs" / "monitor_idle.png"))
window._force_quit = True
window.close()
print("OK")
