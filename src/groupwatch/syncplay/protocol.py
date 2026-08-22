"""Syncplay wire protocol: newline-delimited JSON over TCP.

Reference: Syncplay's syncplay/protocols.py (same language). Each message is a
single JSON object ``{"Command": payload}`` terminated by a newline. Syncplay
itself (Twisted LineReceiver) terminates with ``\\r\\n``; we send ``\\r\\n`` to
match exactly, and split incoming data on ``\\n`` (stripping ``\\r``) so we
tolerate both.
"""

from __future__ import annotations

import json

# Message command names (both directions).
HELLO = "Hello"
SET = "Set"
LIST = "List"
STATE = "State"
ERROR = "Error"
CHAT = "Chat"  # parsed but never surfaced (no social features, AGENTS.md §2)
TLS = "TLS"


def encode(message: dict) -> bytes:
    """Serialize one protocol message to bytes on the wire."""
    return json.dumps(message).encode("utf-8") + b"\r\n"


class LineBuffer:
    """Incrementally split an incoming byte stream into protocol messages."""

    def __init__(self) -> None:
        self._buf = b""

    def feed(self, data: bytes) -> list[dict]:
        self._buf += data
        out: list[dict] = []
        while b"\n" in self._buf:
            line, self._buf = self._buf.split(b"\n", 1)
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass  # ignore malformed lines rather than die
        return out
