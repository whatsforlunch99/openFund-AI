# Backend tool function suggestions

This note suggests additional MCP tool functions that could be added for each backend. **Not all are implemented**; only what is needed for populate/relocate is in place. These are design suggestions for clarity, safety, and agent discoverability.

---

## Suggested named helpers (per backend)

The following are **suggested named helpers** — thin wrappers over existing primitives for clarity and safety.

---

### Neo4j (kg_tool)

- **Existing:** `query_graph(cypher, params)` can run any Cypher (MATCH, MERGE, SET, DETACH DELETE, etc.). Callers can pass the right Cypher to list entities, list relationships, update or delete.
- **Suggested named helpers** (for clarity and safety; thin wrappers over `query_graph` or driver):
  - `get_all_nodes()` — e.g. `MATCH (n) RETURN n` (or with label filter). Useful for agents to discover graph contents.
  - `get_all_relationships()` — e.g. `MATCH ()-[r]->() RETURN type(r), startNode(r), endNode(r)`. Discovery of relationship types and structure.
  - `update_node(id, props)` — MERGE node by id + SET props. Safer than raw Cypher for simple updates.
  - `delete_node(id)` — DETACH DELETE by id. Clear intent and consistent error handling.
- **Implemented:** `get_all_nodes(label?)`, `get_all_relationships(limit?)`, `update_node(id_val, props, id_key="id")`, `delete_node(id_val, id_key="id")`. All use parameterized Cypher via `query_graph`; label and `id_key` are validated as identifiers.

---

### PostgreSQL (sql_tool)

- **Existing:** `run_query(query, params)` covers CRUD and DDL. Agents can run any SQL.
- **Suggested helpers** (for discovery and schema introspection):
  - `list_tables()` — e.g. query information_schema or pg_catalog to return table names. Helps agents know what tables exist.
  - `get_table_schema(table_name)` — return column names and types for a table. Useful for building correct queries.
- **Implemented:** `list_tables()` (information_schema, mock when DATABASE_URL unset), `get_table_schema(table_name)` (parameterized query; `table_name` validated as identifier or `schema.identifier`).

---

### Milvus (vector_tool)

- **Existing:** `search`, `index_documents`, `delete_by_expr` cover search, index, and delete.
- **Suggested helpers** (for discovery and debugging):
  - `list_collections()` — return collection names (e.g. from utility.list_collections()). Lets agents see which collections exist.
  - `get_collection_info(name)` — schema, row count, index info for a collection.
  - `count(expr)` — count entities matching an expression (e.g. `source == "demo"`). Useful for verifying populate or debugging.
- **Implemented:** `list_collections()` (error when MILVUS_URI unset), `get_collection_info(name?)` (schema_fields + count), `count(expr?)` (filtered or total count).

Implement when needed; prefer minimal surface and reuse of existing primitives.

---

## Community-common tools

Patterns that show up often in the community for each backend (and optionally general cross-backend). Documented here as **design/suggestion only**; no new code implementations in `mcp/tools` unless explicitly added later.

### Neo4j / graph tools

Operations commonly expected in graph-backed agents and integrations:

| Pattern | Description | Typical use cases |
|--------|-------------|-------------------|
| **Get node by id** | Look up a single node by internal id or by a domain id property (e.g. `entity_id`). | Knowledge graphs, entity cards, detail views. |
| **Get neighbors / N-hop expansion** | Return nodes connected to a given node at 1 hop, or up to N hops with optional relationship-type filter. | Exploration, context gathering, “what is connected to X?” |
| **Shortest path** | Find one or more shortest paths between two nodes (unweighted or weighted). | Recommendations, fraud detection, dependency chains. |
| **Similarity / recommendation-style** | “Nodes similar to X” (e.g. by shared neighbors, embeddings on nodes, or graph algorithms). | Recommendations, related entities, “more like this.” |
| **Graph schema** | List node labels, relationship types, and optionally property keys per label/type. | Agent discovery, query building, documentation. |
| **Full-text index search** | Query nodes (or relationships) via full-text index (e.g. `db.index.fulltext.queryNodes`). | Search over text properties in a graph. |
| **Bulk import/export** | Batch load from CSV/JSON or export subgraphs (e.g. via APOC or `LOAD CSV`). | ETL, backups, graph migration. |

*Use cases referenced: knowledge graphs, recommendations, fraud detection, dependency/impact analysis — no implementation implied.*

---

### PostgreSQL / SQL tools

Operations commonly expected in SQL/DB agents and DBA-style tools:

| Pattern | Description | Typical use cases |
|--------|-------------|-------------------|
| **Read-only vs write separation** | A “safe” path that only allows `SELECT` (or read-only role); write operations through a separate tool or parameter. | Agent safety, avoiding accidental DDL/DML. |
| **List tables / schemas** | Return table names, optionally filtered by schema (e.g. `information_schema.tables`, `pg_tables`). | Discovery, “what can I query?” |
| **Describe table** | Return column names, types, nullability, defaults for a given table (e.g. `information_schema.columns` or `pg_catalog`). | Query construction, validation. |
| **Explain query** | Run `EXPLAIN` (or `EXPLAIN ANALYZE`) for a read-only query and return the plan. | Performance tuning, teaching, debugging. |
| **Export results** | Return result set as CSV or JSON (or stream), with optional row limit. | Reporting, data extraction, integrations. |
| **Connection health check** | Simple ping or `SELECT 1` to verify connectivity and optional role/schema. | Startup checks, retries, agent capability checks. |

*Common agent/DBA patterns: schema-first discovery, then build and explain read-only queries, then optionally export; writes behind an explicit write path or approval.*

---

### Milvus / vector tools

Operations commonly expected in vector-backed agents and RAG systems:

| Pattern | Description | Typical use cases |
|--------|-------------|-------------------|
| **Hybrid search** | Combine vector similarity with scalar filters (e.g. filter by `source`, `tenant_id`, `date`). Some setups add keyword/sparse + dense. | RAG with metadata filters, multi-tenant search. |
| **Get by IDs** | Retrieve entities by primary key or list of IDs (no vector search). | Fetch specific chunks or records after search. |
| **Upsert** | Insert or update by primary key (insert new, overwrite existing). | Incremental indexing, idempotent pipelines. |
| **Create collection from config** | Create a collection given schema (dimension, primary key, scalar fields) and optional index params. | Bootstrap, migrations, multi-environment. |
| **Collection stats / count** | Row count per collection, optionally with filter expression. | Monitoring, debugging, “how many chunks?” |
| **Health check** | Ping or simple operation to verify Milvus (and optionally collection) is reachable. | Startup, retries, capability checks. |

*RAG/chunking: often “chunk → embed → upsert with metadata”; query with hybrid search (vector + scalar filter). Multi-tenant: filter by `tenant_id` (or similar) in every search/query.*

---

### General (optional)

Cross-backend patterns often seen in agent tooling:

| Pattern | Description |
|--------|-------------|
| **Health / ping** | Per-backend or aggregated “is this backend up?” (e.g. Neo4j driver check, PostgreSQL `SELECT 1`, Milvus ping). |
| **get_capabilities / list_available_tools** | Return which tools (or which backends) are available in this environment, optionally with short descriptions. |
| **Rate limiting / safe wrappers** | Limit calls per minute or per session; wrap destructive operations behind confirmation or allowlists. |

---

*This document remains design/suggestion only; implementation lives in `mcp/tools` as needed.*

---

## Dify Yahoo tools compatibility

The following [Dify Yahoo tools](https://github.com/langgenius/dify-official-plugins/tree/main/tools/yahoo/tools) are integrated in `market_tool` and exposed as MCP tools:

| Dify tool | openFund equivalent | Mapping |
|-----------|----------------------|---------|
| **Ticker** (`ticker.py`: `Ticker(symbol).info`) | `get_ticker_info(symbol)` | Returns raw company/ticker info as JSON in `content`, routed via `MCP_MARKET_VENDOR` (yfinance → `.info`; alpha_vantage → OVERVIEW; finnhub → profile2). `get_fundamentals` remains the human-readable text path. |
| **News** (`news.py`: STORY-only list with title, content, url, provider, publishDate) | `get_news_dify(symbol, limit, start_date?, end_date?)` | Uses yfinance; filters `contentType == 'STORY'`; returns `{"news": [{title, content, url, provider, publishDate}, ...]}` in `content`. `get_news` / `_route_news` remain the existing text-format path. |
| **Analytics** (`analytics.py`: segment OHLCV, per-segment stats) | `get_stock_analytics(symbol, start_date, end_date)` | Uses `_route_stock_data` for OHLCV; parses to DataFrame; splits into up to 15 segments; returns `{"analytics": [{Start Date, End Date, Average/Min/Max for Close, Volume, Open, High, Low}, ...]}` in `content`. Finnhub 403 on candles returns the same clear message as `get_stock_data`. |
