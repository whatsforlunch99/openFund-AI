"""Tool descriptions per agent for LLM tool selection. Mirrors docs/agent-tools-reference.md.

The allowed tool sets and descriptions here are the single source of truth in code.
Any change to the "Summary: tools available per agent" table in docs/agent-tools-reference.md
should be reflected here (and vice versa).
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Single flat dict of all tools: tool_name -> short description.
# Used to build per-agent prompt strings from the allowed sets below.
# ---------------------------------------------------------------------------
TOOL_DESCRIPTIONS_BY_NAME: dict[str, str] = {
    # file_tool
    "file_tool.read_file": "Read file content. Payload: path (string).",
    # vector_tool
    "vector_tool.search": "Semantic search over documents. Payload: query (string), top_k (optional int, default 5), filter (optional).",
    "vector_tool.get_by_ids": "Retrieve documents by IDs. Payload: ids (list of strings), collection_name (optional).",
    "vector_tool.upsert_documents": "Insert or update documents in vector collection. Payload: docs (list of dicts with 'text' and optional 'id').",
    "vector_tool.health_check": "Check Milvus connectivity. Payload: {}.",
    "vector_tool.create_collection_from_config": "Create a new Milvus collection. Payload: name (string), dimension (optional int), primary_key_field (optional), scalar_fields (optional), index_params (optional).",
    # kg_tool
    "kg_tool.query_graph": "Run Cypher query. Payload: cypher (string), params (optional dict).",
    "kg_tool.get_relations": "Get relationships for an entity (fund/company). Payload: entity (string).",
    "kg_tool.get_node_by_id": "Look up a node by property. Payload: id_val (string), id_key (optional, default 'id').",
    "kg_tool.get_neighbors": "Get neighbors of a node. Payload: node_id (string), id_key, direction ('in'|'out'|'both'), relationship_type (optional), limit (optional int).",
    "kg_tool.get_graph_schema": "List node labels and relationship types. Payload: {}.",
    "kg_tool.shortest_path": "Find shortest path between two nodes. Payload: start_id (string), end_id (string), id_key (optional), relationship_type (optional), max_depth (optional int).",
    "kg_tool.get_similar_nodes": "Find structurally similar nodes by shared neighbors. Payload: node_id (string), id_key (optional), limit (optional int).",
    "kg_tool.fulltext_search": "Full-text search via Neo4j index. Payload: index_name (string), query_string (string), limit (optional int).",
    "kg_tool.bulk_export": "Read-only Cypher export as JSON or CSV. Payload: cypher (string), params (optional), format ('json'|'csv'), row_limit (optional int).",
    "kg_tool.bulk_create_nodes": "Create/merge nodes. Payload: nodes (list of dicts), label (optional string), id_key (optional string).",
    # sql_tool
    "sql_tool.run_query": "Execute SQL. Payload: query (string), params (optional).",
    "sql_tool.explain_query": "Return SQL query plan. Payload: query (string), params (optional), analyze (optional bool).",
    "sql_tool.export_results": "Run SQL and return JSON/CSV. Payload: query (string), params (optional), format ('json'|'csv'), row_limit (optional int).",
    "sql_tool.connection_health_check": "Test PostgreSQL connectivity. Payload: {}.",
    # market_tool
    "market_tool.get_stock_data_yf": "OHLCV historical data (yfinance). Payload: symbol (string), start_date (yyyy-mm-dd), end_date (yyyy-mm-dd).",
    "market_tool.get_stock_data": "OHLCV historical data (vendor-routed). Same payload as get_stock_data_yf.",
    "market_tool.get_fundamentals_yf": "Company fundamentals (P/E, sector, market cap) via yfinance. Payload: ticker or symbol (string).",
    "market_tool.get_fundamentals": "Company fundamentals (vendor-routed). Same payload as get_fundamentals_yf.",
    "market_tool.get_balance_sheet_yf": "Balance sheet via yfinance. Payload: ticker (string), freq (optional 'quarterly'|'annual').",
    "market_tool.get_balance_sheet": "Balance sheet (vendor-routed). Same payload as get_balance_sheet_yf.",
    "market_tool.get_cashflow_yf": "Cash flow statement via yfinance. Payload: ticker (string), freq (optional).",
    "market_tool.get_cashflow": "Cash flow statement (vendor-routed). Same payload as get_cashflow_yf.",
    "market_tool.get_income_statement_yf": "Income statement via yfinance. Payload: ticker (string), freq (optional).",
    "market_tool.get_income_statement": "Income statement (vendor-routed). Same payload as get_income_statement_yf.",
    "market_tool.get_insider_transactions_yf": "Insider buy/sell transactions via yfinance. Payload: ticker (string).",
    "market_tool.get_insider_transactions": "Insider transactions (vendor-routed). Same payload as get_insider_transactions_yf.",
    "market_tool.get_news_yf": "Recent ticker news via yfinance. Payload: symbol (string), limit (optional int).",
    "market_tool.get_news": "Recent ticker news (vendor-routed). Same payload as get_news_yf.",
    "market_tool.get_global_news_yf": "Global/macro financial news via yfinance. Payload: as_of_date (optional yyyy-mm-dd), look_back_days (optional int), limit (optional int).",
    "market_tool.get_global_news": "Global news (vendor-routed). Same payload as get_global_news_yf.",
    "market_tool.get_ticker_info": "Concise ticker metadata (name, exchange, sector). Payload: symbol or ticker (string).",
    "market_tool.get_news_dify": "Ticker news in Dify-compatible format. Payload: symbol (string), limit (optional int), start_date (optional), end_date (optional).",
    "market_tool.get_stock_analytics": "Combined price/volume analytics for a ticker. Payload: symbol (string), start_date (yyyy-mm-dd), end_date (yyyy-mm-dd).",
    # analyst_tool
    "analyst_tool.get_indicators_yf": "Technical indicators (SMA, RSI, MACD, etc.) via yfinance. Payload: symbol (string), indicator (e.g. sma_50, rsi, macd, boll, atr), as_of_date (yyyy-mm-dd), look_back_days (int).",
    "analyst_tool.get_indicators": "Technical indicators (vendor-routed). Same payload as get_indicators_yf.",
    # capabilities
    "get_capabilities": "List registered MCP tools and backend status (neo4j, postgres, milvus). Payload: {}.",
}


# ---------------------------------------------------------------------------
# Allowed tool name sets per agent — derived from docs/agent-tools-reference.md
# "Summary: tools available per agent" table.
# ---------------------------------------------------------------------------
LIBRARIAN_ALLOWED_TOOL_NAMES: frozenset[str] = frozenset([
    "file_tool.read_file",
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
    "market_tool.get_stock_data_yf",
    "market_tool.get_stock_data",
    "market_tool.get_fundamentals_yf",
    "market_tool.get_fundamentals",
    "market_tool.get_balance_sheet_yf",
    "market_tool.get_balance_sheet",
    "market_tool.get_cashflow_yf",
    "market_tool.get_cashflow",
    "market_tool.get_income_statement_yf",
    "market_tool.get_income_statement",
    "market_tool.get_insider_transactions_yf",
    "market_tool.get_insider_transactions",
    "market_tool.get_news_yf",
    "market_tool.get_news",
    "market_tool.get_global_news_yf",
    "market_tool.get_global_news",
    "market_tool.get_ticker_info",
    "market_tool.get_news_dify",
    "market_tool.get_stock_analytics",
    "get_capabilities",
])

ANALYST_ALLOWED_TOOL_NAMES: frozenset[str] = frozenset([
    "analyst_tool.get_indicators_yf",
    "analyst_tool.get_indicators",
    "get_capabilities",
])


# ---------------------------------------------------------------------------
# Convenience lists for ordering tool entries in prompts (ordered by usefulness).
# Each list contains tool names; descriptions are fetched from TOOL_DESCRIPTIONS_BY_NAME.
# ---------------------------------------------------------------------------
_LIBRARIAN_TOOL_ORDER: list[str] = [
    "file_tool.read_file",
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
    "market_tool.get_fundamentals_yf",
    "market_tool.get_fundamentals",
    "market_tool.get_stock_data_yf",
    "market_tool.get_stock_data",
    "market_tool.get_news_yf",
    "market_tool.get_news",
    "market_tool.get_global_news_yf",
    "market_tool.get_global_news",
    "market_tool.get_balance_sheet_yf",
    "market_tool.get_balance_sheet",
    "market_tool.get_cashflow_yf",
    "market_tool.get_cashflow",
    "market_tool.get_income_statement_yf",
    "market_tool.get_income_statement",
    "market_tool.get_insider_transactions_yf",
    "market_tool.get_insider_transactions",
    "market_tool.get_ticker_info",
    "market_tool.get_stock_analytics",
    "market_tool.get_news_dify",
    "get_capabilities",
]

_ANALYST_TOOL_ORDER: list[str] = [
    "analyst_tool.get_indicators_yf",
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


def get_librarian_tool_descriptions() -> str:
    """Return prompt-ready tool descriptions for the Librarian (allowed pool only)."""
    return _build_descriptions_string(_LIBRARIAN_TOOL_ORDER)


def get_websearcher_tool_descriptions() -> str:
    """Return prompt-ready tool descriptions for the WebSearcher (allowed pool only)."""
    return _build_descriptions_string(_WEBSEARCHER_TOOL_ORDER)


def get_analyst_tool_descriptions() -> str:
    """Return prompt-ready tool descriptions for the Analyst (allowed pool only)."""
    return _build_descriptions_string(_ANALYST_TOOL_ORDER)


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
