# Agent Tools Reference

This document lists every MCP tool available in OpenFund-AI, with callable format, payload parameters, and sample calls. It is intended as a reference for agents to know what they can call and how.

**How to call a tool:**

```python
result = mcp_client.call_tool("<tool_name>", { ...payload... })
```

`tool_name` is a dot-separated string (e.g. `"file_tool.read_file"`). The payload is a plain dict. The response is always a dict; on failure it contains an `"error"` key.

When **Librarian**, **WebSearcher**, or **Analyst** receive a request from the Planner, they use an **LLM call** with a prompt and the **tool descriptions in this document** (and their per-agent tool list) to determine **which tools to call and with what parameters**. They then execute those tool calls via `mcp_client.call_tool(tool_name, payload)`. The "Summary: tools available per agent" and the per-agent "tool selection guide" tables below are the **tool-description input** for that LLM (or for human reference).

**Code sync:** The allowed tool sets for each agent are maintained in `llm/tool_descriptions.py` (`LIBRARIAN_ALLOWED_TOOL_NAMES`, `WEBSEARCHER_ALLOWED_TOOL_NAMES`, `ANALYST_ALLOWED_TOOL_NAMES`). The LLM prompt for each agent is injected with only that agent's tool descriptions, and any tool name the LLM returns outside the allowed set is discarded at runtime by `filter_tool_calls_to_allowed()` before execution. Keep this document and `llm/tool_descriptions.py` in sync when adding or removing tools.

All tools are registered in the **FastMCP** server (`openfund_mcp/fastmcp_server.py`) and in `MCPServer.register_default_tools()` for in-process tests (`openfund_mcp/mcp_server.py`). The API and agents use **MCPClient** to call the FastMCP server over stdio. `market_tool` and `analyst_tool` are optional — they are skipped if their dependencies (e.g. `pandas`) are not installed.

---

## file_tool

#### file_tool.read_file

- **Description:** Read file content and metadata from disk. When `MCP_FILE_BASE_DIR` is set, paths outside that directory are rejected.
- **Payload:** `path` (required, string) — absolute or relative file path.
- **Returns:** `{"content": str, "path": str}` on success; `{"error": str, "path": str}` on failure.
- **Sample call:**
  ```json
  { "path": "/data/fund_facts.txt" }
  ```

---

## vector_tool

Backed by Milvus (`MILVUS_URI`). When `MILVUS_URI` is unset, all calls return mock data.

#### vector_tool.search

- **Description:** Semantic search over the vector database. Returns the top-k most relevant documents for a query.
- **Payload:** `query` (required, string), `top_k` (optional, int, default 5), `filter` (optional, dict — e.g. `fund_id`, `source` for metadata filtering).
- **Returns:** `{"documents": [{"id": ..., "content": ..., "score": ...}, ...]}`
- **Sample call:**
  ```json
  { "query": "NVDA fund performance 2024", "top_k": 5 }
  ```

#### vector_tool.get_by_ids

- **Description:** Retrieve documents by their IDs from the vector collection.
- **Payload:** `ids` (required, list of strings), `collection_name` (optional, string).
- **Returns:** `{"entities": [...]}` (each entity has `id`, `content`, `fund_id`, `source`, etc.) or `{"error": str}`.
- **Sample call:**
  ```json
  { "ids": ["doc_001", "doc_002"] }
  ```

#### vector_tool.upsert_documents

- **Description:** Insert or update documents in the vector collection (embeddings are computed automatically).
- **Payload:** `docs` (required, list of dicts; each dict must have `"id"` and `"content"`; optional metadata: `fund_id`, `source`).
- **Returns:** `{"upserted": int}` or `{"error": str}`.
- **Sample call:**
  ```json
  { "docs": [{"id": "doc_003", "content": "NVDA Q4 2024 earnings summary."}] }
  ```

#### vector_tool.health_check

- **Description:** Check connectivity and status of the Milvus backend.
- **Payload:** _(empty)_
- **Returns:** `{"ok": true}` or `{"ok": false, "error": str}`.
- **Sample call:**
  ```json
  {}
  ```

#### vector_tool.create_collection_from_config

- **Description:** Create a new Milvus collection from explicit configuration (name, dimension, key field, scalar fields, index params).
- **Payload:** `name` (required, string), `dimension` (optional, int, default 384), `primary_key_field` (optional, string, default `"id"`), `scalar_fields` (optional, list), `index_params` (optional, dict).
- **Returns:** `{"ok": true, "name": str}` or `{"error": str}`.
- **Sample call:**
  ```json
  { "name": "fund_docs_v2", "dimension": 768, "primary_key_field": "id" }
  ```

---

## kg_tool

Backed by Neo4j (`NEO4J_URI`). When `NEO4J_URI` is unset, all calls return mock/empty data.

#### kg_tool.query_graph

- **Description:** Run a raw Cypher query against Neo4j and return the results.
- **Payload:** `cypher` (required, string), `params` (optional, dict of Cypher parameters).
- **Returns:** `{"rows": [...], "params": {...}}` (row keys are the column names) or `{"error": str}`.
- **Sample call:**
  ```json
  { "cypher": "MATCH (f:Fund {symbol: $sym}) RETURN f", "params": {"sym": "NVDA"} }
  ```

#### kg_tool.get_relations

- **Description:** Get all relationships and connected nodes for a named entity (e.g. fund or company).
- **Payload:** `entity` (required, string) — entity name or identifier.
- **Returns:** `{"nodes": [...], "edges": [...]}` or `{"error": str}`.
- **Sample call:**
  ```json
  { "entity": "NVDA" }
  ```

#### kg_tool.get_node_by_id

- **Description:** Look up a single node by a specific property value.
- **Payload:** `id_val` (required, string — the value to match), `id_key` (optional, string, default `"id"` — the property name to match on).
- **Returns:** `{"node": {...}}` or `{"node": null}` if not found.
- **Sample call:**
  ```json
  { "id_val": "NVDA", "id_key": "symbol" }
  ```

#### kg_tool.get_neighbors

- **Description:** Get immediate neighbors of a node, with optional direction and relationship-type filters.
- **Payload:** `node_id` (required, string), `id_key` (optional, string, default `"id"`), `direction` (optional: `"in"` | `"out"` | `"both"`, default `"both"`), `relationship_type` (optional, string), `limit` (optional, int, default 100).
- **Returns:** `{"nodes": [...], "relationships": [...]}` or `{"error": str}`.
- **Sample call:**
  ```json
  { "node_id": "NVDA", "id_key": "symbol", "direction": "out", "relationship_type": "IN_SECTOR", "limit": 20 }
  ```

#### kg_tool.get_graph_schema

- **Description:** List all node labels and relationship types present in the graph.
- **Payload:** _(empty)_
- **Returns:** `{"node_labels": [...], "relationship_types": [...]}`.
- **Sample call:**
  ```json
  {}
  ```

#### kg_tool.shortest_path

- **Description:** Find the shortest path between two nodes by their ID property values.
- **Payload:** `start_id` (required, string), `end_id` (required, string), `id_key` (optional, string, default `"id"`), `relationship_type` (optional, string), `max_depth` (optional, int, default 15).
- **Returns:** `{"paths": [{"nodes": [...], "relationships": [...]}, ...]}` or `{"paths": []}` if none found.
- **Sample call:**
  ```json
  { "start_id": "NVDA", "end_id": "AAPL", "id_key": "symbol", "max_depth": 5 }
  ```

#### kg_tool.get_similar_nodes

- **Description:** Find nodes similar to a given node by shared 1-hop neighbors (structural similarity).
- **Payload:** `node_id` (required, string), `id_key` (optional, string, default `"id"`), `limit` (optional, int, default 10).
- **Returns:** `{"nodes": [{"id": ..., "score": ...}, ...]}`.
- **Sample call:**
  ```json
  { "node_id": "NVDA", "id_key": "symbol", "limit": 5 }
  ```

#### kg_tool.fulltext_search

- **Description:** Query nodes via a Neo4j full-text index (`db.index.fulltext.queryNodes`). Requires a pre-existing index.
- **Payload:** `index_name` (required, string), `query_string` (required, string), `limit` (optional, int, default 50).
- **Returns:** `{"nodes": [...]}` or `{"error": str}`.
- **Sample call:**
  ```json
  { "index_name": "fund_fulltext", "query_string": "semiconductor AI chips", "limit": 10 }
  ```

#### kg_tool.bulk_export

- **Description:** Run a read-only Cypher query and return results as JSON or CSV. Only `MATCH` / `CALL` queries are allowed; write operations are rejected.
- **Payload:** `cypher` (required, string — must be read-only), `params` (optional, dict), `format` (optional: `"json"` | `"csv"`, default `"json"`), `row_limit` (optional, int, default 1000).
- **Returns:** `{"data": <list of dicts for format "json", CSV string for format "csv">, "format": "json"|"csv"}` or `{"error": str}`.
- **Sample call:**
  ```json
  { "cypher": "MATCH (f:Fund) RETURN f.symbol, f.name LIMIT 100", "format": "json" }
  ```

#### kg_tool.bulk_create_nodes

- **Description:** Create or merge multiple nodes in the graph from a list of dicts (uses `MERGE` to avoid duplicates).
- **Payload:** `nodes` (required, list of dicts), `label` (optional, string — Neo4j node label, default `"Node"`), `id_key` (optional, string, default `"id"`).
- **Returns:** `{"created": int}` or `{"error": str}`.
- **Sample call:**
  ```json
  { "nodes": [{"id": "TSMC", "name": "Taiwan Semiconductor"}], "label": "Company", "id_key": "id" }
  ```

---

## sql_tool

Backed by PostgreSQL (`DATABASE_URL`). When `DATABASE_URL` is unset, calls return mock data.

**Schema:** Use only the tables and columns defined in [fund-data-schema.md](fund-data-schema.md). Key tables: `fund_info`, `fund_performance`, `fund_risk_metrics`, `fund_holdings` (use `fund_symbol`, not `fund_id`), `fund_sector_allocation`, `fund_flows`; for stocks: `stock_ohlcv`, `company_fundamentals`, `financial_statements`. Do not use: `financials`, `revenue_segments`, `fund_returns`, `fund_sector_exposures`, or column `fund_id` in `fund_holdings`.

#### sql_tool.run_query

- **Description:** Execute a SQL query with optional parameterized values. Returns rows as a list of dicts. Use only tables/columns from the documented schema (see fund-data-schema.md).
- **Payload:** `query` (required, string — use `%s` or `%(name)s` for psycopg2 parameters), `params` (optional, dict or tuple).
- **Returns:** `{"rows": [...], "schema": [...], "params": {...}}` or `{"error": str}`.
- **Sample call:**
  ```json
  { "query": "SELECT symbol, name, total_assets_billion FROM fund_info WHERE symbol = %s", "params": ["VOO"] }
  ```

#### sql_tool.explain_query

- **Description:** Return the query plan for a SQL statement (uses `EXPLAIN` or `EXPLAIN ANALYZE`).
- **Payload:** `query` (required, string), `params` (optional), `analyze` (optional, bool, default false — if true uses `EXPLAIN ANALYZE`).
- **Returns:** `{"plan": [...], "schema": [...], "params": {...}}` or `{"error": str}`.
- **Sample call:**
  ```json
  { "query": "SELECT symbol, total_assets_billion FROM fund_info WHERE total_assets_billion > 100", "analyze": false }
  ```

#### sql_tool.export_results

- **Description:** Run a SQL query and return results as JSON or CSV, with an optional row limit. Use only schema from fund-data-schema.md.
- **Payload:** `query` (required, string), `params` (optional), `format` (optional: `"json"` | `"csv"`, default `"json"`), `row_limit` (optional, int, default 1000).
- **Returns:** `{"data": ...}` (list of dicts for JSON, CSV string for CSV), `"schema": [...]`, `"row_count": int`; or `{"error": str}`.
- **Sample call:**
  ```json
  { "query": "SELECT symbol, name, total_assets_billion FROM fund_info ORDER BY total_assets_billion DESC", "format": "csv", "row_limit": 500 }
  ```

#### sql_tool.connection_health_check

- **Description:** Test connectivity to the PostgreSQL backend.
- **Payload:** _(empty)_
- **Returns:** `{"ok": true}` or `{"ok": false, "error": str}`.
- **Sample call:**
  ```json
  {}
  ```

---

## market_tool _(optional — requires `pandas`)_

**Vendor routing:** Vendor-agnostic tools route to the configured vendor (`MCP_MARKET_VENDOR`: `alpha_vantage` (default) or `finnhub`; unset or invalid → `alpha_vantage`). No yfinance; Alpha Vantage or Finnhub only.

When the backend is unavailable or the dependency is missing, calls return `{"error": str}`.

#### market_tool.get_stock_data

- **Description:** Fetch OHLCV historical price data for a ticker over a date range.
- **Payload:** `symbol` or `ticker` (required, string), `start_date` (required, string `yyyy-mm-dd`), `end_date` (required, string `yyyy-mm-dd`).
- **Returns:** `{"content": str, "timestamp": str}` or `{"error": str}`.
- **Sample call:**
  ```json
  { "symbol": "NVDA", "start_date": "2024-01-01", "end_date": "2024-12-31" }
  ```

#### market_tool.get_balance_sheet

- **Description:** Fetch the balance sheet (assets, liabilities, equity) for a ticker.
- **Payload:** `ticker` or `symbol` (required, string), `freq` (optional: `"quarterly"` | `"annual"`, default `"quarterly"`).
- **Returns:** `{"content": str, "timestamp": str}` or `{"error": str}`.
- **Sample call:**
  ```json
  { "ticker": "MSFT", "freq": "annual" }
  ```

#### market_tool.get_cashflow

- **Description:** Fetch the cash flow statement for a ticker.
- **Payload:** `ticker` or `symbol` (required, string), `freq` (optional: `"quarterly"` | `"annual"`, default `"quarterly"`).
- **Returns:** `{"content": str, "timestamp": str}` or `{"error": str}`.
- **Sample call:**
  ```json
  { "ticker": "TSLA", "freq": "quarterly" }
  ```

#### market_tool.get_income_statement

- **Description:** Fetch the income statement (revenue, net income, EBITDA, etc.) for a ticker.
- **Payload:** `ticker` or `symbol` (required, string), `freq` (optional: `"quarterly"` | `"annual"`, default `"quarterly"`).
- **Returns:** `{"content": str, "timestamp": str}` or `{"error": str}`.
- **Sample call:**
  ```json
  { "ticker": "NVDA", "freq": "quarterly" }
  ```

#### market_tool.get_insider_transactions

- **Description:** Fetch recent insider buy/sell transactions for a ticker.
- **Payload:** `ticker` or `symbol` (required, string).
- **Returns:** `{"content": str, "timestamp": str}` or `{"error": str}`.
- **Sample call:**
  ```json
  { "ticker": "AAPL" }
  ```

#### market_tool.get_news

- **Description:** Fetch recent news headlines for a ticker.
- **Payload:** `symbol` or `ticker` (required, string), `limit` or `count` (optional, int, default 20), `start_date` (optional, string), `end_date` (optional, string).
- **Returns:** `{"content": str, "timestamp": str}` or `{"error": str}`.
- **Sample call:**
  ```json
  { "symbol": "NVDA", "limit": 5 }
  ```

#### market_tool.get_global_news

- **Description:** Fetch recent global financial/market news (not ticker-specific).
- **Payload:** `as_of_date` or `curr_date` (optional, string `yyyy-mm-dd`), `look_back_days` (optional, int, default 7), `limit` (optional, int, default 10).
- **Returns:** `{"content": str, "timestamp": str}` or `{"error": str}`.
- **Sample call:**
  ```json
  { "as_of_date": "2024-12-31", "look_back_days": 7, "limit": 5 }
  ```

---

## analyst_tool _(optional — requires `pandas`)_

#### analyst_tool.get_indicators

- **Description:** Compute technical indicators (SMA, EMA, RSI, MACD, Bollinger Bands, ATR, etc.) from OHLCV data over a lookback window. Routes to Alpha Vantage (`MCP_INDICATOR_VENDOR`: `alpha_vantage` only).
- **Payload:** `symbol` or `ticker` (required, string), `indicator` (required, string — e.g. `close_50_sma`, `close_200_sma`, `rsi`, `macd`, `boll`, `atr`), `as_of_date` or `curr_date` (required, string `yyyy-mm-dd`), `look_back_days` (required, int).
- **Returns:** `{"content": str, "timestamp": str}` or `{"error": str}`.
- **Supported indicators (Alpha Vantage):** `close_50_sma`, `close_200_sma`, `close_10_ema`, `macd`, `macds`, `macdh`, `rsi`, `boll`, `boll_ub`, `boll_lb`, `atr`, `vwma`.
- **Sample call:**
  ```json
  { "symbol": "NVDA", "indicator": "rsi", "as_of_date": "2024-12-31", "look_back_days": 30 }
  ```

---

## get_capabilities

#### get_capabilities

- **Description:** Introspect the MCP server: returns which backends are configured (Neo4j, PostgreSQL, Milvus) and the list of all registered tool names.
- **Payload:** _(empty)_
- **Returns:** `{"neo4j": bool, "postgres": bool, "milvus": bool, "tools": [list of tool names]}`.
- **Sample call:**
  ```json
  {}
  ```

---

## Summary: tools available per agent

Each agent uses `mcp_client.call_tool(...)` to access MCP tools. **Planner** and **Responder** do not call MCP tools directly — the Planner orchestrates agent steps and sends decomposed queries to specialists; the Responder formats the final answer.

| Agent | Tools available |
|---|---|
| **Librarian** | `file_tool.read_file` · `vector_tool.search` · `vector_tool.get_by_ids` · `vector_tool.upsert_documents` · `vector_tool.health_check` · `vector_tool.create_collection_from_config` · `kg_tool.query_graph` · `kg_tool.get_relations` · `kg_tool.get_node_by_id` · `kg_tool.get_neighbors` · `kg_tool.get_graph_schema` · `kg_tool.shortest_path` · `kg_tool.get_similar_nodes` · `kg_tool.fulltext_search` · `kg_tool.bulk_export` · `kg_tool.bulk_create_nodes` · `sql_tool.run_query` · `sql_tool.explain_query` · `sql_tool.export_results` · `sql_tool.connection_health_check` · `get_capabilities` |
| **WebSearcher** | `market_tool.get_fundamentals` · `market_tool.get_stock_data` · `market_tool.get_balance_sheet` · `market_tool.get_cashflow` · `market_tool.get_income_statement` · `market_tool.get_insider_transactions` · `market_tool.get_news` · `market_tool.get_global_news` · `get_capabilities` |
| **Analyst** | `analyst_tool.get_indicators` · `get_capabilities` |
| **Planner** | _(none — orchestrates specialists and sends decomposed queries via ACL)_ |
| **Responder** | _(none — formats the final answer)_ |

### Librarian: tool selection guide

| Content need | Tool to call |
|---|---|
| Read a known file | `file_tool.read_file` |
| Semantic search over fund documents | `vector_tool.search` |
| Fetch fund/entity graph relationships | `kg_tool.get_relations` |
| Look up a node by ID | `kg_tool.get_node_by_id` |
| Graph traversal / custom Cypher | `kg_tool.query_graph` |
| Full-text keyword search | `kg_tool.fulltext_search` |
| SQL query (structured data) | `sql_tool.run_query` |
| Export data as CSV | `sql_tool.export_results` or `kg_tool.bulk_export` |

### WebSearcher: tool selection guide

| Content need | Tool to call |
|---|---|
| Company / fund overview (fundamentals) | `market_tool.get_fundamentals` |
| Recent news / sentiment | `market_tool.get_news` |
| Global macro / regulatory news | `market_tool.get_global_news` |
| Historical price data | `market_tool.get_stock_data` |
| Financials (balance sheet, income) | `market_tool.get_balance_sheet`, `market_tool.get_income_statement` |
| Insider activity | `market_tool.get_insider_transactions` |

### Analyst: tool selection guide

| Content need | Tool to call |
|---|---|
| Technical indicator (SMA, RSI, MACD, etc.) | `analyst_tool.get_indicators` |
| Vendor-routed indicator | `analyst_tool.get_indicators` |
