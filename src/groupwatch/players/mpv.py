"""mpv adapter — the bundled default player (AGENTS.md §3.4).

Controlled via mpv's JSON IPC over a socket (Unix) or named pipe (Windows).
mpv is launched with ``--input-ipc-server`` and we speak newline-delimited
JSON: commands look like ``{"command": [...], "request_id": N}`` and mpv replies
with ``{"data": ..., "error": "success", "request_id": N}`` plus async
``{"event": "property-change", ...}`` messages.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from groupwatch.players.base import PlayerAdapter

# A position jump smaller than this is playback, not a user seek.
_SEEK_EPSILON = 1.0
# After WE seek (a sync correction), ignore the resulting position events for
# this long so they aren't mistaken for a user seek.
_SEEK_GUARD_S = 1.0


class MpvAdapter(PlayerAdapter):
    name = "mpv"
    speed_supported = True

    def __init__(self, headless: bool = False, binary: str | None = None):
        super().__init__()
        self.headless = headless  # --vo=null --ao=null, for tests/CI
        self.binary = binary or "mpv"
        self._proc: subprocess.Popen | None = None
        self._sock: socket.socket | None = None
        self._reader: threading.Thread | None = None
        self._lock = threading.Lock()
        self._next_request_id = 1
        self._pending: dict[int, dict] = {}
        self._pending_event = threading.Event()

        self._position = 0.0
        self._position_at = time.monotonic()  # when _position was last set
        self._paused = True
        self._duration = 0.0
        self._path = ""
        self._seek_guard_until = 0.0

    # ------------------------------------------------------------------ launch

    def start(self) -> None:
        sock_path = self._make_socket_path()
        args = [
            self.binary,
            "--idle=yes",
            f"--input-ipc-server={sock_path}",
            "--input-terminal=no",
            "--terminal=no",
        ]
        if self.headless:
            args += ["--vo=null", "--ao=null", "--force-window=no"]
        else:
            args += ["--force-window=yes"]
        self._proc = subprocess.Popen(
            args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )

        # Wait for the IPC socket to appear, then connect.
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if self._proc.poll() is not None:
                raise RuntimeError("mpv exited during startup")
            if self._try_connect(sock_path):
                break
            time.sleep(0.1)
        else:
            raise RuntimeError("timed out waiting for mpv's IPC socket")

        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        # Event-driven state updates.
        for prop in ("time-pos", "pause", "path", "duration"):
            self._observe(prop)

    def _make_socket_path(self) -> str:
        if sys.platform.startswith("win"):
            return rf"\\.\pipe\groupwatch-mpv-{os.getpid()}"
        return os.path.join(
            tempfile.gettempdir(), f"groupwatch-mpv-{os.getpid()}.sock"
        )

    def _try_connect(self, sock_path: str) -> bool:
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.connect(sock_path)
            self._sock = s
            return True
        except OSError:
            return False

    # ------------------------------------------------------------------ IPC

    def _command(self, *cmd, expect_reply: bool = True):
        with self._lock:
            rid = self._next_request_id
            self._next_request_id += 1
        if not expect_reply:
            self._send({"command": list(cmd)})
            return None
        self._pending_event.clear()
        self._send({"command": list(cmd), "request_id": rid})
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            self._pending_event.wait(0.1)
            with self._lock:
                if rid in self._pending:
                    return self._pending.pop(rid).get("data")
        raise TimeoutError(f"mpv did not answer command {cmd!r}")

    def _send(self, obj: dict) -> None:
        if self._sock is None:
            return
        try:
            self._sock.sendall(json.dumps(obj).encode("utf-8") + b"\n")
        except OSError:
            pass

    def _observe(self, prop: str) -> None:
        self._send({"command": ["observe_property", prop, prop]})

    def _read_loop(self) -> None:
        buf = b""
        while self._sock is not None:
            try:
                chunk = self._sock.recv(65536)
            except OSError:
                break
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                line = line.strip()
                if line:
                    self._handle_line(line)

    def _handle_line(self, line: bytes) -> None:
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            return
        if "request_id" in msg:
            with self._lock:
                self._pending[msg["request_id"]] = msg
            self._pending_event.set()
            return
        if msg.get("event") == "property-change":
            self._on_property(msg.get("name"), msg.get("data"))

    # ------------------------------------------------------- state & events

    def _on_property(self, name, data) -> None:
        prev_position, prev_paused = self._position, self._paused
        if name == "time-pos" and isinstance(data, (int, float)):
            self._position = float(data)
            self._position_at = time.monotonic()
        elif name == "pause" and isinstance(data, bool):
            self._paused = data
        elif name == "duration" and isinstance(data, (int, float)):
            self._duration = float(data)
        elif name == "path" and isinstance(data, str):
            self._path = data
            if self.on_file_loaded:
                self.on_file_loaded(self.current_filename(), self.get_duration(), 0)
            return
        else:
            return
        self._maybe_emit_change(prev_position, prev_paused)

    def _maybe_emit_change(self, prev_position: float, prev_paused: bool) -> None:
        if not self.on_change:
            return
        # Pause toggle is a user action.
        if self._paused != prev_paused:
            self.on_change(self._position, self._paused)
            return
        # A position jump we did NOT cause ourselves is a user seek.
        jump = abs(self._position - prev_position)
        if jump > _SEEK_EPSILON and time.monotonic() > self._seek_guard_until:
            self.on_change(self._position, self._paused)

    # ----------------------------------------------------------- commands

    def open_file(self, path: Path, position: float = 0.0) -> None:
        self._command("loadfile", str(path), expect_reply=False)
        if position > 0:
            # Let the file load before jumping.
            threading.Timer(0.5, lambda: self.seek(position)).start()

    def set_paused(self, paused: bool) -> None:
        self._command("set_property", "pause", paused, expect_reply=False)

    def seek(self, position: float) -> None:
        self._seek_guard_until = time.monotonic() + _SEEK_GUARD_S
        self._position = position
        self._position_at = time.monotonic()
        self._command("set_property", "time-pos", position, expect_reply=False)

    def set_speed(self, factor: float) -> None:
        self._command("set_property", "speed", factor, expect_reply=False)

    # -------------------------------------------------------------- getters

    def get_position(self) -> float:
        # mpv only pushes time-pos on change, so while playing we add the
        # elapsed time since the last event for an accurate live position.
        if self._paused:
            return self._position
        return self._position + (time.monotonic() - self._position_at)

    def is_paused(self) -> bool:
        return self._paused

    def get_duration(self) -> float:
        return self._duration

    def current_filename(self) -> str:
        return os.path.basename(self._path) if self._path else ""

    def close(self) -> None:
        try:
            self._send({"command": ["quit"]})
        except Exception:
            pass
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        if self._proc is not None:
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            self._proc = None
