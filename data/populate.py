"""Populate PostgreSQL, Neo4j, and Milvus with demo data matching demo_data.py.

Seeds data so that when demo=False the app can use real backends and return
the same logical content as the static demo (NVDA/NVIDIA, two vector docs,
KG nodes/edges). Run with: python -m data populate.

Idempotency: Postgres uses ON CONFLICT; Neo4j uses MERGE; Milvus deletes
by source == "demo" before indexing so re-runs do not duplicate docs.

This module is a thin orchestrator only; backend logic lives in
data.postgres, data.neo4j, and data.milvus.
"""

from __future__ import annotations

import sys

from data.env_loader import load_dotenv as _load_dotenv
from data.postgres import populate_postgres
from data.neo4j import populate_neo4j
from data.milvus import populate_milvus


def run_populate() -> int:
    """Load .env, run Postgres, Neo4j, and Milvus populate; print status; return 0."""
    _load_dotenv()

    results = []
    results.append(populate_postgres())
    results.append(populate_neo4j())
    results.append(populate_milvus())

    for ok, msg in results:
        print(msg, file=sys.stdout if ok else sys.stderr)
    if not any(ok for ok, _ in results):
        print(
            "No backends configured. Set DATABASE_URL, NEO4J_URI, and/or MILVUS_URI in .env.",
            file=sys.stderr,
        )
    return 0
