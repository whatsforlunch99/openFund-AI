"""Legacy CLI wrapper; delegates to unified data_manager CLI."""

from __future__ import annotations

import sys

from data_manager.__main__ import main as data_manager_main


def main() -> int:
    """Forward legacy `data` CLI arguments to `data_manager`."""
    return data_manager_main(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
