#!/usr/bin/env python3
"""Test script: run Librarian agent in isolation with a sub-query.

Shows the A2A REQUEST content, optional LLM tool selection, and the INFORM
reply. Uses real MCP (vector_tool, kg_tool, file_tool, sql_tool) by default;
use --mock for stub data.

Usage (from project root):
  PYTHONPATH=. python scripts/test_librarian.py "AAPL fund facts and holdings"
  PYTHONPATH=. python scripts/test_librarian.py "NVDA investment reports" --path /data/fund.txt
  PYTHONPATH=. python scripts/test_librarian.py "query" --mock   # stub data, no backends
  echo "vector search for tech ETFs" | PYTHONPATH=. python scripts/test_librarian.py
"""

from __future__ import annotations

import argparse
import json
import sys

from a2a.acl_message import ACLMessage, Performative


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Test Librarian agent: sub-query -> tool selection -> reply (mock MCP)."
    )
    parser.add_argument("query", nargs="?", default=None, help="Sub-query (or stdin)")
    parser.add_argument("--path", default=None, help="Optional path for file_tool")
    parser.add_argument("--fund", default="", help="Optional fund/entity for kg_tool")
    parser.add_argument("--mock", action="store_true", help="Use mock MCP (stub data, no backends)")
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
            print(f"LLM failed ({e}). Using content-key fallback.\n", file=sys.stderr)
    else:
        print("No LLM_API_KEY. Librarian will use content-key dispatch.\n")

    from a2a.message_bus import InMemoryMessageBus
    from agents.librarian_agent import LibrarianAgent

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
        print("Using real MCP (live vector_tool, kg_tool, file_tool, sql_tool).\n")

    bus = InMemoryMessageBus()
    bus.register_agent("planner")
    bus.register_agent("librarian")
    agent = LibrarianAgent(
        "librarian", bus, mcp_client=mcp_client, llm_client=llm_client
    )

    content = {"query": query, "action": "retrieve_documents"}
    if args.path:
        content["path"] = args.path
    if args.fund:
        content["fund"] = args.fund
        content["vector_query"] = query

    request = ACLMessage(
        performative=Performative.REQUEST,
        sender="planner",
        receiver="librarian",
        content=content,
        reply_to="planner",
    )

    if llm_client:
        from llm.prompts import LIBRARIAN_TOOL_SELECTION
        from llm.tool_descriptions import (
            LIBRARIAN_ALLOWED_TOOL_NAMES,
            filter_tool_calls_to_allowed,
            get_librarian_tool_descriptions,
            normalize_tool_calls,
        )
        tool_descriptions = get_librarian_tool_descriptions()
        user_content = f"Sub-query from planner: {query}"
        tool_calls = llm_client.select_tools(
            LIBRARIAN_TOOL_SELECTION, user_content, tool_descriptions
        )
        tool_calls = filter_tool_calls_to_allowed(tool_calls, LIBRARIAN_ALLOWED_TOOL_NAMES)
        tool_calls = normalize_tool_calls(tool_calls)
        print("=" * 60)
        print("TOOL SELECTION (LLM)")
        print("=" * 60)
        if tool_calls:
            for i, tc in enumerate(tool_calls, 1):
                print(f"  {i}. {tc.get('tool')}  payload={tc.get('payload')}")
        else:
            print("  (none — will use content-key fallback)")
        print()

    print("=" * 60)
    print("USER INPUT / REQUEST CONTENT")
    print("=" * 60)
    print(f"  query: {query}")
    print(f"  action: {content.get('action')}")
    if args.path or args.fund:
        print(f"  extra: path={args.path}, fund={args.fund}")
    print()

    agent.handle_message(request)
    reply = bus.receive("planner", timeout=15)
    if not reply:
        print("No reply from librarian (timeout).", file=sys.stderr)
        return 1

    print("=" * 60)
    print("REPLY (INFORM content)")
    print("=" * 60)
    c = reply.content or {}
    if args.verbose:
        print(json.dumps(c, indent=2))
    else:
        for k, v in c.items():
            print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
