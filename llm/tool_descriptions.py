"""Tool descriptions per agent for LLM tool selection.

Tools and payload parameters are derived from mcp/tools/*.py and
mcp/mcp_server.py register_default_tools(). Kept in sync with
docs/agent-tools-reference.md. Only tools actually registered in
MCPServer are listed here (file_tool is not registered).
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Single flat dict of all tools: tool_name -> short description.
# Payload keys match mcp_server lambdas and tool function signatures.
# ---------------------------------------------------------------------------
TOOL_DESCRIPTIONS_BY_NAME: dict[str, str] = {
    # vector_tool (mcp/tools/vector_tool.py)
    "vector_tool.search": "Semantic search over documents. Payload: query (required), top_k (optional int, default 5), filter (optional dict, e.g. fund_id, source).",
    "vector_tool.get_by_ids": "Retrieve entities by IDs. Payload: ids (list of strings), collection_name (optional). Returns entities.",
    "vector_tool.upsert_documents": "Insert or update documents in vector collection. Payload: docs (list of dicts with 'id' and 'content'; optional fund_id, source).",
    "vector_tool.health_check": "Check Milvus connectivity. Payload: {}.",
    "vector_tool.create_collection_from_config": "Create a new Milvus collection. Payload: name (string), dimension (optional int, default 384), primary_key_field (optional), scalar_fields (optional), index_params (optional).",
    # kg_tool (mcp/tools/kg_tool.py)
    "kg_tool.query_graph": "Run Cypher query. Payload: cypher (string), params (optional dict).",
    "kg_tool.get_relations": "Get relationships for an entity (fund/company). Payload: entity (string).",
    "kg_tool.get_node_by_id": "Look up a node by property. Payload: id_val or id (string), id_key (optional, default 'id').",
    "kg_tool.get_neighbors": "Get neighbors of a node. Payload: node_id or id (string), id_key, direction ('in'|'out'|'both'), relationship_type (optional), limit (optional int, default 100).",
    "kg_tool.get_graph_schema": "List node labels and relationship types. Payload: {}.",
    "kg_tool.shortest_path": "Find shortest path between two nodes. Payload: start_id (string), end_id (string), id_key (optional), relationship_type (optional), max_depth (optional int, default 15).",
    "kg_tool.get_similar_nodes": "Find structurally similar nodes by shared neighbors. Payload: node_id or id (string), id_key (optional), limit (optional int, default 10).",
    "kg_tool.fulltext_search": "Full-text search via Neo4j index. Payload: index_name (string), query_string (string), limit (optional int, default 50).",
    "kg_tool.bulk_export": "Read-only Cypher export as JSON or CSV. Payload: cypher (string), params (optional), format ('json'|'csv'), row_limit (optional int, default 1000).",
    "kg_tool.bulk_create_nodes": "Create/merge nodes. Payload: nodes (list of dicts), label (optional string), id_key (optional string, default 'id').",
    # sql_tool (mcp/tools/sql_tool.py)
    "sql_tool.run_query": "Execute SQL on PostgreSQL. Use only tables/columns from the schema in your instructions. Payload: query (string), params (optional).",
    "sql_tool.explain_query": "Return SQL query plan. Payload: query (string), params (optional), analyze (optional bool).",
    "sql_tool.export_results": "Run read-only SQL and return JSON or CSV. Payload: query (string), params (optional), format ('json'|'csv'), row_limit (optional int, default 1000).",
    "sql_tool.connection_health_check": "Test PostgreSQL connectivity. Payload: {}.",
    # market_tool (mcp/tools/market_tool.py; optional)
    "market_tool.get_fundamentals": "Company fundamentals/overview (vendor-routed). Payload: symbol or ticker (string).",
    "market_tool.get_stock_data": "OHLCV historical data (vendor-routed). Payload: symbol or ticker (string), start_date (yyyy-mm-dd), end_date (yyyy-mm-dd).",
    "market_tool.get_balance_sheet": "Balance sheet (vendor-routed). Payload: ticker or symbol (string), freq (optional 'quarterly'|'annual').",
    "market_tool.get_cashflow": "Cash flow statement (vendor-routed). Payload: ticker or symbol (string), freq (optional).",
    "market_tool.get_income_statement": "Income statement (vendor-routed). Payload: ticker or symbol (string), freq (optional).",
    "market_tool.get_insider_transactions": "Insider transactions (vendor-routed). Payload: ticker or symbol (string).",
    "market_tool.get_news": "Recent ticker news (vendor-routed). Payload: symbol or ticker (string), limit (optional), start_date, end_date.",
    "market_tool.get_global_news": "Global/macro financial news (vendor-routed). Payload: as_of_date or curr_date (optional yyyy-mm-dd), look_back_days (optional int, default 7), limit (optional int, default 10).",
    # analyst_tool (mcp/tools/analyst_tool.py; optional)
    "analyst_tool.get_indicators": "Technical indicators (SMA, RSI, MACD, etc.). Payload: symbol or ticker (string), indicator (e.g. close_50_sma, rsi, macd, boll, atr), as_of_date or curr_date (yyyy-mm-dd), look_back_days (optional int, default 30).",
    # capabilities (mcp/tools/capabilities.py)
    "get_capabilities": "List registered MCP tools and backend status (neo4j, postgres, milvus). Payload: {}.",
}


# ---------------------------------------------------------------------------
# Allowed tool name sets per agent. Must match tools registered in
# mcp/mcp_server.py register_default_tools() and mcp/tools/*.py.
# ---------------------------------------------------------------------------
LIBRARIAN_ALLOWED_TOOL_NAMES: frozenset[str] = frozenset([
    "vector_tool.search",
    "vector_tool.get_by_ids",
    "vector_tool.upsert_documents",
    "vector_tool.health_check",
    "vector_tool.create_collection_from_config",
    "kg_tool.query_graph",
    "kg_tool.get_relations",
    "kg_tool.get_node_by_id",
    "kg_tool.get_neighbors",
    "kg_tool.get_graph_schema",
    "kg_tool.shortest_path",
    "kg_tool.get_similar_nodes",
    "kg_tool.fulltext_search",
    "kg_tool.bulk_export",
    "kg_tool.bulk_create_nodes",
    "sql_tool.run_query",
    "sql_tool.explain_query",
    "sql_tool.export_results",
    "sql_tool.connection_health_check",
    "get_capabilities",
])

WEBSEARCHER_ALLOWED_TOOL_NAMES: frozenset[str] = frozenset([
    "market_tool.get_fundamentals",
    "market_tool.get_stock_data",
    "market_tool.get_balance_sheet",
    "market_tool.get_cashflow",
    "market_tool.get_income_statement",
    "market_tool.get_insider_transactions",
    "market_tool.get_news",
    "market_tool.get_global_news",
    "get_capabilities",
])

ANALYST_ALLOWED_TOOL_NAMES: frozenset[str] = frozenset([
    "analyst_tool.get_indicators",
    "get_capabilities",
])


# ---------------------------------------------------------------------------
# Convenience lists for ordering tool entries in prompts (ordered by usefulness).
# Each list contains tool names; descriptions are fetched from TOOL_DESCRIPTIONS_BY_NAME.
# ---------------------------------------------------------------------------
_LIBRARIAN_TOOL_ORDER: list[str] = [
    "vector_tool.search",
    "vector_tool.get_by_ids",
    "vector_tool.upsert_documents",
    "vector_tool.health_check",
    "vector_tool.create_collection_from_config",
    "kg_tool.get_relations",
    "kg_tool.get_node_by_id",
    "kg_tool.query_graph",
    "kg_tool.get_neighbors",
    "kg_tool.get_graph_schema",
    "kg_tool.shortest_path",
    "kg_tool.get_similar_nodes",
    "kg_tool.fulltext_search",
    "kg_tool.bulk_export",
    "kg_tool.bulk_create_nodes",
    "sql_tool.run_query",
    "sql_tool.explain_query",
    "sql_tool.export_results",
    "sql_tool.connection_health_check",
    "get_capabilities",
]

_WEBSEARCHER_TOOL_ORDER: list[str] = [
    "market_tool.get_fundamentals",
    "market_tool.get_stock_data",
    "market_tool.get_news",
    "market_tool.get_global_news",
    "market_tool.get_balance_sheet",
    "market_tool.get_cashflow",
    "market_tool.get_income_statement",
    "market_tool.get_insider_transactions",
    "get_capabilities",
]

_ANALYST_TOOL_ORDER: list[str] = [
    "analyst_tool.get_indicators",
    "get_capabilities",
]


def _build_descriptions_string(tool_names: list[str]) -> str:
    """Format an ordered list of tool names into a prompt-ready string."""
    lines = []
    for name in tool_names:
        desc = TOOL_DESCRIPTIONS_BY_NAME.get(name, "No description available.")
        lines.append(f"- {name}: {desc}")
    return "\n".join(lines)


def get_librarian_tool_descriptions(
    registered_tool_names: set[str] | None = None,
) -> str:
    """Return prompt-ready tool descriptions for the Librarian (allowed pool only).
    If registered_tool_names is set, only include tools that are actually registered.
    """
    order = (
        [n for n in _LIBRARIAN_TOOL_ORDER if n in registered_tool_names]
        if registered_tool_names is not None
        else _LIBRARIAN_TOOL_ORDER
    )
    return _build_descriptions_string(order)


def get_websearcher_tool_descriptions(
    registered_tool_names: set[str] | None = None,
) -> str:
    """Return prompt-ready tool descriptions for the WebSearcher (allowed pool only).
    If registered_tool_names is set, only include tools that are actually registered.
    """
    order = (
        [n for n in _WEBSEARCHER_TOOL_ORDER if n in registered_tool_names]
        if registered_tool_names is not None
        else _WEBSEARCHER_TOOL_ORDER
    )
    return _build_descriptions_string(order)


def get_analyst_tool_descriptions(
    registered_tool_names: set[str] | None = None,
) -> str:
    """Return prompt-ready tool descriptions for the Analyst (allowed pool only).
    If registered_tool_names is set, only include tools that are actually registered.
    """
    order = (
        [n for n in _ANALYST_TOOL_ORDER if n in registered_tool_names]
        if registered_tool_names is not None
        else _ANALYST_TOOL_ORDER
    )
    return _build_descriptions_string(order)


def normalize_tool_calls(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert raw tool-call list to canonical shape: [{"tool": str, "payload": dict}, ...].

    Ensures every element has exactly "tool" (non-empty string) and "payload" (dict, shallow
    copy). Accepts input with "tool" or "tool_name"; skips non-dict items, non-string/empty
    tool names, and coerces missing or non-dict payload to {}.
    """
    result = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        tool = item.get("tool") or item.get("tool_name")
        if not isinstance(tool, str) or not tool.strip():
            continue
        payload = item.get("payload")
        if not isinstance(payload, dict):
            payload = {}
        else:
            payload = dict(payload)
        result.append({"tool": tool.strip(), "payload": payload})
    return result


def filter_tool_calls_to_allowed(
    tool_calls: list[dict[str, Any]],
    allowed_names: frozenset[str],
) -> list[dict[str, Any]]:
    """Discard any tool call whose name is not in the agent's allowed set.

    Defense-in-depth: even if the LLM returns a hallucinated or cross-agent
    tool name, it will be dropped before mcp_client.call_tool is invoked.

    Args:
        tool_calls: List of {tool, payload} dicts from select_tools().
        allowed_names: frozenset of allowed tool names for this agent.

    Returns:
        Filtered list containing only tool calls whose 'tool' is in allowed_names.
    """
    filtered = []
    for tc in tool_calls:
        tool = tc.get("tool") or tc.get("tool_name") or ""
        if tool in allowed_names:
            filtered.append(tc)
    return filtered


# ---------------------------------------------------------------------------
# Legacy aliases kept for backward compatibility (tests that import directly).
# ---------------------------------------------------------------------------
LIBRARIAN_TOOLS: list[dict] = [
    {"name": n, "description": TOOL_DESCRIPTIONS_BY_NAME.get(n, "")}
    for n in _LIBRARIAN_TOOL_ORDER
]
WEBSEARCHER_TOOLS: list[dict] = [
    {"name": n, "description": TOOL_DESCRIPTIONS_BY_NAME.get(n, "")}
    for n in _WEBSEARCHER_TOOL_ORDER
]
ANALYST_TOOLS: list[dict] = [
    {"name": n, "description": TOOL_DESCRIPTIONS_BY_NAME.get(n, "")}
    for n in _ANALYST_TOOL_ORDER
]
