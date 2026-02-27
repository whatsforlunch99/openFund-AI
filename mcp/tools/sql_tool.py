"""SQL query execution (MCP tool)."""

from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


def _get_connection():
    """Return a psycopg2 connection when DATABASE_URL is set. Lazy import."""
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
    except ImportError:
        return None, "PostgreSQL driver not installed. Run: pip install -e '.[backends]'"
    url = os.environ.get("DATABASE_URL")
    if not url:
        return None, None
    try:
        conn = psycopg2.connect(url, cursor_factory=RealDictCursor)
        return conn, None
    except Exception as e:
        logger.exception("sql_tool: failed to connect to PostgreSQL: %s", e)
        return None, f"PostgreSQL connection failed: {e}"


def run_query(query: str, params: Optional[dict] = None) -> dict:
    """
    Execute a SQL query with optional parameters.

    Args:
        query: SQL query string. Use %s or %(name)s placeholders for psycopg2.
        params: Optional query parameters (tuple for positional, dict for named).

    Returns:
        Dict with rows (list of dicts), schema (column names), and params.
        When DATABASE_URL is unset, returns mock data. On error returns {"error": "..."}.
    """
    if not os.environ.get("DATABASE_URL"):
        return {
            "rows": [{"id": 1, "value": "mock"}],
            "schema": ["id", "value"],
            "params": params or {},
        }
    conn, err = _get_connection()
    if conn is None:
        return {
            "error": err or "PostgreSQL driver not available or connection failed.",
            "rows": [],
            "schema": [],
            "params": params or {},
        }
    try:
        with conn.cursor() as cur:
            if params:
                cur.execute(query, params)
            else:
                cur.execute(query)
            # DDL/INSERT/UPDATE/DELETE without RETURNING have no result set; fetchall() would raise.
            if cur.description:
                rows = cur.fetchall()
                rows = [dict(r) for r in rows] if rows else []
                schema = list(rows[0].keys()) if rows else []
            else:
                rows = []
                schema = []
        conn.commit()
        return {"rows": rows, "schema": schema, "params": params or {}}
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        logger.exception("sql_tool.run_query failed: %s", e)
        return {"error": str(e), "rows": [], "schema": [], "params": params or {}}
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass
