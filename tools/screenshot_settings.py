"""开发期：设置对话框截图。"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from orbit.config import AppConfig
from orbit.ui.settings import DiagnosticsDialog, SettingsDialog
from orbit.ui.theme import build_stylesheet

DOCS = Path(__file__).resolve().parents[1] / "docs"
DOCS.mkdir(exist_ok=True)
app = QApplication(sys.argv[:1])
app.setStyle("Fusion")
app.setStyleSheet(build_stylesheet())
cfg = AppConfig(log_visible=True)
dialog = SettingsDialog(cfg, True)
dialog.show()
app.processEvents()
dialog.grab().save(str(DOCS / "settings.png"))
print("settings saved")
dialog.tabs.setCurrentIndex(2)
app.processEvents()
dialog.grab().save(str(DOCS / "settings_system.png"))
print("settings system saved")
diag = DiagnosticsDialog()
diag.show()
app.processEvents()
diag.grab().save(str(DOCS / "diagnostics.png"))
print("diagnostics saved")
diag.close()
dialog.close()
