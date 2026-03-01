#!/usr/bin/env python3
"""Test script: run Analyst agent in isolation with a sub-query.

Shows the A2A REQUEST content, optional LLM tool selection, and the INFORM
reply. Uses real MCP (analyst_tool, market_tool) by default; use --mock for stub data.

Usage (from project root):
  PYTHONPATH=. python scripts/test_analyst.py "Analyze AAPL financial performance and risk"
  PYTHONPATH=. python scripts/test_analyst.py "NVDA technical indicators" --symbol NVDA
  PYTHONPATH=. python scripts/test_analyst.py "query" --mock   # stub data, no network
  echo "TSLA investment outlook" | PYTHONPATH=. python scripts/test_analyst.py
"""

from __future__ import annotations

import argparse
import json
import sys

from a2a.acl_message import ACLMessage, Performative


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Test Analyst agent: sub-query -> tool selection -> reply (mock MCP)."
    )
    parser.add_argument("query", nargs="?", default=None, help="Sub-query (or stdin)")
    parser.add_argument("--symbol", default=None, help="Optional symbol for indicator tools")
    parser.add_argument("--mock", action="store_true", help="Use mock MCP (stub data, no network)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Print full JSON")
    args = parser.parse_args()

    query = args.query or sys.stdin.read().strip()
    if not query:
        print("No query provided. Pass as argument or stdin.", file=sys.stderr)
        return 1

    from config.config import load_config

    config = load_config()
    llm_client = None
    if config.llm_api_key and config.llm_api_key.strip():
        try:
            from llm.factory import get_llm_client
            llm_client = get_llm_client(config)
            print("Using live LLM for tool selection.\n")
        except (ValueError, ImportError) as e:
            print(f"LLM failed ({e}). Using content-based fallback.\n", file=sys.stderr)
    else:
        print("No LLM_API_KEY. Analyst will use content-based flow.\n")

    from a2a.message_bus import InMemoryMessageBus
    from agents.analyst_agent import AnalystAgent

    if args.mock:
        from scripts._mock_mcp import MockMCPClient
        mcp_client = MockMCPClient()
        print("Using mock MCP (stub data).\n")
    else:
        from mcp.mcp_client import MCPClient
        from mcp.mcp_server import MCPServer
        server = MCPServer()
        server.register_default_tools()
        mcp_client = MCPClient(server)
        print("Using real MCP (live analyst_tool, market_tool).\n")

    bus = InMemoryMessageBus()
    bus.register_agent("planner")
    bus.register_agent("analyst")
    agent = AnalystAgent(
        "analyst", bus, mcp_client=mcp_client, llm_client=llm_client
    )

    content = {"query": query, "action": "analyze", "structured_data": {}, "market_data": {}}
    if args.symbol:
        content["symbol"] = args.symbol

    request = ACLMessage(
        performative=Performative.REQUEST,
        sender="planner",
        receiver="analyst",
        content=content,
        reply_to="planner",
    )

    if llm_client:
        from llm.prompts import ANALYST_TOOL_SELECTION
        from llm.tool_descriptions import (
            ANALYST_ALLOWED_TOOL_NAMES,
            filter_tool_calls_to_allowed,
            get_analyst_tool_descriptions,
            normalize_tool_calls,
        )
        tool_descriptions = get_analyst_tool_descriptions()
        user_content = f"Sub-query from planner: {query}"
        tool_calls = llm_client.select_tools(
            ANALYST_TOOL_SELECTION, user_content, tool_descriptions
        )
        tool_calls = filter_tool_calls_to_allowed(tool_calls, ANALYST_ALLOWED_TOOL_NAMES)
        tool_calls = normalize_tool_calls(tool_calls)
        print("=" * 60)
        print("TOOL SELECTION (LLM)")
        print("=" * 60)
        if tool_calls:
            for i, tc in enumerate(tool_calls, 1):
                print(f"  {i}. {tc.get('tool')}  payload={tc.get('payload')}")
        else:
            print("  (none — will use analyze() with empty/mock data)")
        print()

    print("=" * 60)
    print("USER INPUT / REQUEST CONTENT")
    print("=" * 60)
    print(f"  query: {query}")
    print(f"  action: {content.get('action')}")
    if args.symbol:
        print(f"  symbol: {args.symbol}")
    print()

    agent.handle_message(request)
    reply = bus.receive("planner", timeout=15)
    if not reply:
        print("No reply from analyst (timeout).", file=sys.stderr)
        return 1

    print("=" * 60)
    print("REPLY (INFORM content)")
    print("=" * 60)
    c = reply.content or {}
    if args.verbose:
        print(json.dumps(c, indent=2))
    else:
        for k, v in c.items():
            if k == "analysis" and isinstance(v, dict):
                print(f"  analysis: confidence={v.get('confidence')} keys={list(v.keys())}")
            else:
                print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
