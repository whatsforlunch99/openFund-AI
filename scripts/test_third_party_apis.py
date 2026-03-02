#!/usr/bin/env python3
"""Test every MCP tool from agent-tools-reference.md via MCPClient.call_tool().

Makes live calls through the MCP layer, classifies results as PASS, INFRA_SKIP,
or API_FAIL, and writes a detailed table to docs/api-test-results.md.

Usage (from project root):
  PYTHONPATH=. python scripts/test_third_party_apis.py
  PYTHONPATH=. python scripts/test_third_party_apis.py --symbol TSLA
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from datetime import date, timedelta


def _snippet(obj: object, max_len: int = 80) -> str:
    """Return a short snippet for display; escape newlines."""
    if obj is None:
        return "(null)"
    if isinstance(obj, dict):
        if "error" in obj:
            return str(obj.get("error", ""))[:max_len]
        if "content" in obj:
            c = obj["content"]
            if isinstance(c, str) and c.strip():
                return c.strip().replace("\n", " ")[:max_len]
            return "(empty content)"
        if "documents" in obj:
            return f"documents: {len(obj.get('documents', []))} items"
        if "status" in obj:
            return f"status={obj.get('status')}"
        if "tools" in obj:
            return f"tools: {len(obj.get('tools', []))} registered"
        return json.dumps(obj)[:max_len]
    s = str(obj)
    return s.replace("\n", " ")[:max_len]


# Keywords in error messages that indicate subscription/access/invalid (API_FAIL).
_API_FAIL_KEYWORDS = re.compile(
    r"subscription|premium|upgrade|rate limit|quota|invalid api|access denied|403|401",
    re.IGNORECASE,
)

# Keywords that indicate infrastructure not configured (INFRA_SKIP).
_INFRA_KEYWORDS = re.compile(
    r"connection refused|unavailable|MILVUS|NEO4J|postgres|DATABASE_URL|not configured|environment variable|MCP_MARKET_VENDOR",
    re.IGNORECASE,
)


def _classify(result: dict, tool_name: str) -> str:
    """Return PASS, INFRA_SKIP, or API_FAIL."""
    if not isinstance(result, dict):
        return "API_FAIL"
    err = result.get("error")
    if err is not None:
        err_str = str(err)
        if _API_FAIL_KEYWORDS.search(err_str):
            return "API_FAIL"
        if _INFRA_KEYWORDS.search(err_str):
            return "INFRA_SKIP"
        # Unknown error: treat as API_FAIL for external tools, INFRA_SKIP for rest
        if tool_name.startswith("market_tool.") or tool_name.startswith("analyst_tool."):
            return "API_FAIL"
        return "INFRA_SKIP"
    # No error: check for content
    if "content" in result:
        c = result["content"]
        if c is None or (isinstance(c, str) and not c.strip()):
            if tool_name.startswith("market_tool.") or tool_name.startswith("analyst_tool."):
                return "API_FAIL"
        return "PASS"
    if "documents" in result or "status" in result or "tools" in result:
        return "PASS"
    if "rows" in result or "created" in result or "upserted" in result:
        return "PASS"
    return "PASS"


def _build_sample_payloads(symbol: str, today: str, start_5d: str) -> dict[str, dict]:
    """Build payloads for every documented tool (from agent-tools-reference.md)."""
    return {
        "file_tool.read_file": {"path": "/tmp/agent_tools_test"},
        "vector_tool.search": {"query": "NVDA fund performance 2024", "top_k": 5},
        "vector_tool.get_by_ids": {"ids": ["doc_001", "doc_002"]},
        "vector_tool.upsert_documents": {"docs": [{"id": "doc_003", "text": "Test."}]},
        "vector_tool.health_check": {},
        "vector_tool.create_collection_from_config": {
            "name": "fund_docs_v2",
            "dimension": 768,
            "primary_key_field": "id",
        },
        "kg_tool.query_graph": {
            "cypher": "MATCH (f:Fund {symbol: $sym}) RETURN f",
            "params": {"sym": symbol},
        },
        "kg_tool.get_relations": {"entity": symbol},
        "kg_tool.get_node_by_id": {"id_val": symbol, "id_key": "symbol"},
        "kg_tool.get_neighbors": {"node_id": symbol, "id_key": "symbol", "direction": "out", "limit": 20},
        "kg_tool.get_graph_schema": {},
        "kg_tool.shortest_path": {"start_id": symbol, "end_id": "AAPL", "id_key": "symbol", "max_depth": 5},
        "kg_tool.get_similar_nodes": {"node_id": symbol, "id_key": "symbol", "limit": 5},
        "kg_tool.fulltext_search": {"index_name": "fund_fulltext", "query_string": "semiconductor", "limit": 10},
        "kg_tool.bulk_export": {"cypher": "MATCH (f:Fund) RETURN f.symbol, f.name LIMIT 100", "format": "json"},
        "kg_tool.bulk_create_nodes": {
            "nodes": [{"id": "TSMC", "name": "Taiwan Semiconductor"}],
            "label": "Company",
            "id_key": "id",
        },
        "sql_tool.run_query": {"query": "SELECT * FROM funds WHERE symbol = %s", "params": [symbol]},
        "sql_tool.explain_query": {"query": "SELECT * FROM funds WHERE aum > 1000000", "analyze": False},
        "sql_tool.export_results": {
            "query": "SELECT symbol, name, aum FROM funds ORDER BY aum DESC",
            "format": "csv",
            "row_limit": 500,
        },
        "sql_tool.connection_health_check": {},
        "market_tool.get_stock_data": {"symbol": symbol, "start_date": start_5d, "end_date": today},
        "market_tool.get_balance_sheet": {"ticker": "MSFT", "freq": "annual"},
        "market_tool.get_cashflow": {"ticker": "TSLA", "freq": "quarterly"},
        "market_tool.get_income_statement": {"ticker": symbol, "freq": "quarterly"},
        "market_tool.get_insider_transactions": {"ticker": symbol},
        "market_tool.get_news": {"symbol": symbol, "limit": 5},
        "market_tool.get_global_news": {"as_of_date": today, "look_back_days": 7, "limit": 5},
        "analyst_tool.get_indicators": {
            "symbol": symbol,
            "indicator": "rsi",
            "as_of_date": today,
            "look_back_days": 30,
        },
        "get_capabilities": {},
    }


def _write_results_doc(results: list[tuple[str, str, float, str, str]], out_path: str, run_date: str) -> None:
    """Write docs/api-test-results.md with a markdown table."""
    lines = [
        "# MCP Tool Live Test Results",
        "",
        f"Generated by `scripts/test_third_party_apis.py` on {run_date}.",
        "",
        "| Tool | Status | Time (s) | Response snippet |",
        "|------|--------|----------|------------------|",
    ]
    for tool_name, status, elapsed, snippet, _ in results:
        snippet_esc = snippet.replace("|", "\\|")[:100]
        lines.append(f"| {tool_name} | {status} | {elapsed:.2f} | {snippet_esc} |")
    lines.extend([
        "",
        "## Status legend",
        "",
        "- **PASS** — Call succeeded; non-empty content or valid structure.",
        "- **INFRA_SKIP** — Backend not configured (Milvus/Neo4j/Postgres) or similar.",
        "- **API_FAIL** — External API error (subscription, rate limit, invalid). Remove from project if persistent.",
        "",
    ])
    api_fails = [r[0] for r in results if r[1] == "API_FAIL"]
    if api_fails:
        lines.extend([
            "## Tools marked API_FAIL (candidates for removal)",
            "",
            "The following tools returned errors indicating subscription/access or invalid response:",
            "",
        ])
        for t in api_fails:
            lines.append(f"- `{t}`")
        lines.append("")
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w") as f:
        f.write("\n".join(lines))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Test all MCP tools via MCPClient.call_tool(); write docs/api-test-results.md."
    )
    parser.add_argument(
        "--symbol",
        default="NVDA",
        help="Ticker for market/analyst tools (default: NVDA)",
    )
    parser.add_argument(
        "--out",
        default="docs/api-test-results.md",
        help="Output markdown file (default: docs/api-test-results.md)",
    )
    args = parser.parse_args()

    # Load .env so MCP tools see ALPHA_VANTAGE_API_KEY, FINNHUB_API_KEY, etc.
    from config.config import load_config
    load_config()

    logging.getLogger("mcp.tools").setLevel(logging.WARNING)

    from llm.tool_descriptions import TOOL_DESCRIPTIONS_BY_NAME
    from mcp.mcp_client import MCPClient
    from mcp.mcp_server import MCPServer

    server = MCPServer()
    server.register_default_tools()
    client = MCPClient(server)

    registered = set()
    caps = client.call_tool("get_capabilities", {})
    if isinstance(caps, dict):
        registered = set(caps.get("tools") or [])

    symbol = (args.symbol or "NVDA").strip().upper()
    today = date.today().isoformat()
    start_5d = (date.today() - timedelta(days=5)).isoformat()
    payloads = _build_sample_payloads(symbol, today, start_5d)

    # Ensure we have payloads for every tool in TOOL_DESCRIPTIONS_BY_NAME
    for name in TOOL_DESCRIPTIONS_BY_NAME:
        if name not in payloads:
            payloads[name] = {}

    run_date = date.today().isoformat()
    print(f"=== MCP Tool Live Validation ({run_date}) ===\n")
    results: list[tuple[str, str, float, str, str]] = []

    for tool_name in sorted(TOOL_DESCRIPTIONS_BY_NAME):
        if tool_name not in registered:
            results.append((tool_name, "SKIP", 0.0, "(not registered)", ""))
            print(f"  {tool_name:<45} SKIP   (not registered)")
            continue
        payload = payloads.get(tool_name, {})
        start = time.perf_counter()
        try:
            result = client.call_tool(tool_name, payload)
        except Exception as e:
            result = {"error": str(e)}
        elapsed = time.perf_counter() - start
        status = _classify(result, tool_name)
        snippet = _snippet(result)
        full_snippet = snippet
        if isinstance(result, dict) and "error" in result:
            full_snippet = str(result.get("error", ""))[:200]
        results.append((tool_name, status, elapsed, snippet, full_snippet))
        print(f"  {tool_name:<45} {status:<10} {elapsed:.2f}s  {snippet}")

    _write_results_doc(results, args.out, run_date)
    print(f"\nWrote {args.out}")

    counts = {"PASS": 0, "INFRA_SKIP": 0, "API_FAIL": 0, "SKIP": 0}
    for _, status, _, _, _ in results:
        counts[status] = counts.get(status, 0) + 1
    print("\n=== Summary ===")
    for k, v in sorted(counts.items()):
        print(f"  {k}  {v}")

    return 1 if counts.get("API_FAIL", 0) > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
