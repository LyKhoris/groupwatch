"""groupwatch service orchestration.

Phase 0: tray shell only. The sync engine (Phase 1), Syncplay engine
(Phase 2), full UI (Phase 3), and readiness gate (Phase 4) plug in here as
they land. See AGENTS.md §7 for the roadmap.
"""

from __future__ import annotations

import argparse

from groupwatch import __version__
from groupwatch.config import APP_NAME


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=APP_NAME,
        description="Watch synced videos together with friends.",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="print the version and exit (also used as a build smoke test)",
    )
    return parser


def run(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.version:
        print(f"{APP_NAME} {__version__}")
        return 0

    # Imported lazily so `--version` works without a display / Qt plugins.
    from groupwatch.ui.tray import run_tray_app

    return run_tray_app()
