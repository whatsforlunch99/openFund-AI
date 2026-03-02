"""Legacy compatibility package forwarding `python -m data` to `data_manager`."""

from data.cli import main
from data.populate import run_populate

__all__ = ["main", "run_populate"]
