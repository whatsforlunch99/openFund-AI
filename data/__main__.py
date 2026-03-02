"""Entry point for legacy `python -m data` command."""

from data.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
