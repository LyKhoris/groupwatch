"""Invite codes (AGENTS.md §3.5).

A leader generates one invite per friend; the friend pastes it and everything
else is automatic. The code is a copy-pastable string carrying: the leader's
Syncthing device ID, the shared folder ID, the Syncplay server address, the
room name, and the leader's display name.

Format: ``gw1:`` + base64url(JSON). Versioned so future format changes don't
silently break old codes.
"""

from __future__ import annotations

import base64
import json
from dataclasses import asdict, dataclass

PREFIX = "gw1:"
DEFAULT_SERVER_PORT = 8999
DEFAULT_ROOM = "groupwatch"

_KNOWN_FIELDS = (
    "leader_device_id",
    "folder_id",
    "server_host",
    "server_port",
    "room",
    "leader_name",
    "version",
)


@dataclass
class Invite:
    leader_device_id: str
    folder_id: str
    server_host: str = ""  # filled in Phase 2 (leader's syncplay server)
    server_port: int = DEFAULT_SERVER_PORT
    room: str = DEFAULT_ROOM
    leader_name: str = ""
    version: int = 1

    def encode(self) -> str:
        payload = json.dumps(asdict(self), separators=(",", ":")).encode("utf-8")
        return PREFIX + base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")

    @classmethod
    def decode(cls, text: str) -> "Invite":
        text = text.strip()
        if not text.startswith(PREFIX):
            raise ValueError("not a groupwatch invite code")
        body = text[len(PREFIX):]
        body += "=" * (-len(body) % 4)  # restore stripped padding
        try:
            data = json.loads(base64.urlsafe_b64decode(body))
        except Exception as exc:
            raise ValueError("invite code is corrupted") from exc
        if not isinstance(data, dict) or data.get("version") != 1:
            raise ValueError("unsupported invite version")
        return cls(**{k: data[k] for k in _KNOWN_FIELDS if k in data})
