#!/usr/bin/env python3
"""Download the pinned Syncthing binary for bundling with groupwatch.

Stdlib-only dev tool (run from the repo root):

    python tools/fetch_syncthing.py                    # current platform
    python tools/fetch_syncthing.py windows-amd64      # explicit target

Fetches the version pinned in vendor/syncthing/VERSION into
vendor/syncthing/<platform>/ and grabs the upstream LICENSE (MPL-2.0).
Binaries are gitignored; CI runs this before packaging (AGENTS.md §6).
"""

from __future__ import annotations

import io
import shutil
import stat
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor" / "syncthing"
VERSION = (VENDOR / "VERSION").read_text(encoding="utf-8").strip()

BASE = f"https://github.com/syncthing/syncthing/releases/download/v{VERSION}"
LICENSE_URL = f"https://raw.githubusercontent.com/syncthing/syncthing/v{VERSION}/LICENSE"
ARCHIVE_EXT = {"windows-amd64": "zip", "linux-amd64": "tar.gz"}


def current_platform() -> str:
    if sys.platform.startswith("win"):
        return "windows-amd64"
    if sys.platform.startswith("linux"):
        return "linux-amd64"
    raise SystemExit(f"unsupported platform: {sys.platform}")


def fetch(url: str) -> bytes:
    print(f"  downloading {url}")
    with urllib.request.urlopen(url, timeout=120) as resp:
        return resp.read()


def extract_binary(archive: bytes, platform: str, dest: Path) -> None:
    ext = ARCHIVE_EXT[platform]
    binary_name = "syncthing.exe" if platform.startswith("windows") else "syncthing"
    prefix = f"syncthing-{platform}-v{VERSION}"
    dest.mkdir(parents=True, exist_ok=True)
    out = dest / binary_name

    if ext == "zip":
        with zipfile.ZipFile(io.BytesIO(archive)) as zf:
            with zf.open(f"{prefix}/{binary_name}") as src, out.open("wb") as dst:
                shutil.copyfileobj(src, dst)
    else:
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tf:
            src = tf.extractfile(f"{prefix}/{binary_name}")
            assert src is not None
            with out.open("wb") as dst:
                shutil.copyfileobj(src, dst)

    out.chmod(out.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    print(f"  extracted {out}")


def main() -> None:
    platform = sys.argv[1] if len(sys.argv) > 1 else current_platform()
    if platform not in ARCHIVE_EXT:
        raise SystemExit(f"unknown platform {platform!r}; expected one of {sorted(ARCHIVE_EXT)}")

    print(f"fetching syncthing v{VERSION} for {platform}")
    archive = fetch(f"{BASE}/syncthing-{platform}-v{VERSION}.{ARCHIVE_EXT[platform]}")
    extract_binary(archive, platform, VENDOR / platform)

    license_path = VENDOR / "LICENSE"
    if not license_path.exists():
        license_path.write_bytes(fetch(LICENSE_URL))
        print(f"  wrote {license_path}")

    print("done")


if __name__ == "__main__":
    main()
