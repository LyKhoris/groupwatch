"""Player adapter interface (AGENTS.md §3.4).

Each group member picks their own player; adapters translate between the
syncplay engine and the player. Syncplay syncs playback *state*, not video —
one member can use VLC while another uses mpv, as long as everyone plays the
same file from the synced folder.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Callable, Optional


class PlayerAdapter(ABC):
    """Common interface: open file, play, pause, seek, position/state, events.

    Position is in seconds. ``on_change`` fires on *user-initiated* changes
    (the human paused / seeked / loaded a file) so the syncplay client can
    broadcast them; sync-driven corrections must NOT trigger it.
    """

    name: str = "base"
    speed_supported: bool = False

    def __init__(self) -> None:
        self.on_change: Optional[Callable[[float, bool], None]] = None
        self.on_file_loaded: Optional[Callable[[str, float, int], None]] = None

    @abstractmethod
    def start(self) -> None:
        """Launch the player process / connect its remote interface."""

    @abstractmethod
    def open_file(self, path: Path, position: float = 0.0) -> None:
        """Load a file and (optionally) jump to a position."""

    @abstractmethod
    def set_paused(self, paused: bool) -> None: ...

    @abstractmethod
    def seek(self, position: float) -> None: ...

    def set_speed(self, factor: float) -> None:  # only if speed_supported
        raise NotImplementedError

    @abstractmethod
    def get_position(self) -> float: ...

    @abstractmethod
    def is_paused(self) -> bool: ...

    @abstractmethod
    def get_duration(self) -> float: ...

    @abstractmethod
    def current_filename(self) -> str: ...

    @abstractmethod
    def close(self) -> None:
        """Stop playback and quit the player."""
