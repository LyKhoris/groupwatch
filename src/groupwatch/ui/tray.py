"""System tray icon — the always-on face of groupwatch (AGENTS.md §3.1).

Phase 0: icon, menu, placeholder window. Live status (sync %, room members)
and quick actions get wired to the engines in later phases.
"""

from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from groupwatch.config import APP_NAME
from groupwatch.platform.paths import resource_path
from groupwatch.ui.main_window import MainWindow


def run_tray_app() -> int:
    app = QApplication([])
    app.setApplicationName(APP_NAME)
    # The service lives in the tray; closing the window must never quit it.
    app.setQuitOnLastWindowClosed(False)

    icon = QIcon(str(resource_path("icon.png")))

    window = MainWindow()
    window.setWindowIcon(icon)

    tray = QSystemTrayIcon(icon, parent=app)
    tray.setToolTip(APP_NAME)

    menu = QMenu()
    open_action = QAction(f"Open {APP_NAME}", menu)
    open_action.triggered.connect(window.show)
    quit_action = QAction("Quit", menu)
    quit_action.triggered.connect(app.quit)
    menu.addAction(open_action)
    menu.addAction(quit_action)
    tray.setContextMenu(menu)

    def _on_activated(reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            window.show()
            window.raise_()
            window.activateWindow()

    tray.activated.connect(_on_activated)
    tray.show()
    return app.exec()
