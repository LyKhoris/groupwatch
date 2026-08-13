"""Popup window.

Phase 0: placeholder. Phase 3 grows this into the library list, people panel,
invite generation, and settings (AGENTS.md §3.1).
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QMainWindow

from groupwatch import __version__
from groupwatch.config import APP_NAME


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(480, 320)

        body = QLabel(
            f"<h2>{APP_NAME} v{__version__}</h2>"
            "<p>The background service is running in your system tray.</p>"
            "<p>Phase 0 scaffold — syncing, playback, and invites arrive "
            "in the next phases.</p>"
        )
        body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body.setTextFormat(Qt.TextFormat.RichText)
        self.setCentralWidget(body)
