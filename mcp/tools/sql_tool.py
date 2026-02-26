"""SQL query execution (MCP tool)."""

from __future__ import annotations

import os
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
    if not os.environ.get("DATABASE_URL"):
        # No database configured; return mock so tests and E2E run without Postgres
        return {
            "rows": [{"id": 1, "value": "mock"}],
            "schema": ["id", "value"],
            "params": params or {},
        }
    raise NotImplementedError("Real PostgreSQL backend not implemented")
