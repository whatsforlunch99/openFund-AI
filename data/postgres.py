"""PostgreSQL data management: create schema and seed demo data.

Uses mcp.tools.sql_tool for all queries. For one-off queries use the CLI
(data cli sql) or sql_tool.run_query directly.
"""

from __future__ import annotations

import os

from data.env_loader import load_dotenv as _load_dotenv


def populate_postgres() -> tuple[bool, str]:
    """Create funds table (if not exists) and insert NVDA row. Uses DATABASE_URL."""
    _load_dotenv()
    if not os.environ.get("DATABASE_URL"):
        return False, "DATABASE_URL not set; skipping PostgreSQL."
    from mcp.tools import sql_tool

    ddl = """
    CREATE TABLE IF NOT EXISTS funds (
        symbol VARCHAR(32) PRIMARY KEY,
        name VARCHAR(256)
    )
    """
    r = sql_tool.run_query(ddl)
    if r.get("error"):
        return False, f"PostgreSQL DDL failed: {r['error']}"

    insert = """
    INSERT INTO funds (symbol, name) VALUES ('NVDA', 'NVIDIA Corporation')
    ON CONFLICT (symbol) DO UPDATE SET name = EXCLUDED.name
    """
    r = sql_tool.run_query(insert)
    if r.get("error"):
        return False, f"PostgreSQL insert failed: {r['error']}"
    return True, "PostgreSQL: created/updated funds, inserted NVDA."
