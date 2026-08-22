#!/usr/bin/env python3
"""Phase 2 protocol test: two groupwatch syncplay clients stay in sync.

By default the test is self-contained: it starts OUR embedded minimal server
(groupwatch.syncplay.server) on an ephemeral port and connects two clients
with mock players (no mpv needed). A seek+play on one client must land on the
other, and a pause on the second must land back on the first.

    python tools/e2e_playback_test.py             # our embedded server
    python tools/e2e_playback_test.py --upstream  # real syncplay server on :8999
                                                  # (protocol-compat check)
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from groupwatch.players.base import PlayerAdapter
from groupwatch.syncplay.client import SyncplayClient
from groupwatch.syncplay.server import SyncplayServer

HOST, ROOM = "127.0.0.1", "groupwatch"


class MockPlayer(PlayerAdapter):
    """PlayerAdapter with no real player; records what sync applies to it."""

    name = "mock"

    def __init__(self) -> None:
        super().__init__()
        self._pos = 0.0
        self._paused = True
        self._pos_at = time.monotonic()
        self._path = ""
        self.seek_calls: list[float] = []
        self.pause_calls: list[bool] = []

    # adapter API (sync-driven) ------------------------------------------
    def start(self) -> None: pass

    def open_file(self, path, position: float = 0.0) -> None:
        self._path = str(path)
        self._pos = position
        self._pos_at = time.monotonic()
        if self.on_file_loaded:
            self.on_file_loaded(self.current_filename(), 600.0, 1234)

    def set_paused(self, paused: bool) -> None:
        self._pos = self.get_position()
        self._paused = paused
        self._pos_at = time.monotonic()
        self.pause_calls.append(paused)

    def seek(self, position: float) -> None:
        self._pos = position
        self._pos_at = time.monotonic()
        self.seek_calls.append(position)

    def get_position(self) -> float:
        return self._pos if self._paused else self._pos + (time.monotonic() - self._pos_at)

    def is_paused(self) -> bool: return self._paused
    def get_duration(self) -> float: return 600.0
    def current_filename(self) -> str: return os.path.basename(self._path)
    def close(self) -> None: pass

    # test helpers (simulate the human) ------------------------------------
    def user_seek(self, pos: float) -> None:
        self._pos = pos
        self._pos_at = time.monotonic()
        if self.on_change:
            self.on_change(self._pos, self._paused)

    def user_pause(self, paused: bool) -> None:
        self._pos = self.get_position()
        self._paused = paused
        self._pos_at = time.monotonic()
        if self.on_change:
            self.on_change(self._pos, self._paused)


def check(label: str, ok: bool) -> bool:
    print(f"  [{'ok' if ok else 'XX'}] {label}")
    return ok


def wait_for(desc: str, cond, timeout: float = 8.0) -> bool:
    """Poll cond() until true — robust against server-heartbeat timing."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(0.2)
    print(f"    (timed out waiting for: {desc})")
    return False


def main() -> int:
    upstream = "--upstream" in sys.argv
    server = None
    if not upstream:
        server = SyncplayServer(port=0, room=ROOM)  # port 0 -> ephemeral
        server.start()
        print(f"[test] embedded server listening on :{server.port}")
        port = server.port
    else:
        port = 8999
        print(f"[test] using external upstream server on :{port}")

    player_a, player_b = MockPlayer(), MockPlayer()
    a = SyncplayClient(HOST, port, "tester-a", ROOM, player_a)
    b = SyncplayClient(HOST, port, "tester-b", ROOM, player_b)
    passed = True
    try:
        a.connect()
        b.connect()
        print("[test] both clients connected + joined room")
        player_a.open_file("episode01.mkv")
        player_b.open_file("episode01.mkv")
        time.sleep(1.5)  # let the room settle

        passed &= check("A sees B in room", "tester-b" in a.users)
        passed &= check("B sees A in room", "tester-a" in b.users)

        # A seeks to 120s and presses play.
        print("[test] A seeks to 120s + plays")
        player_a.user_seek(120.0)
        player_a.user_pause(False)

        passed &= check("B is playing (unpaused)",
                        wait_for("B unpause", lambda: player_b.is_paused() is False))
        passed &= check("B seeked near 120s",
                        wait_for("B seek", lambda: player_b.get_position() > 100.0))
        b_pos = player_b.get_position()
        print(f"    (B at {b_pos:.1f}s)")

        # B presses pause.
        print("[test] B pauses")
        player_b.user_pause(True)
        passed &= check("A is paused",
                        wait_for("A pause", lambda: player_a.is_paused() is True))
    finally:
        a.close()
        b.close()
        if server is not None:
            time.sleep(0.3)
            server.stop()

    print("[test] PASS" if passed else "[test] FAIL")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
