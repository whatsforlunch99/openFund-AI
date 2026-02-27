"""Populate PostgreSQL, Neo4j, and Milvus with demo data matching demo_data.py.

Seeds data so that when demo=False the app can use real backends and return
the same logical content as the static demo (NVDA/NVIDIA, two vector docs,
KG nodes/edges). Run with: python -m data populate.

Idempotency: Postgres uses ON CONFLICT; Neo4j uses MERGE; Milvus deletes
by source == "demo" before indexing so re-runs do not duplicate docs.

This module is a thin orchestrator only; backend logic lives in mcp.tools
(sql_tool.populate_demo, kg_tool.populate_demo, vector_tool.populate_demo).
"""

from __future__ import annotations

import sys

from data.env_loader import load_dotenv as _load_dotenv
from mcp.tools import kg_tool
from mcp.tools import sql_tool
from mcp.tools import vector_tool


def run_populate() -> int:
    """Load .env, run Postgres, Neo4j, and Milvus populate; print status; return 0."""
    _load_dotenv()

    results = []
    results.append(sql_tool.populate_demo())
    results.append(kg_tool.populate_demo())
    results.append(vector_tool.populate_demo())

    for ok, msg in results:
        print(msg, file=sys.stdout if ok else sys.stderr)
    if not any(ok for ok, _ in results):
        print(
            "No backends configured. Set DATABASE_URL, NEO4J_URI, and/or MILVUS_URI in .env.",
            file=sys.stderr,
        )
    return 0
