"""Shared time helpers for tool modules."""

from __future__ import annotations

from datetime import datetime, timezone


def now_iso_utc() -> str:
    """Return UTC timestamp in project-standard ISO format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

