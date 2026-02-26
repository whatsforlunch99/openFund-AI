"""Demo MCP client: hybrid backends + static LLM/external APIs.

When demo mode is on, SQL/KG/vector use real backends (with populated demo data)
when DATABASE_URL, NEO4J_URI, or MILVUS_URI are set. File, market, and analyst
tools always return static data. No live LLM or external API calls.
"""

from __future__ import annotations

import os
from typing import Any

from demo.demo_data import DEMO_RESPONSES, DEMO_TIMESTAMP


def _load_dotenv() -> None:
    """Load .env so backend env vars are available."""
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass


class DemoMCPClient:
    """MCP client for demo mode: real backends (sql/kg/vector) when configured, static elsewhere.

    Implements the same call_tool(tool_name, payload) interface as mcp.mcp_client.MCPClient.
    - sql_tool.run_query, kg_tool.get_relations, kg_tool.query_graph, vector_tool.search:
      call real tools when DATABASE_URL / NEO4J_URI / MILVUS_URI are set; otherwise static.
    - file_tool.*, market_tool.*, analyst_tool.*: always static (no external APIs).
    """

    def __init__(self) -> None:
        """Initialize the demo client. No server reference; uses env and static data."""
        _load_dotenv()

    def call_tool(self, tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Invoke a tool: real backend when configured, else static demo response.

        Args:
            tool_name: Tool name (e.g. vector_tool.search, sql_tool.run_query).
            payload: Tool-specific parameters.

        Returns:
            Tool response dict. Same shape as real tools for sql/kg/vector;
            static dict for file/market/analyst.
        """
        # Real backends when env is set (use populated demo data)
        if tool_name == "sql_tool.run_query" and os.environ.get("DATABASE_URL"):
            from mcp.tools import sql_tool
            result = sql_tool.run_query(
                payload.get("query") or "",
                payload.get("params"),
            )
            return result if isinstance(result, dict) else {"rows": [], "schema": [], "params": {}}
        if tool_name == "kg_tool.get_relations" and os.environ.get("NEO4J_URI"):
            from mcp.tools import kg_tool
            return kg_tool.get_relations(payload.get("entity") or "")
        if tool_name == "kg_tool.query_graph" and os.environ.get("NEO4J_URI"):
            from mcp.tools import kg_tool
            return kg_tool.query_graph(
                payload.get("cypher") or "",
                payload.get("params"),
            )
        if tool_name == "vector_tool.search" and os.environ.get("MILVUS_URI"):
            from mcp.tools import vector_tool
            docs = vector_tool.search(
                payload.get("query") or "",
                payload.get("top_k", 5),
                payload.get("filter"),
            )
            return {"documents": docs}

        # Static responses for file, market, analyst, or fallback when backend not set
        if tool_name in DEMO_RESPONSES:
            return DEMO_RESPONSES[tool_name]
        return {"content": "Demo stub.", "timestamp": DEMO_TIMESTAMP}
