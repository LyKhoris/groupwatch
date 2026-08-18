"""Per-device sync completion — powers the people panel and the Phase 4
readiness gate ("Waiting for Sam (60%)…", AGENTS.md §3.6)."""

from __future__ import annotations

import urllib.error

from groupwatch.sync.api import SyncthingAPI


def folder_completion(api: SyncthingAPI, device_id: str, folder_id: str) -> float:
    """0–100: how much of the folder the device has, as seen by this machine."""
    try:
        return float(api.db_completion(device_id, folder_id).get("completion", 0.0))
    except Exception:
        return 0.0


def file_synced(api: SyncthingAPI, device_id: str, folder_id: str, relpath: str) -> bool:
    """True if the device holds the leader's current version of one file.

    Uses Syncthing's "availability" — the list of devices holding the current
    global version of the file — from this machine's index.
    """
    try:
        view = api.db_file(folder_id, relpath)
    except urllib.error.HTTPError:
        return False  # 404: file not in the index at all
    except Exception:
        return False
    # availability entries are objects: {"id": "<device-id>", "fromTemporary": bool}
    return any(
        entry.get("id") == device_id
        for entry in (view.get("availability") or [])
        if isinstance(entry, dict)
    )
