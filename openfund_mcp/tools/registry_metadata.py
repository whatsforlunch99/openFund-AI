"""Canonical tool descriptions and per-agent allowlists."""

from __future__ import annotations

from typing import Any

TOOL_DESCRIPTIONS_BY_NAME: dict[str, str] = {
    "file_tool.read_file": "Read file content. Payload: path (string).",
    "vector_tool.search": "Semantic search over documents. Payload: query (string), top_k (optional int, default 5), filter (optional dict, e.g. fund_id, source).",
    "vector_tool.get_by_ids": "Retrieve entities by IDs. Payload: ids (list of strings), collection_name (optional). Returns entities.",
    "vector_tool.upsert_documents": "Insert or update documents in vector collection. Payload: docs (list of dicts with 'id' and 'content').",
    "vector_tool.health_check": "Check Milvus connectivity. Payload: {}.",
    "vector_tool.create_collection_from_config": "Create a new Milvus collection. Payload: name (string), dimension (optional int), primary_key_field (optional), scalar_fields (optional), index_params (optional).",
    "kg_tool.query_graph": "Run Cypher query. Payload: cypher (string), params (optional dict).",
    "kg_tool.get_relations": "Get 1-hop Neo4j relationships for a company/fund. Payload: entity (string)—symbol, node_id, or name; optional prefer_dataset (e.g. equities, etfs) to bias matches when the user asked about a specific asset class.",
    "kg_tool.get_node_by_id": "Look up a node by property. Payload: id_val (string), id_key (optional, default 'id').",
    "kg_tool.get_neighbors": "Get neighbors of a node. Payload: node_id (string), id_key, direction ('in'|'out'|'both'), relationship_type (optional), limit (optional int).",
    "kg_tool.get_graph_schema": "List node labels and relationship types. Payload: {}.",
    "kg_tool.shortest_path": "Find shortest path between two nodes. Payload: start_id (string), end_id (string), id_key (optional), relationship_type (optional), max_depth (optional int).",
    "kg_tool.get_similar_nodes": "Find structurally similar nodes by shared neighbors. Payload: node_id (string), id_key (optional), limit (optional int).",
    "kg_tool.fulltext_search": "Full-text search via Neo4j index. Payload: index_name (string), query_string (string), limit (optional int).",
    "kg_tool.bulk_export": "Read-only Cypher export as JSON or CSV. Payload: cypher (string), params (optional), format ('json'|'csv'), row_limit (optional int).",
    "kg_tool.bulk_create_nodes": "Create/merge nodes. Payload: nodes (list of dicts), label (optional string), id_key (optional string).",
    "sql_tool.run_query": "Execute SQL on PostgreSQL. Use only tables/columns from the schema in your instructions (e.g. yahoo_quote_metrics, yahoo_fundamentals_metrics, yahoo_timeseries, index_symbol_map). Payload: query (string), params (optional dict or list/tuple for positional %s).",
    "sql_tool.explain_query": "Return SQL query plan. Payload: query (string), params (optional), analyze (optional bool).",
    "sql_tool.export_results": "Run SQL and return JSON/CSV. Use only schema from instructions. Payload: query (string), params (optional dict for %(name)s or list/tuple for positional %s — e.g. [\"AAPL\"] for one %s), format ('json'|'csv'), row_limit (optional int).",
    "sql_tool.connection_health_check": "Test PostgreSQL connectivity. Payload: {}.",
    "market_tool.get_fundamentals": "Company fundamentals/overview (vendor-routed). Payload: symbol or ticker (string).",
    "market_tool.get_stock_data": "OHLCV historical data (vendor-routed). Payload: symbol (string), start_date (yyyy-mm-dd), end_date (yyyy-mm-dd).",
    "market_tool.get_balance_sheet": "Balance sheet (vendor-routed). Payload: ticker (string), freq (optional 'quarterly'|'annual').",
    "market_tool.get_cashflow": "Cash flow statement (vendor-routed). Payload: ticker (string), freq (optional).",
    "market_tool.get_income_statement": "Income statement (vendor-routed). Payload: ticker (string), freq (optional).",
    "market_tool.get_insider_transactions": "Insider transactions (vendor-routed). Payload: ticker (string).",
    "market_tool.get_news": "Recent ticker news (vendor-routed). Payload: symbol (string), limit (optional int), start_date, end_date.",
    "market_tool.get_global_news": "Global/macro financial news (vendor-routed). Payload: as_of_date (required yyyy-mm-dd), look_back_days (optional int), limit (optional int).",
    "fund_catalog_tool.search": "Search ETFs/mutual funds by name or query. Payload: query or name (string), limit (optional int, default 10). Returns matches with symbol, name, asset_class.",
    "stooq_tool.get_price": "Latest price from stooq. Payload: symbol (string). Returns price, close, date, timestamp.",
    "yahoo_finance_tool.get_price": "Latest price from Yahoo Finance. Payload: symbol (string). Returns price, close, date, timestamp.",
    "yahoo_finance_tool.get_fundamental": "Yahoo quoteSummary fundamentals: price + ETF/fund stats (expense ratio, AUM, holdings/sector when available). Payload: symbol (string). Returns parsed fields plus raw modules.",
    "etfdb_tool.get_fund_data": "ETF fundamentals from ETFdb: expense ratio, AUM, holdings. Payload: symbol (string). Returns expense_ratio, aum, holdings_top10.",
    "news_tool.search_rss": "Search news via Google News RSS. Payload: query (required string), days (optional int, default 7). Returns items with title, link, published, source.",
    "news_tool.search_yahoo_rss": "Fetch finance news from Yahoo Finance RSS (fixed feed, no query). Payload: limit (optional int, default 20). Returns items with title, link, published, source.",
    "news_tool.search_gdelt": "Search news via GDELT API (free, no key; may 429). Payload: query (required string), limit (optional int, default 10). Returns items with title, link, published, source.",
    "news_tool.search_playwright": "Fetch a web page via Playwright and extract headline when no API/RSS exists. Payload: url (required string).",
    "analyst_tool.get_indicators": "Technical indicators only (SMA, RSI, MACD, etc.) — not raw OHLCV. Do not use indicator close/open/high/low/volume; use market_tool.get_stock_data or sql_tool for price series. Payload: symbol (string), indicator (e.g. close_50_sma, rsi, macd, boll, atr), as_of_date (yyyy-mm-dd), look_back_days (int).",
    "get_capabilities": "List registered MCP tools and backend status (neo4j, postgres, milvus). Payload: {}.",
}

LIBRARIAN_ALLOWED_TOOL_NAMES: frozenset[str] = frozenset([
    "file_tool.read_file", "vector_tool.search", "vector_tool.get_by_ids", "vector_tool.upsert_documents",
    "vector_tool.health_check", "vector_tool.create_collection_from_config", "kg_tool.query_graph",
    "kg_tool.get_relations", "kg_tool.get_node_by_id", "kg_tool.get_neighbors", "kg_tool.get_graph_schema",
    "kg_tool.shortest_path", "kg_tool.get_similar_nodes", "kg_tool.fulltext_search", "kg_tool.bulk_export",
    "kg_tool.bulk_create_nodes", "sql_tool.run_query", "sql_tool.explain_query", "sql_tool.export_results",
    "sql_tool.connection_health_check", "get_capabilities",
])
WEBSEARCHER_ALLOWED_TOOL_NAMES: frozenset[str] = frozenset([
    "fund_catalog_tool.search", "news_tool.search_rss", "news_tool.search_yahoo_rss", "news_tool.search_gdelt", "news_tool.search_playwright",
    "stooq_tool.get_price", "yahoo_finance_tool.get_fundamental", "yahoo_finance_tool.get_price",
    "etfdb_tool.get_fund_data", "market_tool.get_fundamentals", "market_tool.get_stock_data",
    "market_tool.get_balance_sheet", "market_tool.get_cashflow", "market_tool.get_income_statement",
    "market_tool.get_insider_transactions", "market_tool.get_news", "market_tool.get_global_news",
    "get_capabilities",
])
ANALYST_ALLOWED_TOOL_NAMES: frozenset[str] = frozenset(["analyst_tool.get_indicators", "get_capabilities"])

_LIBRARIAN_TOOL_ORDER: list[str] = [
    "file_tool.read_file", "vector_tool.search", "vector_tool.get_by_ids", "vector_tool.upsert_documents",
    "vector_tool.health_check", "vector_tool.create_collection_from_config", "kg_tool.get_relations",
    "kg_tool.get_node_by_id", "kg_tool.query_graph", "kg_tool.get_neighbors", "kg_tool.get_graph_schema",
    "kg_tool.shortest_path", "kg_tool.get_similar_nodes", "kg_tool.fulltext_search", "kg_tool.bulk_export",
    "kg_tool.bulk_create_nodes", "sql_tool.run_query", "sql_tool.explain_query", "sql_tool.export_results",
    "sql_tool.connection_health_check", "get_capabilities",
]
_WEBSEARCHER_TOOL_ORDER: list[str] = [
    "fund_catalog_tool.search", "news_tool.search_rss", "news_tool.search_yahoo_rss", "news_tool.search_gdelt", "news_tool.search_playwright",
    "stooq_tool.get_price", "yahoo_finance_tool.get_fundamental", "yahoo_finance_tool.get_price",
    "etfdb_tool.get_fund_data", "market_tool.get_fundamentals", "market_tool.get_stock_data",
    "market_tool.get_news", "market_tool.get_global_news", "market_tool.get_balance_sheet",
    "market_tool.get_cashflow", "market_tool.get_income_statement", "market_tool.get_insider_transactions",
    "get_capabilities",
]
_ANALYST_TOOL_ORDER: list[str] = ["analyst_tool.get_indicators", "get_capabilities"]


def _build_descriptions_string(tool_names: list[str]) -> str:
    return "\n".join(f"- {name}: {TOOL_DESCRIPTIONS_BY_NAME.get(name, 'No description available.')}" for name in tool_names)


def get_librarian_tool_descriptions(registered_tool_names: set[str] | None = None) -> str:
    order = [n for n in _LIBRARIAN_TOOL_ORDER if n in registered_tool_names] if registered_tool_names is not None else _LIBRARIAN_TOOL_ORDER
    return _build_descriptions_string(order)


def get_websearcher_tool_descriptions(registered_tool_names: set[str] | None = None) -> str:
    order = [n for n in _WEBSEARCHER_TOOL_ORDER if n in registered_tool_names] if registered_tool_names is not None else _WEBSEARCHER_TOOL_ORDER
    return _build_descriptions_string(order)


def get_analyst_tool_descriptions(registered_tool_names: set[str] | None = None) -> str:
    order = [n for n in _ANALYST_TOOL_ORDER if n in registered_tool_names] if registered_tool_names is not None else _ANALYST_TOOL_ORDER
    return _build_descriptions_string(order)


def normalize_tool_calls(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        tool = item.get("tool") or item.get("tool_name")
        if not isinstance(tool, str) or not tool.strip():
            continue
        payload = item.get("payload")
        payload = {} if not isinstance(payload, dict) else dict(payload)
        result.append({"tool": tool.strip(), "payload": payload})
    return result


def filter_tool_calls_to_allowed(tool_calls: list[dict[str, Any]], allowed_names: frozenset[str]) -> list[dict[str, Any]]:
    filtered = []
    for tc in tool_calls:
        tool = tc.get("tool") or tc.get("tool_name") or ""
        if tool in allowed_names:
            filtered.append(tc)
    return filtered


LIBRARIAN_TOOLS: list[dict] = [{"name": n, "description": TOOL_DESCRIPTIONS_BY_NAME.get(n, "")} for n in _LIBRARIAN_TOOL_ORDER]
WEBSEARCHER_TOOLS: list[dict] = [{"name": n, "description": TOOL_DESCRIPTIONS_BY_NAME.get(n, "")} for n in _WEBSEARCHER_TOOL_ORDER]
ANALYST_TOOLS: list[dict] = [{"name": n, "description": TOOL_DESCRIPTIONS_BY_NAME.get(n, "")} for n in _ANALYST_TOOL_ORDER]

