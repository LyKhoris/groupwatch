"""Minimal embedded Syncplay server for the leader's machine (AGENTS.md §3.3).

Own implementation — the owner approved replacing the original "vendored
upstream" plan (decision log §4): every member runs groupwatch's invisible
client, so the server only needs the protocol subset that client speaks —
Hello / Set / List / State with latency-compensation bookkeeping. Stdlib only;
runs as plain threads inside the app process. No passwords, chat, playlists,
managed rooms or TLS — private trusted group (§2).

Wire format matches Syncplay's exactly (newline-delimited JSON, §protocol),
so the real Syncplay client remains *approximately* compatible even though
that is not a goal.
"""

from __future__ import annotations

import socket
import threading
import time
from typing import Optional

from groupwatch.syncplay import protocol
from groupwatch.syncplay.client import CLIENT_VERSION, PingService

SERVER_VERSION = CLIENT_VERSION
HEARTBEAT_INTERVAL_S = 1.0        # upstream SERVER_STATE_INTERVAL
POSITION_EPSILON_S = 1.0          # room follows a member only past this drift
DEFAULT_SERVER_PORT = 8999

# Per-(client-thread) identity so message handlers can find their watcher.
_ctx = threading.local()

_SERVER_FEATURES = {
    "sharedPlaylists": False,
    "chat": False,
    "uiMode": "console",
    "featureList": True,
    "readiness": True,
    "managedRooms": False,
    "persistentRooms": False,
}


class _Watcher:
    """One connected group member."""

    def __init__(self, sock: socket.socket, username: str, version: str):
        self.sock = sock
        self.username = username
        self.version = version
        self.room = ""
        self.file: dict = {}
        self.ping = PingService()
        # Feedback-suppression counters (mirror upstream's ignoringOnTheFly):
        self.client_ignoring = 0   # echoes of this client's changes, awaiting ack
        self.server_ignoring = 0   # forced changes we sent, awaiting ack
        self.pending_latency_ts: Optional[float] = None
        self.pending_latency_at = 0.0
        self.alive = True

    def send(self, message: dict) -> None:
        try:
            self.sock.sendall(protocol.encode(message))
        except OSError:
            self.alive = False


class _Room:
    def __init__(self) -> None:
        self.position = 0.0
        self.paused = True
        self.set_by: Optional[str] = None
        self.updated_at = time.time()
        self.do_seek = False  # one-shot flag, consumed by the next broadcast

    def live_position(self) -> float:
        if self.paused:
            return self.position
        return self.position + (time.time() - self.updated_at)

    def update(self, position: float, paused: bool, do_seek: bool, set_by: str) -> bool:
        changed = paused != self.paused or do_seek
        self.position = position
        self.paused = paused
        self.set_by = set_by
        self.updated_at = time.time()
        if do_seek:
            self.do_seek = True
        return changed


class SyncplayServer:
    """Leader-side playback-sync server. start() is non-blocking."""

    def __init__(self, port: int = DEFAULT_SERVER_PORT, room: str = "groupwatch"):
        self._requested_port = port
        self.port = port
        self.main_room = room
        self._listener: socket.socket | None = None
        self._lock = threading.Lock()
        self._watchers: list[_Watcher] = []
        self._rooms: dict[str, _Room] = {}
        self._running = False

    # ------------------------------------------------------------- lifecycle

    def start(self) -> None:
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind(("0.0.0.0", self._requested_port))  # remote friends
        self._listener.listen(16)
        # Port 0 = ephemeral; learn what the OS picked (tests).
        self.port = self._listener.getsockname()[1]
        self._running = True
        threading.Thread(target=self._accept_loop, daemon=True).start()
        threading.Thread(target=self._heartbeat_loop, daemon=True).start()

    def stop(self) -> None:
        self._running = False
        with self._lock:
            for w in list(self._watchers):
                w.sock.close()
            self._watchers.clear()
        if self._listener is not None:
            try:
                self._listener.close()
            except OSError:
                pass
            self._listener = None

    @property
    def running(self) -> bool:
        return self._running

    # ------------------------------------------------------------------ loops

    def _accept_loop(self) -> None:
        while self._running:
            try:
                sock, addr = self._listener.accept()
            except OSError:
                break
            threading.Thread(target=self._client_loop, args=(sock,),
                             daemon=True).start()

    def _heartbeat_loop(self) -> None:
        while self._running:
            time.sleep(HEARTBEAT_INTERVAL_S)
            with self._lock:
                for w in list(self._watchers):
                    if not w.alive:
                        continue
                    room = self._rooms.get(w.room)
                    pos = room.live_position() if room else 0.0
                    paused = room.paused if room else True
                    self._send_state(w, pos, paused, do_seek=False,
                                     set_by=None, forced=False)

    # ------------------------------------------------------------- per client

    def _client_loop(self, sock: socket.socket) -> None:
        buf = protocol.LineBuffer()
        watcher: Optional[_Watcher] = None
        try:
            while True:
                data = sock.recv(65536)
                if not data:
                    break
                for msg in buf.feed(data):
                    result = self._handle(sock, msg)
                    if result is False:
                        return
                    if isinstance(result, _Watcher):
                        watcher = result
                        _ctx.watcher = watcher
        except OSError:
            pass
        finally:
            _ctx.__dict__.pop("watcher", None)
            if watcher is not None:
                self._drop(watcher)

    def _handle(self, sock: socket.socket, msg: dict):
        """Returns False to close, a _Watcher after Hello, else None."""
        for command, payload in msg.items():
            if command == protocol.HELLO:
                return self._handle_hello(sock, payload)
            if command == protocol.STATE:
                self._handle_state(payload)
            elif command == protocol.SET:
                self._handle_set(payload)
            elif command == protocol.LIST:
                me = self._current()
                if me:
                    self._send_list(me)
            # Chat / TLS / unknown: intentionally ignored (§2).
        return None

    @staticmethod
    def _current() -> Optional[_Watcher]:
        return getattr(_ctx, "watcher", None)

    # ------------------------------------------------------------------ Hello

    def _handle_hello(self, sock: socket.socket, hello: dict):
        username = (hello.get("username") or "").strip()
        room_name = ((hello.get("room") or {}).get("name") or "").strip() or self.main_room
        version = str(hello.get("realversion") or hello.get("version") or "")
        if not username or not version:
            self._send_error_and_close(sock, "Welcome request malformed")
            return False

        with self._lock:
            username = self._unique_name(username)
            w = _Watcher(sock, username, version)
            w.room = room_name
            self._rooms.setdefault(room_name, _Room())
            self._watchers.append(w)

        w.send({"Hello": {
            "username": username,
            "room": {"name": room_name},
            "version": version,       # echo the client's version (upstream does)
            "realversion": SERVER_VERSION,
            "features": _SERVER_FEATURES,
            "motd": "",
        }})
        self._announce(w, joined=True)
        self._broadcast_lists()
        return w

    def _unique_name(self, wanted: str) -> str:
        names = {w.username for w in self._watchers}
        if wanted not in names:
            return wanted
        n = 2
        while f"{wanted}-{n}" in names:
            n += 1
        return f"{wanted}-{n}"

    # -------------------------------------------------------------------- Set

    def _handle_set(self, settings: dict) -> None:
        me = self._current()
        if me is None:
            return
        for command, values in settings.items():
            if command == "room":
                name = ((values or {}).get("name") or "").strip()
                if name and name != me.room:
                    with self._lock:
                        me.room = name
                        self._rooms.setdefault(name, _Room())
                    self._announce(me, joined=True)
                    self._broadcast_lists()
            elif command == "file":
                if isinstance(values, dict):
                    with self._lock:
                        me.file = values
                    self._announce_file(me)

    # ------------------------------------------------------------------ State

    def _handle_state(self, payload: dict) -> None:
        me = self._current()
        if me is None:
            return

        if "ignoringOnTheFly" in payload:
            ignore = payload["ignoringOnTheFly"]
            if "server" in ignore and me.server_ignoring == ignore["server"]:
                me.server_ignoring = 0
            if "client" in ignore:
                me.client_ignoring = ignore["client"]

        if "ping" in payload:
            ping = payload["ping"]
            me.pending_latency_ts = ping.get("clientLatencyCalculation") or None
            me.pending_latency_at = time.time()
            me.ping.receive_message(ping.get("latencyCalculation"),
                                    ping.get("clientRtt"))

        if "playstate" not in payload:
            return
        ps = payload["playstate"]
        position = ps.get("position", 0.0)
        paused = ps.get("paused")
        do_seek = bool(ps.get("doSeek"))
        if paused is None:
            return

        with self._lock:
            room = self._rooms.get(me.room)
            if room is None:
                return
            live = room.live_position()
            significant = (do_seek or paused != room.paused
                           or abs(position - live) > POSITION_EPSILON_S)
            if significant and me.server_ignoring == 0:
                changed = room.update(position, paused, do_seek, me.username)
            else:
                changed = False
            if changed:
                self._broadcast_room_state_locked(room, forced=True)

    def _broadcast_room_state_locked(self, room: _Room, forced: bool) -> None:
        room_name = next((n for n, r in self._rooms.items() if r is room), None)
        if room_name is None:
            return
        members = [w for w in self._watchers if w.room == room_name and w.alive]
        do_seek = room.do_seek
        room.do_seek = False
        for w in members:
            self._send_state(w, room.live_position(), room.paused,
                             do_seek=do_seek, set_by=room.set_by, forced=forced)

    def _send_state(self, w: _Watcher, position: float, paused: bool,
                    do_seek: bool, set_by: Optional[str], forced: bool) -> None:
        processing = time.time() - w.pending_latency_at if w.pending_latency_ts else 0
        playstate = {
            "position": position if position else 0,
            "paused": paused,
            "doSeek": do_seek,
            "setBy": set_by,
        }
        ping = {
            "latencyCalculation": w.ping.new_timestamp(),
            "serverRtt": w.ping.rtt,
        }
        if w.pending_latency_ts is not None:
            ping["clientLatencyCalculation"] = w.pending_latency_ts + processing
            w.pending_latency_ts = None
        state = {"ping": ping, "playstate": playstate}

        if forced:
            w.server_ignoring += 1
        if w.server_ignoring or w.client_ignoring:
            ignore: dict = {}
            if w.server_ignoring:
                ignore["server"] = w.server_ignoring
            if w.client_ignoring:
                ignore["client"] = w.client_ignoring
                w.client_ignoring = 0
            state["ignoringOnTheFly"] = ignore
        if w.server_ignoring == 0 or forced:
            w.send({"State": state})

    # ------------------------------------------------------------------- List

    def _build_list(self) -> dict:
        userlist: dict = {}
        for w in self._watchers:
            userlist.setdefault(w.room, {})[w.username] = {
                "position": 0,
                "file": w.file or {},
                "controller": False,
                "isReady": True,
                "features": _SERVER_FEATURES,
            }
        return userlist

    def _send_list(self, w: _Watcher) -> None:
        w.send({"List": self._build_list()})

    def _broadcast_lists(self) -> None:
        with self._lock:
            snapshot = [w for w in self._watchers if w.alive]
        payload = self._build_list()
        for w in snapshot:
            w.send({"List": payload})

    # ------------------------------------------------------- presence / files

    def _announce(self, watcher: _Watcher, joined: bool) -> None:
        event = {"joined": True} if joined else {"left": True}
        entry: dict = {"room": {"name": watcher.room}, "event": event}
        if joined and watcher.file:
            entry["file"] = watcher.file
        payload = {watcher.username: entry}
        with self._lock:
            others = [x for x in self._watchers if x is not watcher and x.alive]
        for other in others:
            other.send({"Set": {"user": payload}})

    def _announce_file(self, watcher: _Watcher) -> None:
        payload = {watcher.username: {
            "room": {"name": watcher.room},
            "file": watcher.file,
        }}
        with self._lock:
            others = [x for x in self._watchers if x is not watcher and x.alive]
        for other in others:
            other.send({"Set": {"user": payload}})

    def _drop(self, watcher: _Watcher) -> None:
        with self._lock:
            if watcher in self._watchers:
                self._watchers.remove(watcher)
        watcher.alive = False
        try:
            watcher.sock.close()
        except OSError:
            pass
        self._announce(watcher, joined=False)
        self._broadcast_lists()

    # ------------------------------------------------------------------ error

    @staticmethod
    def _send_error_and_close(sock: socket.socket, message: str) -> None:
        try:
            sock.sendall(protocol.encode({"Error": {"message": message}}))
        except OSError:
            pass
        try:
            sock.close()
        except OSError:
            pass
