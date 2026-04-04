"""SQL query execution (MCP tool)."""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Safe identifier for table/schema names: alphanumeric and underscore only.
_IDENTIFIER_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

_DB_UNSET = "DATABASE_URL not set"


def _get_connection():
    """Return a psycopg2 connection when DATABASE_URL is set. Lazy import."""
    try:
        import psycopg2  # type: ignore[import-untyped]
        from psycopg2.extras import RealDictCursor  # type: ignore[import-untyped]
    except ImportError:
        return (
            None,
            "PostgreSQL driver not installed. Run: pip install -e '.[backends]'",
        )
    url = os.environ.get("DATABASE_URL")
    if not url:
        return None, None
    try:
        conn = psycopg2.connect(url, cursor_factory=RealDictCursor)
        return conn, None
    except Exception as e:
        logger.exception("sql_tool: failed to connect to PostgreSQL: %s", e)
        return None, f"PostgreSQL connection failed: {e}"


def _normalize_sql_bind_params(params: Any) -> Optional[dict[str, Any] | tuple[Any, ...]]:
    """Accept dict (named), tuple, or list (positional for %s) from LLM payloads."""
    if params is None:
        return None
    if isinstance(params, dict):
        return params
    if isinstance(params, tuple):
        return params
    if isinstance(params, list):
        return tuple(params)
    return params


def run_query(query: str, params: Optional[dict[str, Any] | tuple[Any, ...] | list[Any]] = None) -> dict:
    """
    Execute a SQL query with optional parameters.

    Args:
        query: SQL query string. Use %s or %(name)s placeholders for psycopg2.
        params: Optional query parameters (tuple for positional, dict for named).

    Returns:
        Dict with rows (list of dicts), schema (column names), and params.
        When DATABASE_URL is unset, returns {"error": "DATABASE_URL not set", ...}.
    """
    params = _normalize_sql_bind_params(params)
    if not os.environ.get("DATABASE_URL"):
        return {
            "error": _DB_UNSET,
            "rows": [],
            "schema": [],
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
            except Exception as rollback_err:
                logger.debug("Rollback failed: %s", rollback_err)
        logger.exception("sql_tool.run_query failed: %s", e)
        return {"error": str(e), "rows": [], "schema": [], "params": params or {}}
    finally:
        if conn:
            try:
                conn.close()
            except Exception as close_err:
                logger.debug("Close failed: %s", close_err)


def list_tables() -> dict:
    """
    List tables in the database (schemas other than pg_catalog, information_schema).

    Returns:
        Dict with rows (table_schema, table_name) and schema. When DATABASE_URL unset, returns error.
    """
    if not os.environ.get("DATABASE_URL"):
        return {
            "error": _DB_UNSET,
            "rows": [],
            "schema": [],
            "params": {},
        }
    query = """
    SELECT table_schema, table_name
    FROM information_schema.tables
    WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
    ORDER BY table_schema, table_name
    """
    return run_query(query)


def get_table_schema(table_name: str) -> dict:
    """
    Return column names, types, nullability (and default) for a table.

    Args:
        table_name: Table name, or schema.table. Must be a valid identifier (no SQL injection).

    Returns:
        Dict with rows (column_name, data_type, is_nullable, column_default) and schema.
    """
    if not table_name or not table_name.strip():
        return {"error": "table_name is required", "rows": [], "schema": []}
    parts = table_name.strip().split(".", 1)
    if len(parts) == 2:
        schema_part, table_part = parts[0].strip(), parts[1].strip()
        if not _IDENTIFIER_RE.match(schema_part) or not _IDENTIFIER_RE.match(
            table_part
        ):
            return {
                "error": "table_name must be a valid identifier or schema.identifier",
                "rows": [],
                "schema": [],
            }
        query = """
        SELECT column_name, data_type, is_nullable, column_default
        FROM information_schema.columns
        WHERE table_schema = %(schema)s AND table_name = %(table)s
        ORDER BY ordinal_position
        """
        return run_query(query, {"schema": schema_part, "table": table_part})
    if not _IDENTIFIER_RE.match(table_name.strip()):
        return {
            "error": "table_name must contain only letters, numbers, and underscores",
            "rows": [],
            "schema": [],
        }
    query = """
    SELECT column_name, data_type, is_nullable, column_default
    FROM information_schema.columns
    WHERE table_schema = current_schema() AND table_name = %(table)s
    ORDER BY ordinal_position
    """
    return run_query(query, {"table": table_name.strip()})


def _is_read_only_query(query: str) -> bool:
    """Return True if query looks like SELECT or EXPLAIN (safe for explain/export)."""
    q = (query or "").strip().upper()
    return q.startswith("SELECT") or q.startswith("EXPLAIN")


def explain_query(
    query: str,
    params: Optional[dict[str, Any] | tuple[Any, ...] | list[Any]] = None,
    analyze: bool = False,
) -> dict:
    """
    Run EXPLAIN or EXPLAIN ANALYZE for a read-only query and return the plan rows.

    Args:
        query: SQL query to explain (must start with SELECT or EXPLAIN for safety).
        params: Optional query parameters.
        analyze: If True, run EXPLAIN ANALYZE (executes the query).

    Returns:
        Dict with plan (list of plan rows as dicts), schema, params.
        When DATABASE_URL is unset, returns {"error": "DATABASE_URL not set", ...}.
    """
    params = _normalize_sql_bind_params(params)
    if not _is_read_only_query(query):
        return {
            "error": "Only SELECT or EXPLAIN queries are allowed for explain_query.",
            "plan": [],
            "schema": [],
            "params": params or {},
        }
    prefix = "EXPLAIN (ANALYZE true, FORMAT TEXT) " if analyze else "EXPLAIN "
    explained = prefix + query
    if not os.environ.get("DATABASE_URL"):
        return {
            "error": _DB_UNSET,
            "plan": [],
            "schema": [],
            "params": params or {},
        }
    conn, err = _get_connection()
    if conn is None:
        return {
            "error": err or "PostgreSQL not available.",
            "plan": [],
            "schema": [],
            "params": params or {},
        }
    try:
        with conn.cursor() as cur:
            if params:
                cur.execute(explained, params)
            else:
                cur.execute(explained)
            if cur.description:
                rows = cur.fetchall()
                rows = [dict(r) for r in rows] if rows else []
                schema = list(rows[0].keys()) if rows else []
            else:
                rows = []
                schema = []
        conn.rollback()
        return {"plan": rows, "schema": schema, "params": params or {}}
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        logger.exception("sql_tool.explain_query failed: %s", e)
        return {"error": str(e), "plan": [], "schema": [], "params": params or {}}
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def export_results(
    query: str,
    params: Optional[dict[str, Any] | tuple[Any, ...] | list[Any]] = None,
    format: str = "json",
    row_limit: int = 1000,
) -> dict:
    """
    Execute a read-only query, apply row_limit, and return results as JSON (list of dicts) or CSV string.

    Args:
        query: SQL query (must start with SELECT for safety).
        params: Optional query parameters.
        format: "json" or "csv".
        row_limit: Maximum rows to return (default 1000).

    Returns:
        For format "json": {"data": [dict, ...], "schema": [...], "row_count": n}.
        For format "csv": {"data": "csv string", "schema": [...], "row_count": n}.
        When DATABASE_URL is unset, returns {"error": "DATABASE_URL not set", ...}.
    """
    params = _normalize_sql_bind_params(params)
    if not query or not query.strip().upper().startswith("SELECT"):
        return {
            "error": "Only SELECT queries are allowed for export_results.",
            "data": [] if format == "json" else "",
            "schema": [],
            "row_count": 0,
        }
    if format not in ("json", "csv"):
        return {
            "error": "format must be 'json' or 'csv'.",
            "data": [] if format == "json" else "",
            "schema": [],
            "row_count": 0,
        }
    if not os.environ.get("DATABASE_URL"):
        return {
            "error": _DB_UNSET,
            "data": [] if format == "json" else "",
            "schema": [],
            "row_count": 0,
        }
    conn, err = _get_connection()
    if conn is None:
        return {
            "error": err or "PostgreSQL not available.",
            "data": [] if format == "json" else "",
            "schema": [],
            "row_count": 0,
        }
    limited = query.strip().rstrip(";")
    if "LIMIT" not in limited.upper():
        limited += f" LIMIT {int(row_limit)}"
    try:
        with conn.cursor() as cur:
            if params:
                cur.execute(limited, params)
            else:
                cur.execute(limited)
            if cur.description:
                rows = cur.fetchall()
                rows = [dict(r) for r in rows] if rows else []
                schema = list(rows[0].keys()) if rows else []
            else:
                rows = []
                schema = []
        conn.commit()
        if format == "csv":
            import csv
            from io import StringIO
            buf = StringIO()
            if schema and rows:
                w = csv.DictWriter(buf, fieldnames=schema)
                w.writeheader()
                w.writerows(rows)
            return {"data": buf.getvalue(), "schema": schema, "row_count": len(rows)}
        return {"data": rows, "schema": schema, "row_count": len(rows)}
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        logger.exception("sql_tool.export_results failed: %s", e)
        return {
            "error": str(e),
            "data": [] if format == "json" else "",
            "schema": [],
            "row_count": 0,
        }
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def connection_health_check() -> dict:
    """
    Execute SELECT 1 to verify PostgreSQL connectivity.

    Returns:
        {"ok": true} on success; {"ok": false, "error": "..."} on failure.
        When DATABASE_URL is unset returns {"ok": false, "error": "DATABASE_URL not set"}.
    """
    if not os.environ.get("DATABASE_URL"):
        return {"ok": False, "error": "DATABASE_URL not set"}
    conn, err = _get_connection()
    if conn is None:
        return {"ok": False, "error": err or "PostgreSQL not available"}
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        conn.close()
        return {"ok": True}
    except Exception as e:
        logger.debug("sql_tool.connection_health_check failed: %s", e)
        return {"ok": False, "error": str(e)}
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def _coerce_analyze(x: Any) -> bool:
    """Coerce payload 'analyze' to True only when explicitly True (for explain_query)."""
    return x is True


# MCP registration: (name, func_name, required_keys, arg_specs, result_key).
TOOL_SPECS: list[tuple[str, str, list[str], list, str | None]] = [
    ("sql_tool.run_query", "run_query", ["query"], [("query", ["query"], "", None), ("params", ["params"], None, _normalize_sql_bind_params)], None),
    ("sql_tool.explain_query", "explain_query", [], [
        ("query", ["query"], "", None),
        ("params", ["params"], None, _normalize_sql_bind_params),
        ("analyze", ["analyze"], False, _coerce_analyze),
    ], None),
    ("sql_tool.export_results", "export_results", [], [
        ("query", ["query"], "", None),
        ("params", ["params"], None, _normalize_sql_bind_params),
        ("format", ["format"], "json", None),
        ("row_limit", ["row_limit"], 1000, int),
    ], None),
    ("sql_tool.connection_health_check", "connection_health_check", [], [], None),
]
