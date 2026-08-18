"""Manage the bundled Syncthing process (AGENTS.md §3.2).

groupwatch owns Syncthing's entire lifecycle: it generates the config on first
run, launches the stock binary hidden (no browser UI), and supervises it.
"""

from __future__ import annotations

import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

from groupwatch.sync.api import SyncthingAPI, wait_for_api

# Not Syncthing's default 8384 — avoids clashing if a user happens to run
# their own Syncthing install on the same machine.
DEFAULT_GUI_PORT = 18384


class SyncthingEngine:
    """Owns the bundled syncthing process and its localhost REST API."""

    def __init__(self, binary: Path, home: Path, gui_port: int = DEFAULT_GUI_PORT):
        self.binary = Path(binary)
        self.home = Path(home)
        self.gui_port = gui_port
        self._proc: subprocess.Popen | None = None

    @property
    def config_xml(self) -> Path:
        return self.home / "config.xml"

    @property
    def api_key(self) -> str:
        key = ET.parse(self.config_xml).getroot().findtext("gui/apikey")
        if not key:
            raise RuntimeError("syncthing config has no API key")
        return key

    @property
    def api(self) -> SyncthingAPI:
        return SyncthingAPI(f"127.0.0.1:{self.gui_port}", self.api_key)

    def ensure_config(self) -> None:
        """First run: let syncthing generate its config + device key/cert."""
        if self.config_xml.exists():
            return
        self.home.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [str(self.binary), "generate", "--home", str(self.home)],
            check=True,
            capture_output=True,
            text=True,
        )

    def start(self, timeout: float = 30.0) -> SyncthingAPI:
        self.ensure_config()
        log_path = self.home / "syncthing.log"
        log = log_path.open("ab")
        self._proc = subprocess.Popen(
            [
                str(self.binary),
                "serve",
                "--home", str(self.home),
                "--no-browser",      # never open Syncthing's own UI
                "--no-restart",      # we supervise restarts ourselves
                "--gui-address", f"127.0.0.1:{self.gui_port}",
                "--logfile", str(log_path),
            ],
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        api = self.api
        wait_for_api(api, timeout)
        return api

    def stop(self) -> None:
        try:
            self.api.shutdown()
        except Exception:
            pass  # already down
        if self._proc is not None:
            try:
                self._proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            self._proc = None


def default_engine(gui_port: int = DEFAULT_GUI_PORT) -> SyncthingEngine:
    """The real app's engine: bundled binary + per-user config dir."""
    from groupwatch.config import config_dir
    from groupwatch.platform.paths import syncthing_binary

    return SyncthingEngine(syncthing_binary(), config_dir() / "syncthing", gui_port)
