"""Populate PostgreSQL, Neo4j, and Milvus with demo data matching demo_data.py.

Seeds data so that when demo=False the app can use real backends and return
the same logical content as the static demo (NVDA/NVIDIA, two vector docs,
KG nodes/edges). Run with: python -m data populate.

Idempotency: Postgres uses ON CONFLICT; Neo4j uses MERGE; Milvus deletes
by source == "demo" before indexing so re-runs do not duplicate docs.
"""

from __future__ import annotations

import logging
import os
import sys

logger = logging.getLogger(__name__)


def _load_dotenv() -> None:
    """Load .env so env vars are set before using tools."""
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass


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


def populate_neo4j() -> tuple[bool, str]:
    """Create Company/Sector nodes and IN_SECTOR edge for NVDA. Uses NEO4J_URI."""
    _load_dotenv()
    if not os.environ.get("NEO4J_URI"):
        return False, "NEO4J_URI not set; skipping Neo4j."
    from mcp.tools import kg_tool

    # MERGE so re-runs are idempotent. Nodes need id (or name) for get_relations(entity) to match.
    cypher = """
    MERGE (e:Company {id: 'NVDA'})
    MERGE (s:Sector {id: 'Technology'})
    MERGE (e)-[:IN_SECTOR]->(s)
    """
    r = kg_tool.query_graph(cypher)
    if r.get("error"):
        return False, f"Neo4j failed: {r['error']}"
    return True, "Neo4j: merged Company NVDA, Sector Technology, IN_SECTOR edge."


def populate_milvus() -> tuple[bool, str]:
    """Index two demo documents (content from demo_data). Uses MILVUS_URI."""
    _load_dotenv()
    if not os.environ.get("MILVUS_URI"):
        return False, "MILVUS_URI not set; skipping Milvus."
    from mcp.tools import vector_tool

    # Content from demo_data.VECTOR_SEARCH_RESPONSE; use source so we can delete before re-index.
    docs = [
        {
            "content": "NVIDIA (NVDA) is a leading semiconductor company focused on graphics and AI. Suitable for long-term growth investors; volatility can be high.",
            "fund_id": "NVDA",
            "source": "demo",
        },
        {
            "content": "NVDA fundamentals: Technology sector, strong revenue growth. Not a recommendation to buy or sell.",
            "fund_id": "NVDA",
            "source": "demo",
        },
    ]

    # Idempotent: delete existing demo docs by source before indexing.
    out = vector_tool.delete_by_expr('source == "demo"')
    if out.get("error"):
        # Ignore delete error (e.g. empty collection or first run); proceed to index.
        logger.debug("Milvus delete_by_expr (pre-index): %s", out.get("error"))
    out = vector_tool.index_documents(docs)
    if out.get("status") == "error" or out.get("error"):
        return False, f"Milvus failed: {out.get('error', 'unknown')}"
    return True, f"Milvus: indexed {out.get('indexed', 0)} demo document(s)."


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
