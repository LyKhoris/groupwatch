"""Invisible Syncplay protocol client (AGENTS.md §3.3).

Speaks Syncplay's JSON-over-TCP protocol itself so friends never see any
Syncplay UI. Auto-joins the group's fixed room on launch and keeps this
machine's player in sync with the room: play / pause / seek, with network
latency compensation.

Only the subset of the protocol groupwatch needs is implemented (no chat, no
controlled rooms, no TLS — private trusted group, AGENTS.md §2). Reference:
Syncplay's syncplay/client.py + protocols.py.
"""

from __future__ import annotations

import socket
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from groupwatch.players.base import PlayerAdapter
from groupwatch.syncplay import protocol

# Sync thresholds, mirroring Syncplay's constants.py.
PING_MOVING_AVERAGE_WEIGHT = 0.85
REWIND_THRESHOLD = 4.0        # we're this far AHEAD -> seek back
FASTFORWARD_THRESHOLD = 5.0   # we're this far BEHIND -> seek forward
SEEK_THRESHOLD = 1.0          # a jump larger than this counts as a user seek
TICK_INTERVAL_S = 0.2         # local-state poll cadence (Syncplay uses 0.1)
CORRECTION_GUARD_S = 1.0      # after applying a sync correction, don't rebroadcast

CLIENT_VERSION = "1.7.7"  # report the upstream version we mirror


class PingService:
    """Round-trip + forward-delay estimation (mirrors Syncplay's PingService)."""

    def __init__(self) -> None:
        self._rtt = 0.0
        self._fd = 0.0
        self._avr_rtt = 0.0

    def new_timestamp(self) -> float:
        return time.time()

    def receive_message(self, timestamp, sender_rtt) -> None:
        if not timestamp:
            return
        self._rtt = time.time() - timestamp
        if self._rtt < 0 or (sender_rtt or 0) < 0:
            return
        if not self._avr_rtt:
            self._avr_rtt = self._rtt
        self._avr_rtt = (
            self._avr_rtt * PING_MOVING_AVERAGE_WEIGHT
            + self._rtt * (1 - PING_MOVING_AVERAGE_WEIGHT)
        )
        if (sender_rtt or 0) < self._rtt:
            self._fd = self._avr_rtt / 2 + (self._rtt - (sender_rtt or 0))
        else:
            self._fd = self._avr_rtt / 2

    @property
    def forward_delay(self) -> float:
        return self._fd

    @property
    def rtt(self) -> float:
        return self._rtt


class SyncplayClient:
    """One group member's connection to the Syncplay server."""

    def __init__(self, host: str, port: int, username: str, room: str,
                 player: PlayerAdapter,
                 on_users_changed: Optional[Callable[[dict], None]] = None):
        self.debug = False  # set True to log incoming playstates (tests)
        self.host, self.port = host, port
        self.username, self.room = username, room
        self.player = player
        self.on_users_changed = on_users_changed

        self._ping = PingService()
        self._sock: socket.socket | None = None
        self._buffer = protocol.LineBuffer()
        self._send_lock = threading.Lock()
        self._connected = threading.Event()
        self._logged = False
        self._closed = False

        # Global (room) playstate as last told by the server.
        self._global_position = 0.0
        self._global_paused = True
        self._last_global_update: float | None = None

        # Feedback suppression (Syncplay's ignoringOnTheFly).
        self._client_ignoring = 0
        self._server_ignoring = 0

        self.users: dict = {}  # room membership, for the Phase 3 people panel
        self._last_correction_at = 0.0  # monotonic; when we last applied a sync fix

    # ------------------------------------------------------------- lifecycle

    def connect(self, timeout: float = 10.0) -> None:
        self._sock = socket.create_connection((self.host, self.port), timeout=timeout)
        self._sock.settimeout(None)
        threading.Thread(target=self._read_loop, daemon=True).start()
        self._send_hello()
        if not self._connected.wait(timeout):
            raise TimeoutError("no Hello from syncplay server")
        # Instant reaction to user actions, plus a poll loop that re-detects
        # divergence until the server confirms it (self-healing, mirrors
        # Syncplay's askPlayer loop).
        self.player.on_change = lambda pos, pau: self._broadcast_if_changed(
            user_initiated=True)
        self.player.on_file_loaded = lambda n, d, s: self.send_file()
        threading.Thread(target=self._tick_loop, daemon=True).start()

    def close(self) -> None:
        self._closed = True
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    @property
    def connected(self) -> bool:
        return self._logged and not self._closed

    # ------------------------------------------------------------ networking

    def _read_loop(self) -> None:
        while not self._closed:
            try:
                data = self._sock.recv(65536)
            except OSError:
                break
            if not data:
                break
            for msg in self._buffer.feed(data):
                self._handle(msg)

    def _send(self, message: dict) -> None:
        if self._sock is None:
            return
        try:
            with self._send_lock:
                self._sock.sendall(protocol.encode(message))
        except OSError:
            pass

    def _handle(self, msg: dict) -> None:
        for command, payload in msg.items():
            if command == protocol.HELLO:
                self._handle_hello(payload)
            elif command == protocol.SET:
                self._handle_set(payload)
            elif command == protocol.LIST:
                self._handle_list(payload)
            elif command == protocol.STATE:
                self._handle_state(payload)
            elif command == protocol.ERROR:
                self._handle_error(payload)
            # Chat / TLS: intentionally ignored (AGENTS.md §2).

    # ---------------------------------------------------------------- Hello

    def _send_hello(self) -> None:
        self._send({"Hello": {
            "username": self.username,
            "room": {"name": self.room},
            "version": "1.2.255",  # for compatibility with 1.2.x servers
            "realversion": CLIENT_VERSION,
            "features": self._features(),
        }})

    @staticmethod
    def _features() -> dict:
        return {
            "sharedPlaylists": False,
            "chat": False,
            "uiMode": "GUI",
            "featureList": True,
            "readiness": True,
            "managedRooms": False,
            "persistentRooms": False,
            "setOthersReadiness": False,
        }

    def _handle_hello(self, hello: dict) -> None:
        self.username = hello.get("username", self.username)
        room = hello.get("room") or {}
        self.room = room.get("name", self.room)
        self._logged = True
        self._connected.set()
        self.send_file()

    # ------------------------------------------------------------------ Set

    def send_file(self) -> None:
        """Announce the file we're playing (name/duration/size)."""
        name = self.player.current_filename()
        if not name:
            return
        size = 0
        try:
            size = Path(self.player._path).stat().st_size  # noqa: SLF001
        except Exception:
            pass
        self._send({"Set": {"file": {
            "name": name,
            "duration": self.player.get_duration(),
            "size": size,
        }}})
        self._send({"List": None})

    def set_ready(self, ready: bool) -> None:
        self._send({"Set": {"ready": {
            "isReady": ready,
            "manuallyInitiated": True,
        }}})

    def _handle_set(self, settings: dict) -> None:
        for command, values in settings.items():
            if command == "user":
                self._set_user(values)

    def _set_user(self, users: dict) -> None:
        for username, s in users.items():
            event = s.get("event") or {}
            if "left" in event:
                self.users.pop(username, None)
            else:
                self.users[username] = s
        self._notify_users()

    def _handle_list(self, user_list: dict) -> None:
        self.users = {}
        for _room, members in user_list.items():
            for username, info in members.items():
                self.users[username] = info
        self._notify_users()

    def _notify_users(self) -> None:
        if self.on_users_changed:
            self.on_users_changed(self.users)

    # ---------------------------------------------------------------- State

    def _handle_state(self, state: dict) -> None:
        if "ignoringOnTheFly" in state:
            ignore = state["ignoringOnTheFly"]
            if "server" in ignore:
                self._server_ignoring = ignore["server"]
                self._client_ignoring = 0
            elif "client" in ignore:
                if ignore["client"] == self._client_ignoring:
                    self._client_ignoring = 0

        position = paused = do_seek = None
        if "playstate" in state:
            ps = state["playstate"]
            position = ps.get("position", 0.0)
            paused = ps.get("paused")
            do_seek = ps.get("doSeek")
        if self.debug and ("playstate" in state or "ignoringOnTheFly" in state):
            print(f"    [{self.username} <- server] playstate={state.get('playstate')} "
                  f"ignore={state.get('ignoringOnTheFly')} (my client_ignoring={self._client_ignoring})")

        latency_calculation = None
        if "ping" in state:
            ping = state["ping"]
            latency_calculation = ping.get("latencyCalculation")
            if "clientLatencyCalculation" in ping:
                self._ping.receive_message(
                    ping["clientLatencyCalculation"], ping.get("serverRtt", 0)
                )
        message_age = self._ping.forward_delay

        if position is not None and paused is not None and not self._client_ignoring:
            # The server force-feeds everyone (including the actor) each room
            # change. Our own echoes must update bookkeeping but NEVER be
            # re-applied to the player — otherwise a fast seek+pause combo
            # gets undone by the delayed echo of the seek (real bug, e2e-caught).
            from_self = (state.get("playstate", {}).get("setBy") == self.username)
            self._update_global_state(position, paused, do_seek, message_age,
                                      from_self=from_self)

        pos, pau, seek, state_change = self._get_local_state()
        self._send_state(pos, pau, seek, latency_calculation, state_change)

    def _send_state(self, position, paused, do_seek, latency_calculation,
                    state_change: bool) -> None:
        state: dict = {}
        client_ignore_ok = self._client_ignoring == 0 or self._server_ignoring != 0
        if client_ignore_ok and position is not None and paused is not None:
            state["playstate"] = {"position": position, "paused": paused}
            if do_seek:
                state["playstate"]["doSeek"] = do_seek
        ping = {"clientLatencyCalculation": self._ping.new_timestamp(),
                "clientRtt": self._ping.rtt}
        if latency_calculation:
            ping["latencyCalculation"] = latency_calculation
        state["ping"] = ping
        if state_change:
            self._client_ignoring += 1
        if self._server_ignoring or self._client_ignoring:
            state["ignoringOnTheFly"] = {}
            if self._server_ignoring:
                state["ignoringOnTheFly"]["server"] = self._server_ignoring
                self._server_ignoring = 0
            if self._client_ignoring:
                state["ignoringOnTheFly"]["client"] = self._client_ignoring
        self._send({"State": state})

    def _get_local_state(self):
        paused = self.player.is_paused()
        position = self.player.get_position()
        pause_change = paused != self._global_paused
        seeked = abs(position - self._expected_global_position()) > SEEK_THRESHOLD
        if self._last_global_update is None:
            return None, None, None, None
        return position, paused, seeked, (pause_change or seeked)

    # --------------------------------------------------- apply global -> player

    def _expected_global_position(self) -> float:
        """Where the room should be right now (global state + elapsed)."""
        if self._last_global_update is None:
            return self._global_position
        pos = self._global_position
        if not self._global_paused:
            pos += time.time() - self._last_global_update
        return pos

    def _update_global_state(self, position: float, paused: bool,
                             do_seek, message_age: float,
                             from_self: bool = False) -> None:
        if not paused:
            position += message_age  # compensate for network delay

        first = self._last_global_update is None
        self._global_position = position
        self._global_paused = paused
        self._last_global_update = time.time()
        if from_self:
            return  # already applied locally when the user acted

        player_pos = self.player.get_position()
        diff = player_pos - position
        pause_changed = paused != self._global_paused or paused != self.player.is_paused()

        if first:
            self._last_correction_at = time.monotonic()
            self.player.seek(position)
            self.player.set_paused(paused)
            return
        if do_seek:
            self._last_correction_at = time.monotonic()
            self.player.seek(position)
        elif diff > REWIND_THRESHOLD:
            self._last_correction_at = time.monotonic()
            self.player.seek(position)       # we're ahead -> rewind
        elif diff < -FASTFORWARD_THRESHOLD:
            self._last_correction_at = time.monotonic()
            self.player.seek(position)       # we're behind -> catch up
        if pause_changed:
            self._last_correction_at = time.monotonic()
            self.player.set_paused(paused)

    # ------------------------------------------------------- user -> broadcast

    def _broadcast_if_changed(self, user_initiated: bool = False) -> None:
        """Detect local-vs-room divergence and broadcast it.

        Mirrors Syncplay's updateAndSyncStatus: compares the player against the
        SERVER's global state (never our own optimistic copy), so a broadcast
        that was suppressed by ignoringOnTheFly gets retried until the server
        confirms — rapid seek+play combos still land.

        user_initiated=True (the player adapter reported a human action)
        bypasses the correction guard: real user actions must never be
        suppressed, or a locally-paused client can get stuck re-arming the
        guard with catch-up seeks (e2e-caught bug).
        """
        if not self.connected or self._last_global_update is None:
            return
        if (not user_initiated
                and time.monotonic() - self._last_correction_at < CORRECTION_GUARD_S):
            return  # passive poll right after a sync correction; don't echo it
        paused = self.player.is_paused()
        position = self.player.get_position()
        pause_change = paused != self._global_paused
        seeked = abs(position - self._expected_global_position()) > SEEK_THRESHOLD
        if pause_change or seeked:
            self._send_state(position, paused, seeked, None, state_change=True)

    def _tick_loop(self) -> None:
        while not self._closed:
            time.sleep(TICK_INTERVAL_S)
            try:
                self._broadcast_if_changed()
            except Exception:
                pass

    # ---------------------------------------------------------------- errors

    def _handle_error(self, error: dict) -> None:
        # Phase 6 (polish) turns these into plain-language UI. For now, log.
        print(f"[groupwatch] syncplay server error: {error.get('message')}")
