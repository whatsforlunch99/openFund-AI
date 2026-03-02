"""Backend data CLI helpers shared by data_manager and legacy data package wrappers."""

from __future__ import annotations

import argparse
import json
import os
import sys

from config.config import load_config
from mcp.tools import kg_tool, sql_tool, vector_tool


def run_populate() -> int:
    """Seed PostgreSQL, Neo4j, and Milvus demo data (idempotent)."""
    # Ensure .env is loaded regardless of current working directory.
    load_config()

    results = [
        sql_tool.populate_demo(),
        kg_tool.populate_demo(),
        vector_tool.populate_demo(),
    ]
    for ok, msg in results:
        print(msg, file=sys.stdout if ok else sys.stderr)
    if not any(ok for ok, _ in results):
        print(
            "No backends configured. Set DATABASE_URL, NEO4J_URI, and/or MILVUS_URI in .env.",
            file=sys.stderr,
        )
    return 0


def _require_env(var_name: str) -> bool:
    """Return True if required environment variable exists and is non-empty."""
    return bool((os.environ.get(var_name) or "").strip())


def cmd_populate(_args: argparse.Namespace) -> int:
    """Seed PostgreSQL, Neo4j, and Milvus with demo data."""
    return run_populate()


def cmd_sql(args: argparse.Namespace) -> int:
    """Run a SQL query (create/update/delete/select)."""
    load_config()
    if not _require_env("DATABASE_URL"):
        print(
            "DATABASE_URL is not set. Set it in .env or the environment.",
            file=sys.stderr,
        )
        return 1

    params = None
    if args.params:
        params = {}
        for p in args.params:
            if "=" in p:
                k, v = p.split("=", 1)
                params[k.strip()] = v.strip()

    result = sql_tool.run_query(args.query, params)
    if "error" in result:
        print(result["error"], file=sys.stderr)
        return 1
    print(
        json.dumps(
            {"rows": result["rows"], "schema": result.get("schema", [])},
            indent=2,
        )
    )
    return 0


def cmd_neo4j(args: argparse.Namespace) -> int:
    """Run a Cypher query (create/update/delete/read)."""
    load_config()
    if not _require_env("NEO4J_URI"):
        print(
            "NEO4J_URI is not set. Set it in .env or the environment.",
            file=sys.stderr,
        )
        return 1

    params = None
    if args.params:
        params = {}
        for p in args.params:
            if "=" in p:
                k, v = p.split("=", 1)
                params[k.strip()] = v.strip()

    result = kg_tool.query_graph(args.cypher, params)
    if "error" in result:
        print(result["error"], file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


def cmd_milvus_index(args: argparse.Namespace) -> int:
    """Index documents from a JSON file."""
    load_config()
    if not _require_env("MILVUS_URI"):
        print(
            "MILVUS_URI is not set. Set it in .env or the environment.",
            file=sys.stderr,
        )
        return 1

    with open(args.file, "r", encoding="utf-8") as f:
        docs = json.load(f)
    if not isinstance(docs, list):
        docs = [docs]
    result = vector_tool.index_documents(docs)
    if result.get("status") == "error":
        print(result.get("error", "Unknown error"), file=sys.stderr)
        return 1
    print(f"Indexed {result.get('indexed', 0)} document(s).")
    return 0


def cmd_milvus_delete(args: argparse.Namespace) -> int:
    """Delete entities by Milvus filter expression."""
    load_config()
    if not _require_env("MILVUS_URI"):
        print(
            "MILVUS_URI is not set. Set it in .env or the environment.",
            file=sys.stderr,
        )
        return 1

    out = vector_tool.delete_by_expr(args.expr)
    if "error" in out:
        print(out["error"], file=sys.stderr)
        return 1
    print(f"Deleted {out.get('deleted', 0)} entity(ies).")
    return 0


def add_backend_subcommands(subparsers: argparse._SubParsersAction) -> None:
    """Register backend-oriented CLI subcommands under a parser."""
    p_pop = subparsers.add_parser(
        "populate",
        help="Seed PostgreSQL, Neo4j, Milvus with demo data (NVDA/NVIDIA)",
    )
    p_pop.set_defaults(func=cmd_populate)

    p_sql = subparsers.add_parser(
        "sql", help="PostgreSQL: run a query (INSERT/UPDATE/DELETE/SELECT)"
    )
    p_sql.add_argument("query", help="SQL query (use %s or %(name)s for params)")
    p_sql.add_argument(
        "--params", nargs="*", help="Params as key=value (e.g. id=1 name=FundX)"
    )
    p_sql.set_defaults(func=cmd_sql)

    p_neo = subparsers.add_parser(
        "neo4j", help="Neo4j: run a Cypher query (CREATE/MERGE/SET/DELETE/MATCH)"
    )
    p_neo.add_argument("cypher", help="Cypher query (use $paramName for params)")
    p_neo.add_argument("--params", nargs="*", help="Params as key=value")
    p_neo.set_defaults(func=cmd_neo4j)

    p_mil = subparsers.add_parser("milvus", help="Milvus: index or delete documents")
    mil_sub = p_mil.add_subparsers(dest="action")
    p_idx = mil_sub.add_parser("index", help="Index documents from a JSON file")
    p_idx.add_argument("file", help="JSON file: array of {content, fund_id?, source?}")
    p_idx.set_defaults(func=cmd_milvus_index)
    p_del = mil_sub.add_parser("delete", help="Delete entities by filter expression")
    p_del.add_argument(
        "expr", help='Milvus expr (e.g. id in ["id1","id2"] or fund_id == "X")'
    )
    p_del.set_defaults(func=cmd_milvus_delete)

