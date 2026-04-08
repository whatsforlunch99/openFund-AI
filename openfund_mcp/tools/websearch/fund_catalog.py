"""Fund catalog search backed by PostgreSQL symbols tables."""

from __future__ import annotations

import logging
import os
from typing import Any

from openfund_mcp.tools._shared.time import now_iso_utc
from openfund_mcp.tools.sql import postgres as sql_postgres

logger = logging.getLogger(__name__)

_PREFERRED_TABLES = ("index_symbol_map", "fund_info", "yahoo_quote_metrics")


def _list_symbol_tables() -> list[str]:
    info = sql_postgres.run_query(
        """
        SELECT table_name
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND lower(column_name) IN ('symbol', 'ticker')
        GROUP BY table_name
        ORDER BY table_name
        """
    )
    if "error" in info:
        return []
    return [str(r.get("table_name") or "") for r in (info.get("rows") or []) if r.get("table_name")]


def _table_columns(table_name: str) -> set[str]:
    info = sql_postgres.run_query(
        """
        SELECT lower(column_name) AS column_name
        FROM information_schema.columns
        WHERE table_schema = current_schema() AND table_name = %(table)s
        """,
        {"table": table_name},
    )
    if "error" in info:
        return set()
    return {str(r.get("column_name") or "") for r in (info.get("rows") or []) if r.get("column_name")}


def _choose_column(cols: set[str], options: tuple[str, ...], fallback: str) -> str:
    for c in options:
        if c in cols:
            return c
    return fallback


def _search_one_table(table_name: str, query: str, limit: int) -> dict:
    cols = _table_columns(table_name)
    if "symbol" in cols:
        symbol_col = "symbol"
    elif "ticker" in cols:
        symbol_col = "ticker"
    else:
        return {"matches": []}

    name_col = _choose_column(cols, ("name", "longname", "long_name", "shortname", "short_name"), symbol_col)
    asset_col = _choose_column(cols, ("asset_class", "quoteType", "quotetype", "category"), "")
    exchange_col = _choose_column(cols, ("exchange", "fullExchangeName", "fullexchangename"), "")

    select_parts = [f"{symbol_col} AS symbol", f"{name_col} AS name"]
    if asset_col:
        select_parts.append(f"{asset_col} AS asset_class")
    else:
        select_parts.append("NULL::text AS asset_class")
    if exchange_col:
        select_parts.append(f"{exchange_col} AS exchange")
    else:
        select_parts.append("NULL::text AS exchange")

    q = f"""
    SELECT {", ".join(select_parts)}
    FROM {table_name}
    WHERE CAST({symbol_col} AS text) ILIKE %(q)s
       OR CAST({name_col} AS text) ILIKE %(q)s
    ORDER BY CAST({symbol_col} AS text)
    LIMIT %(limit)s
    """
    res = sql_postgres.run_query(q, {"q": f"%{query}%", "limit": limit})
    if "error" in res:
        return {"matches": [], "error": res["error"]}
    return {"matches": res.get("rows") or []}


def search(payload: dict) -> dict:
    """Search funds/symbols from DB tables using query|name and limit."""
    query = (payload.get("query") or payload.get("name") or "").strip()
    limit = int(payload["limit"]) if "limit" in payload and payload["limit"] is not None else 10
    if not query:
        return {"error": "Missing required 'query' or 'name'", "timestamp": now_iso_utc()}
    if not os.environ.get("DATABASE_URL"):
        return {"error": "DATABASE_URL not set", "timestamp": now_iso_utc()}

    tables = _list_symbol_tables()
    ordered = [t for t in _PREFERRED_TABLES if t in tables] + [t for t in tables if t not in _PREFERRED_TABLES]
    seen: set[str] = set()
    out: list[dict[str, Any]] = []

    for table in ordered:
        remaining = max(0, limit - len(out))
        if remaining <= 0:
            break
        part = _search_one_table(table, query, remaining)
        for row in part.get("matches", []):
            sym = str(row.get("symbol") or "").strip().upper()
            if not sym or sym in seen:
                continue
            seen.add(sym)
            out.append(
                {
                    "symbol": sym,
                    "name": str(row.get("name") or ""),
                    "asset_class": row.get("asset_class"),
                    "exchange": row.get("exchange"),
                }
            )
    return {"matches": out[:limit], "timestamp": now_iso_utc(), "source": "PostgreSQL"}

