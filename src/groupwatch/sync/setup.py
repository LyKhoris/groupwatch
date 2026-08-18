"""Group setup: create/join a group, one-way folder wiring, device auto-approve.

Topology (AGENTS.md §3.2): the leader's folder is ``sendonly`` and every
friend's is ``receiveonly`` — with exactly one writer, sync conflicts are
structurally impossible.
"""

from __future__ import annotations

import threading
from pathlib import Path

from groupwatch.invite import Invite
from groupwatch.sync.api import SyncthingAPI

GROUP_FOLDER_ID = "groupwatch-library"
GROUP_FOLDER_LABEL = "groupwatch library"

# Not Syncthing's default 22000 — avoids clashing with a user's own install.
DEFAULT_LISTEN_PORT = 22999


def _mutate_config(api: SyncthingAPI, fn) -> None:
    cfg = api.config()
    fn(cfg)
    api.put_config(cfg)


def set_device_name(api: SyncthingAPI, name: str) -> None:
    """The name shown to the group ('Waiting for Sam (60%)…')."""
    my_id = api.my_id()

    def m(cfg: dict) -> None:
        for d in cfg.get("devices", []):
            if d.get("deviceID") == my_id:
                d["name"] = name

    _mutate_config(api, m)


def configure_network(api: SyncthingAPI, *, listen_port: int = DEFAULT_LISTEN_PORT,
                      discovery: bool = True) -> None:
    """Set listen ports and discovery.

    discovery=True keeps global discovery + relays on — that's Syncthing's NAT
    traversal, which is why file sync needs no router configuration. Tests use
    discovery=False with explicit ports to run two instances on one machine.
    """

    def m(cfg: dict) -> None:
        opts = cfg.setdefault("options", {})
        opts["listenAddresses"] = [
            f"tcp://0.0.0.0:{listen_port}",
            f"quic://0.0.0.0:{listen_port}",
            "dynamic",  # relays
        ]
        opts["globalAnnounceEnabled"] = discovery
        opts["relaysEnabled"] = discovery
        opts["natEnabled"] = discovery
        opts["localAnnounceEnabled"] = discovery
        if not discovery:
            opts["reconnectIntervalS"] = 5  # fast reconnects for tests

    _mutate_config(api, m)


def add_device(api: SyncthingAPI, device_id: str, name: str = "",
               addresses=("dynamic",)) -> None:
    def m(cfg: dict) -> None:
        devices = cfg.setdefault("devices", [])
        if any(d.get("deviceID") == device_id for d in devices):
            return
        devices.append({
            "deviceID": device_id,
            "name": name,
            "addresses": list(addresses),
            "compression": "metadata",
            "introducer": False,
            "paused": False,
            "autoAcceptFolders": False,
        })

    _mutate_config(api, m)


def add_folder(api: SyncthingAPI, *, folder_id: str, path: Path, folder_type: str,
               device_ids: list[str]) -> None:
    def m(cfg: dict) -> None:
        folders = cfg.setdefault("folders", [])
        if any(f.get("id") == folder_id for f in folders):
            return
        folders.append({
            "id": folder_id,
            "label": GROUP_FOLDER_LABEL,
            "path": str(path),
            "type": folder_type,  # "sendonly" (leader) | "receiveonly" (friends)
            "devices": [{"deviceID": d} for d in device_ids],
            "filesystemType": "basic",
            "rescanIntervalS": 30,
            "fsWatcherEnabled": True,  # new episodes start syncing immediately
            "fsWatcherDelayS": 2,
            "ignorePerms": True,
        })

    _mutate_config(api, m)


def share_folder_with(api: SyncthingAPI, folder_id: str, device_id: str) -> None:
    def m(cfg: dict) -> None:
        for f in cfg.get("folders", []):
            if f.get("id") == folder_id:
                devices = f.setdefault("devices", [])
                if not any(d.get("deviceID") == device_id for d in devices):
                    devices.append({"deviceID": device_id})

    _mutate_config(api, m)


def create_group(api: SyncthingAPI, folder_path: Path, name: str, *,
                 server_host: str = "", server_port: int = 8999,
                 room: str = "groupwatch") -> Invite:
    """Leader flow: send-only library folder + an invite to hand out."""
    set_device_name(api, name)
    my_id = api.my_id()
    add_folder(api, folder_id=GROUP_FOLDER_ID, path=folder_path,
               folder_type="sendonly", device_ids=[my_id])
    return Invite(
        leader_device_id=my_id,
        folder_id=GROUP_FOLDER_ID,
        server_host=server_host,
        server_port=server_port,
        room=room,
        leader_name=name,
    )


def join_group(api: SyncthingAPI, invite: Invite, folder_path: Path, name: str, *,
               leader_addresses=("dynamic",)) -> None:
    """Friend flow: add the leader's device + a receive-only copy of the folder.

    The leader's app auto-approves the friend's device (below), so the friend
    never clicks "approve" anywhere.
    """
    set_device_name(api, name)
    add_device(api, invite.leader_device_id, name=invite.leader_name,
               addresses=leader_addresses)
    add_folder(api, folder_id=invite.folder_id, path=folder_path,
               folder_type="receiveonly", device_ids=[invite.leader_device_id])


def autoapprove_once(api: SyncthingAPI, folder_id: str) -> list[str]:
    """Approve every device asking to connect and share the folder with it.

    Returns the newly approved device IDs.
    """
    approved = []
    for device_id, info in api.pending_devices().items():
        add_device(api, device_id, name=info.get("name", ""))
        share_folder_with(api, folder_id, device_id)
        approved.append(device_id)
    return approved


def autoapprove_loop(api: SyncthingAPI, folder_id: str, stop: threading.Event,
                     interval: float = 3.0) -> None:
    """Leader-side background loop: friends are approved automatically."""
    while not stop.is_set():
        try:
            autoapprove_once(api, folder_id)
        except Exception:
            pass  # syncthing briefly reloads after config changes; retry next tick
        stop.wait(interval)
