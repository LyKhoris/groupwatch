"""App identity and persisted user settings.

Settings are edited only through the GUI — users never touch files by hand
(AGENTS.md §2). This module is the tiny JSON store behind that.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

APP_NAME = "groupwatch"


def config_dir() -> Path:
    """Per-user config directory (%APPDATA% on Windows, XDG config on Linux)."""
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / APP_NAME


DEFAULT_SETTINGS = {
    "role": None,          # None until first-run wizard: "leader" | "friend"
    "display_name": "",    # shown to the group ("Waiting for Sam (60%)…")
    "library_path": "",    # where the synced video folder lives
    "server_host": "",     # empty = leader hosts the syncplay server (default)
    "server_port": 8999,
    "room": "groupwatch",  # single fixed room per group (AGENTS.md §3.3)
    "autostart": True,     # §3.7: ON by default
}


class Settings:
    """Tiny JSON-backed settings store. The UI (Phase 3) writes; engines read."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._data = dict(DEFAULT_SETTINGS)
        if self.path.exists():
            self._data.update(json.loads(self.path.read_text(encoding="utf-8")))

    @classmethod
    def load(cls) -> "Settings":
        return cls(config_dir() / "settings.json")

    def get(self, key, default=None):
        return self._data.get(key, default)

    def set(self, key, value) -> None:
        self._data[key] = value
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
