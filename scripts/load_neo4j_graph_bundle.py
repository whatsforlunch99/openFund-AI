#!/usr/bin/env python3
"""Validate and optionally load `database/graph_data/neo4j_export` into Neo4j.

Loads `.env` from the repo root (NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, NEO4J_DATABASE).

Examples:
  .venv/bin/python scripts/load_neo4j_graph_bundle.py --validate-only
  .venv/bin/python scripts/load_neo4j_graph_bundle.py --load
  .venv/bin/python scripts/load_neo4j_graph_bundle.py --probe-vanke
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def _root() -> Path:
    return Path(__file__).resolve().parent.parent


def main() -> int:
    ap = argparse.ArgumentParser(description="Neo4j graph CSV bundle: validate / load / probe.")
    ap.add_argument(
        "--output-dir",
        default=str(_root() / "database" / "graph_data" / "neo4j_export"),
        help="Directory with graph_nodes.csv and graph_relationships.csv",
    )
    ap.add_argument(
        "--validate-only",
        action="store_true",
        help="Only run validate_graph_csv_bundle_for_neo4j (no DB writes).",
    )
    ap.add_argument(
        "--load",
        action="store_true",
        help="Run load_graph_csvs_to_neo4j after validation (large import; requires NEO4J_URI).",
    )
    ap.add_argument(
        "--probe-vanke",
        action="store_true",
        help="After validation, call get_relations('China Vanke Co Ltd') and print node count.",
    )
    args = ap.parse_args()

    try:
        from dotenv import load_dotenv
    except ImportError:
        load_dotenv = None  # type: ignore[misc, assignment]
    if load_dotenv:
        load_dotenv(_root() / ".env")

    from openfund_mcp.tools import kg_tool

    out_dir = os.path.abspath(args.output_dir)
    v = kg_tool.validate_graph_csv_bundle_for_neo4j(out_dir, sample_limit=20)
    if not v.get("ok"):
        print("validate failed:", v, file=sys.stderr)
        return 1
    print("validate: ok", f"schema={v.get('schema', '')!s}".strip())

    if args.validate_only and not args.load and not args.probe_vanke:
        return 0

    if not os.environ.get("NEO4J_URI"):
        print("NEO4J_URI not set; set it in .env to use --load or --probe-vanke.", file=sys.stderr)
        return 2 if (args.load or args.probe_vanke) else 0

    if args.load:
        r = kg_tool.load_graph_csvs_to_neo4j(
            nodes_csv="",
            relationships_csv="",
            mode="append",
            output_dir=out_dir,
        )
        print("load:", r)
        if r.get("error"):
            return 1

    if args.probe_vanke:
        rel = kg_tool.get_relations("China Vanke Co Ltd")
        n = len(rel.get("nodes") or [])
        e = len(rel.get("edges") or [])
        print(f"get_relations probe: nodes={n} edges={e} entity={rel.get('entity')!r}")
        if rel.get("error"):
            print("error:", rel["error"], file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
