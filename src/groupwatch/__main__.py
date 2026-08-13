"""Entry point: ``python -m groupwatch`` or the ``groupwatch`` command."""

import sys

from groupwatch.app import run


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
