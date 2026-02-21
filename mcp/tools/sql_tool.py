"""SQL query execution (MCP tool)."""

from typing import Dict, Optional


def run_query(query: str, params: Optional[Dict] = None) -> dict:
    """
    Execute a SQL query with optional parameters.

    Args:
        query: SQL query string.
        params: Optional query parameters.

    Returns:
        Dict with rows and optional schema.
    """
    raise NotImplementedError
