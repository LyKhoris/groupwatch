"""Locate bundled assets in both dev and frozen (PyInstaller) modes."""

import sys
from pathlib import Path


def resource_path(filename: str) -> Path:
    if getattr(sys, "frozen", False):
        # PyInstaller unpacks --add-data into sys._MEIPASS.
        return Path(sys._MEIPASS) / "assets" / filename
    # Dev mode: assets/ at the repo root.
    return Path(__file__).resolve().parents[3] / "assets" / filename
