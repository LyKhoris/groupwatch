#!/usr/bin/env python3
"""Phase 2 EXIT CRITERIA (AGENTS.md §7): "Two clients play/pause/seek the same
file in sync, mpv only."

Two groupwatch invisible clients each drive a REAL mpv (headless --vo=null)
through our embedded minimal Syncplay server. "User" actions are simulated
faithfully by opening a second connection to mpv's IPC socket and issuing the
exact commands real keybindings run ("cycle pause", absolute seek).

    python tools/e2e_mpv_test.py

Requires: mpv on PATH; ffmpeg to generate the test clip (once).
"""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from groupwatch.players.mpv import MpvAdapter
from groupwatch.syncplay.client import SyncplayClient
from groupwatch.syncplay.server import SyncplayServer

VIDEO = Path("/tmp/groupwatch-test.mp4")


def ensure_video() -> bool:
    if VIDEO.exists():
        return True
    r = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error",
         "-f", "lavfi", "-i", "testsrc2=duration=600:size=320x240:rate=10",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=600",
         "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
         str(VIDEO)],
        capture_output=True,
    )
    return r.returncode == 0 and VIDEO.exists()


class UserHand:
    """Injects the exact IPC commands real mpv keybindings produce."""

    def __init__(self, adapter: MpvAdapter):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(adapter.socket_path)

    def _send(self, cmd: list) -> None:
        self.sock.sendall(json.dumps({"command": cmd}).encode() + b"\n")

    def toggle_pause(self) -> None:
        self._send(["cycle", "pause"])  # what the spacebar binding runs

    def seek_absolute(self, pos: float) -> None:
        self._send(["seek", pos, "absolute+exact"])

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


def check(label: str, ok: bool) -> bool:
    print(f"  [{'ok' if ok else 'XX'}] {label}")
    return ok


def wait_for(desc: str, cond, timeout: float = 12.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(0.25)
    print(f"    (timed out waiting for: {desc})")
    return False


def main() -> int:
    if not ensure_video():
        print("[e2e] could not create the test video (ffmpeg missing?)")
        return 1

    server = SyncplayServer(port=0, room="groupwatch")
    server.start()
    print(f"[e2e] embedded server on :{server.port}")

    player_a, player_b = MpvAdapter(headless=True), MpvAdapter(headless=True)
    a = SyncplayClient("127.0.0.1", server.port, "mpv-a", "groupwatch", player_a)
    b = SyncplayClient("127.0.0.1", server.port, "mpv-b", "groupwatch", player_b)
    passed = True
    try:
        player_a.start()
        player_b.start()
        a.connect()
        b.connect()
        player_a.open_file(VIDEO)
        player_b.open_file(VIDEO)
        passed &= check("both mpvs report the same file loaded",
                        wait_for("file loads", lambda:
                                 player_a.current_filename() == player_b.current_filename()
                                 == "groupwatch-test.mp4"))

        # --- A's human seeks to 120s and presses play -----------------------
        user_a = UserHand(player_a)
        user_a.seek_absolute(120.0)
        user_a.toggle_pause()

        passed &= check("B unpauses when A plays",
                        wait_for("B unpause", lambda: not player_b.is_paused()))
        passed &= check("B follows A's seek (~120s)",
                        wait_for("B seek", lambda: player_b.get_position() > 115.0))

        # --- positions stay locked while playing ----------------------------
        for i in range(3):
            time.sleep(2.0)
            drift = abs(player_a.get_position() - player_b.get_position())
            passed &= check(f"drift sample {i + 1}: "
                            f"A={player_a.get_position():.1f}s B={player_b.get_position():.1f}s "
                            f"(delta {drift:.2f}s < 2s)", drift < 2.0)

        # --- B's human pauses ------------------------------------------------
        user_b = UserHand(player_b)
        user_b.toggle_pause()
        passed &= check("A pauses when B pauses",
                        wait_for("A pause", lambda: player_a.is_paused()))

        # --- A's human seeks while paused ------------------------------------
        user_a.seek_absolute(42.0)
        passed &= check("B follows the paused seek (~42s)",
                        wait_for("B paused-seek",
                                 lambda: abs(player_b.get_position() - 42.0) < 2.5))
    finally:
        user_locals = [v for v in dict(locals()).values() if isinstance(v, UserHand)]
        for u in user_locals:
            u.close()
        a.close()
        b.close()
        time.sleep(0.3)
        player_a.close()
        player_b.close()
        server.stop()

    print("[e2e] PASS" if passed else "[e2e] FAIL")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
