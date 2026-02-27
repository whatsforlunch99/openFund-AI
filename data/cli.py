"""CLI for backend data services: PostgreSQL (sql), Neo4j (neo4j), Milvus (milvus).

Requires .env or env vars (DATABASE_URL, NEO4J_URI, MILVUS_URI). Install backends:
  pip install -e ".[backends]"
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from data.env_loader import load_dotenv as _load_env_from_project


def _load_dotenv() -> None:
    """Load .env from project root so CLI finds it from any cwd."""
    _load_env_from_project()


def cmd_populate(args: argparse.Namespace) -> int:
    """Seed PostgreSQL, Neo4j, Milvus with demo data. Skips backends whose env vars are unset."""
    from data.populate import run_populate

    return run_populate()


def cmd_sql(args: argparse.Namespace) -> int:
    """Run a SQL query (create/update/delete/select). Uses DATABASE_URL."""
    _load_dotenv()
    if not os.environ.get("DATABASE_URL"):
        print(
            "DATABASE_URL is not set. Set it in .env or the environment.",
            file=sys.stderr,
        )
        return 1
    from mcp.tools import sql_tool

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
            {"rows": result["rows"], "schema": result.get("schema", [])}, indent=2
        )
    )
    return 0


def cmd_neo4j(args: argparse.Namespace) -> int:
    """Run a Cypher query (create/update/delete/read). Uses NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD."""
    _load_dotenv()
    if not os.environ.get("NEO4J_URI"):
        print(
            "NEO4J_URI is not set. Set it in .env or the environment.", file=sys.stderr
        )
        return 1
    from mcp.tools import kg_tool

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
    """Index documents from a JSON file. Uses MILVUS_URI, MILVUS_COLLECTION, EMBEDDING_*."""
    _load_dotenv()
    if not os.environ.get("MILVUS_URI"):
        print(
            "MILVUS_URI is not set. Set it in .env or the environment.", file=sys.stderr
        )
        return 1
    from mcp.tools import vector_tool

    with open(args.file) as f:
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
    """Delete entities by Milvus filter expression. Uses MILVUS_URI, MILVUS_COLLECTION."""
    _load_dotenv()
    if not os.environ.get("MILVUS_URI"):
        print(
            "MILVUS_URI is not set. Set it in .env or the environment.", file=sys.stderr
        )
        return 1
    from mcp.tools import vector_tool

    out = vector_tool.delete_by_expr(args.expr)
    if "error" in out:
        print(out["error"], file=sys.stderr)
        return 1
    print(f"Deleted {out.get('deleted', 0)} entity(ies).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="OpenFund-AI data services: run SQL, Cypher, or Milvus index/delete.",
        epilog="Set DATABASE_URL, NEO4J_URI, or MILVUS_URI in .env. Install backends: pip install -e '.[backends]'",
    )
    sub = parser.add_subparsers(dest="backend", help="Backend to use")

    # populate (seed demo data into all configured backends)
    p_pop = sub.add_parser(
        "populate", help="Seed PostgreSQL, Neo4j, Milvus with demo data (NVDA/NVIDIA)"
    )
    p_pop.set_defaults(func=cmd_populate)

    # sql
    p_sql = sub.add_parser(
        "sql", help="PostgreSQL: run a query (INSERT/UPDATE/DELETE/SELECT)"
    )
    p_sql.add_argument("query", help="SQL query (use %s or %(name)s for params)")
    p_sql.add_argument(
        "--params", nargs="*", help="Params as key=value (e.g. id=1 name=FundX)"
    )
    p_sql.set_defaults(func=cmd_sql)

    # neo4j
    p_neo = sub.add_parser(
        "neo4j", help="Neo4j: run a Cypher query (CREATE/MERGE/SET/DELETE/MATCH)"
    )
    p_neo.add_argument("cypher", help="Cypher query (use $paramName for params)")
    p_neo.add_argument("--params", nargs="*", help="Params as key=value")
    p_neo.set_defaults(func=cmd_neo4j)

    # milvus index
    p_mil = sub.add_parser("milvus", help="Milvus: index or delete documents")
    mil_sub = p_mil.add_subparsers(dest="action")
    p_idx = mil_sub.add_parser("index", help="Index documents from a JSON file")
    p_idx.add_argument("file", help="JSON file: array of {content, fund_id?, source?}")
    p_idx.set_defaults(func=cmd_milvus_index)
    p_del = mil_sub.add_parser("delete", help="Delete entities by filter expression")
    p_del.add_argument(
        "expr", help='Milvus expr (e.g. id in ["id1","id2"] or fund_id == "X")'
    )
    p_del.set_defaults(func=cmd_milvus_delete)

    args = parser.parse_args()
    if not args.backend:
        parser.print_help()
        return 0
    if args.backend == "milvus" and not getattr(args, "action", None):
        p_mil.print_help()
        return 0
    func = getattr(args, "func", None)
    if func is None:
        parser.print_help()
        return 0
    return func(args)


if __name__ == "__main__":
    sys.exit(main())
