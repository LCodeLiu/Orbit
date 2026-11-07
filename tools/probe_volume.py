"""开发期：验证试听条音量控件渲染与交互。"""

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

out = Path(tempfile.mkdtemp(prefix="aa_vol_"))
n = 48000
t = np.arange(n) / 48000
sig = (0.15 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
sf.write(out / "sample.wav", np.stack([sig, sig], axis=1), 48000, subtype="PCM_16")

app = QApplication(sys.argv[:1])
app.setStyle("Fusion")
app.setStyleSheet(build_stylesheet())
cfg = AppConfig(output_dir=str(out), player_volume=60)
window = MainWindow(cfg, ConfigStore(out / "config.json"))
window.resize(1440, 940)
window.show()
for _ in range(30):
    app.processEvents()
    time.sleep(0.04)

player = window.player
print("initial slider", player.volume_slider.value(), "label", player.volume_label.text())
print("audio volume", player._audio.volume())

# 模拟拖动
player.volume_slider.setValue(30)
app.processEvents()
print("after 30 ->", player.volume_label.text(), "audio", round(player._audio.volume(), 3), "cfg", window.cfg.player_volume)

# 静音
player.mute_btn.click()
app.processEvents()
print("mute -> slider", player.volume_slider.value(), "audio", player._audio.volume())

# 取消静音
player.mute_btn.click()
app.processEvents()
print("unmute -> slider", player.volume_slider.value(), "audio", round(player._audio.volume(), 3))

# 播放并截图
player.play_file(out / "sample.wav")
for _ in range(20):
    app.processEvents()
    time.sleep(0.04)
print("playing", player._media.playbackState(), "duration", player._duration)
window._update_playing_rows()
app.processEvents()

DOCS = Path(__file__).resolve().parents[1] / "docs"
player.grab().save(str(DOCS / "player_volume.png"))
print("saved", DOCS / "player_volume.png")

window._force_quit = True
window.close()
print("saved cfg", window.cfg.player_volume)
