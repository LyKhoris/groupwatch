"""Minimal client for Syncthing's localhost REST API.

Stdlib only (no new dependencies, AGENTS.md §2). groupwatch drives Syncthing
entirely through this API; Syncthing's own web UI is never exposed to users.
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request


class SyncthingAPI:
    def __init__(self, address: str, api_key: str):
        self.base = f"http://{address}/rest"
        self.api_key = api_key

    def _request(self, method: str, path: str, params: dict | None = None, body=None):
        url = self.base + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("X-API-Key", self.api_key)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = resp.read()
        return json.loads(payload) if payload else {}

    def get(self, path, params=None):
        return self._request("GET", path, params)

    def post(self, path, params=None, body=None):
        return self._request("POST", path, params, body)

    def put(self, path, body=None):
        return self._request("PUT", path, None, body)

    # --- typed helpers -------------------------------------------------

    def ping(self) -> dict:
        return self.get("/system/ping")

    def status(self) -> dict:
        return self.get("/system/status")

    def my_id(self) -> str:
        return self.status()["myID"]

    def config(self) -> dict:
        return self.get("/config")

    def put_config(self, cfg: dict) -> None:
        self.put("/config", cfg)

    def pending_devices(self) -> dict:
        return self.get("/cluster/pending/devices")

    def db_completion(self, device: str, folder: str) -> dict:
        return self.get("/db/completion", {"device": device, "folder": folder})

    def db_file(self, folder: str, relpath: str) -> dict:
        # Returns {"global": {...}, "local": {...}, "availability": [deviceID, ...]}
        # where availability lists devices holding the current global version.
        return self.get("/db/file", {"folder": folder, "file": relpath})

    def scan(self, folder: str) -> None:
        self.post("/db/scan", {"folder": folder})

    def shutdown(self) -> None:
        self.post("/system/shutdown")


def wait_for_api(api: SyncthingAPI, timeout: float = 30.0) -> None:
    """Block until the API answers (syncthing takes a moment to boot)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            api.ping()
            return
        except Exception:
            time.sleep(0.25)
    raise TimeoutError(f"syncthing API did not come up within {timeout}s")
