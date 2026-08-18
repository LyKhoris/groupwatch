"""Locate bundled assets/binaries in both dev and frozen (PyInstaller) modes."""

import sys
from pathlib import Path


def _root() -> Path:
    if getattr(sys, "frozen", False):
        # PyInstaller unpacks --add-data into sys._MEIPASS.
        return Path(sys._MEIPASS)
    # Dev mode: repo root.
    return Path(__file__).resolve().parents[3]


def resource_path(filename: str) -> Path:
    return _root() / "assets" / filename


def syncthing_binary() -> Path:
    if sys.platform.startswith("win"):
        platform, name = "windows-amd64", "syncthing.exe"
    elif sys.platform.startswith("linux"):
        platform, name = "linux-amd64", "syncthing"
    else:
        raise RuntimeError(f"unsupported platform: {sys.platform}")
    return _root() / "vendor" / "syncthing" / platform / name
