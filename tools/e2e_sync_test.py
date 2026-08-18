#!/usr/bin/env python3
"""Phase 1 exit-criteria test (AGENTS.md §7): two machines sync a folder
end-to-end with zero Syncthing UI visible.

Simulates leader + friend on localhost with separate Syncthing homes, ports,
and library dirs:

    leader: create group -> invite code
    friend: paste invite -> join
    leader: auto-approves the friend's device (no human clicks)
    leader drops a file -> it must appear, byte-identical, on the friend

Run from the repo root:  python tools/e2e_sync_test.py
Requires the pinned Syncthing binary: python tools/fetch_syncthing.py
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from groupwatch.platform.paths import syncthing_binary
from groupwatch.sync import readiness, setup as stsetup
from groupwatch.sync.process import SyncthingEngine

GUI_A, GUI_B = 18394, 18395
LISTEN_A, LISTEN_B = 22100, 22200


def main() -> int:
    binary = syncthing_binary()
    if not binary.exists():
        print("[e2e] syncthing binary missing — run: python tools/fetch_syncthing.py")
        return 1

    tmp = Path(tempfile.mkdtemp(prefix="groupwatch-e2e-"))
    a_home, a_lib = tmp / "a-home", tmp / "a-library"
    b_home, b_lib = tmp / "b-home", tmp / "b-library"
    a_lib.mkdir()
    b_lib.mkdir()

    leader = SyncthingEngine(binary, a_home, GUI_A)
    friend = SyncthingEngine(binary, b_home, GUI_B)
    stop = threading.Event()
    ok = False
    try:
        print("[e2e] starting leader...")
        api_a = leader.start()
        stsetup.configure_network(api_a, listen_port=LISTEN_A, discovery=False)
        invite = stsetup.create_group(api_a, a_lib, name="leader")
        print(f"[e2e] leader up. invite code: {invite.encode()[:50]}...")

        print("[e2e] starting friend (joins via invite)...")
        api_b = friend.start()
        stsetup.configure_network(api_b, listen_port=LISTEN_B, discovery=False)
        stsetup.join_group(api_b, invite, b_lib, name="friend",
                           leader_addresses=(f"tcp://127.0.0.1:{LISTEN_A}",))

        threading.Thread(target=stsetup.autoapprove_loop,
                         args=(api_a, invite.folder_id, stop),
                         kwargs={"interval": 1.0}, daemon=True).start()

        print("[e2e] waiting for the devices to connect...")
        payload = b"groupwatch e2e payload " * 4096  # ~100 KiB
        time.sleep(5)
        (a_lib / "episode01.mkv").write_bytes(payload)
        api_a.scan(invite.folder_id)
        print("[e2e] dropped episode01.mkv into the leader's library")

        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            target = b_lib / "episode01.mkv"
            if target.exists() and target.read_bytes() == payload:
                ok = True
                break
            time.sleep(1)

        if ok:
            friend_id = api_b.my_id()
            time.sleep(2)  # let completion state settle
            completion = readiness.folder_completion(api_a, friend_id, invite.folder_id)
            synced = readiness.file_synced(api_a, friend_id, invite.folder_id, "episode01.mkv")
            print(f"[e2e] friend completion as seen by leader: {completion:.0f}%")
            print(f"[e2e] leader sees friend's copy of the file as synced: {synced}")
            ok = ok and completion == 100.0 and synced
    finally:
        stop.set()
        friend.stop()
        leader.stop()
        shutil.rmtree(tmp, ignore_errors=True)

    if ok:
        print("[e2e] PASS — file synced leader -> friend, no Syncthing UI involved")
        return 0
    print("[e2e] FAIL — file did not arrive in time")
    return 1


if __name__ == "__main__":
    sys.exit(main())
