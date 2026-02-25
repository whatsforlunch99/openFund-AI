"""SQL query execution (MCP tool)."""

from __future__ import annotations

from typing import Optional


def run_query(query: str, params: Optional[dict] = None) -> dict:
    """
    Execute a SQL query with optional parameters.

    Args:
        query: SQL query string.
        params: Optional query parameters.

    Returns:
        Dict with rows and optional schema.
    """
    raise NotImplementedError
