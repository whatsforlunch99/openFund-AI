# Neo4j, PostgreSQL, and Milvus integration and data-model guidance

Data prep and backend integration plan. See [../docs/prd.md](prd.md), [../docs/backend.md](backend.md), [../docs/user-flow.md](user-flow.md).

---

## Project context (from /docs)

- **PRD:** Investment-research answers from natural-language queries; three user profiles (beginner, long_term, analyst); orchestrated research via specialists; safety and compliance ([prd.md](../docs/prd.md)).
- **Librarian** combines vector search (Milvus), knowledge graph (Neo4j), and SQL (PostgreSQL) via MCP; results feed the Analyst and Responder ([user-flow.md](../docs/user-flow.md), [backend.md](../docs/backend.md)).
- **Existing contracts:** mcp/tools/kg_tool.py (`query_graph`, `get_relations`), mcp/tools/sql_tool.py (`run_query`), mcp/tools/vector_tool.py (`search`, `index_documents`). When env is unset, mocks are returned; when set, they currently raise `NotImplementedError` ([progress.md](../docs/progress.md) future tracker).

---

## 1. What each store should store (data-model suggestions)

### Neo4j — Knowledge graph (fund/entity relationships)

**Role:** Answer "who is related to what" and "how funds connect" for the Librarian's `retrieve_knowledge_graph` / `get_relations` and for Cypher queries from the Planner.

**Suggested node labels and relations:**

| Node label | Purpose                                         |
| ---------- | ----------------------------------------------- |
| `Fund`     | Funds (id, name, isin, optional symbol)         |
| `Manager`  | Fund managers / management companies            |
| `Issuer`   | Issuing institution                             |
| `Sector`   | Sector / industry (e.g. Technology, Healthcare) |
| `Region`   | Geographic region                               |
| `Index`    | Benchmark index (e.g. S&P 500)                  |

| Relation type          | Meaning                                                                                      |
| ---------------------- | -------------------------------------------------------------------------------------------- |
| `MANAGED_BY`           | Fund → Manager                                                                               |
| `ISSUED_BY`            | Fund → Issuer                                                                                |
| `IN_SECTOR`            | Fund → Sector                                                                                |
| `IN_REGION`            | Fund → Region                                                                                |
| `TRACKS` / `BENCHMARK` | Fund → Index                                                                                 |
| `HOLDS`                | Fund → Asset (optional; can be simplified to "top holdings" as attributes or separate nodes) |

**Data to include:** Fund identifiers (id, name, ISIN), manager/issuer names, sector/region and benchmark for "fund X relationships", "who manages fund Y", "funds in same sector", and regulatory/issuer context. Populate from fund metadata (e.g. from market/fund data pipeline or CSV/API ingest).

**→ Source: you.** Graph structure is not provided by yf/AV; you build and ingest it yourself (see § 1.4).

**Tool alignment:** `get_relations(entity)` returns 1-hop (or configurable) relations for a given fund/manager/entity id. `query_graph(cypher, params)` runs arbitrary Cypher (e.g. "all funds in sector X", "funds managed by Y").

---

### PostgreSQL — Structured, queryable tabular data

**Role:** Answer precise filters and time-series/summary metrics the Librarian requests via `sql_tool.run_query` (e.g. "funds by AUM", "returns in a period", "fees").

**Suggested tables (minimal viable schema):**

| Table / concept      | Purpose                                                                                                             |
| -------------------- | ------------------------------------------------------------------------------------------------------------------- |
| `funds`              | id (PK), name, isin, symbol, inception_date, aum, fee_bps, currency, created_at, updated_at                         |
| `fund_returns`       | fund_id (FK), period_start, period_end, return_pct, source (e.g. "monthly") — supports "returns for fund X in 2023" |
| `holdings_snapshot`  | fund_id, as_of_date, holding_name, weight_pct (optional) — for "what does fund X hold"                              |
| `regulatory_filings` | fund_id, filing_type, filing_date, url or path (optional) — for "regulatory disclosures for fund X"                 |

**Data to include:** Fund metadata (name, ISIN, AUM, fees, inception), period returns (e.g. monthly/quarterly), optional holdings snapshots and filing references. Align with Analyst needs: Sharpe/max drawdown/Monte Carlo can be computed from returns; fees and AUM support "is fund X safe" / "costs" answers.

**Tool alignment:** `run_query(query, params)` executes parameterized SQL; return `{ "rows": [...], "schema": ["col1", "col2"], "params": {...} }`. Use `DATABASE_URL`; support at least psycopg2 (or SQLAlchemy) with parameterization to avoid SQL injection.

**→ Source: mix of yf/AV and you.** Returns and some metadata from yf/AV; ISIN, fees, filings you source yourself (see § 1.4).

---

### Milvus — Vector store (semantic search over text)

**Role:** Semantic search over fund-related text so the Librarian's `retrieve_documents` can find "fund X performance", "drawdown", "risk", etc., and combine with graph + SQL in `combine_results`.

**Suggested collection schema:**

- **Vector field:** One embedding field; dimension from config (`EMBEDDING_DIM`, default 384 per backend.md); model `sentence-transformers/all-MiniLM-L6-v2` or `EMBEDDING_MODEL`.
- **Scalar fields (metadata):** e.g. `fund_id` (string), `source` (e.g. "fact_sheet", "prospectus", "report"), `as_of_date` (string or timestamp), optional `language`. Filter in `vector_tool.search(query, top_k, filter)` by `fund_id` or `source` when provided.

**Documents to include:**

- Fund fact-sheet excerpts, prospectus snippets, annual/quarterly report summaries.
- Short "fund facts" or "situation" descriptions (can align with situation_memory-style content: "fund X in high-volatility period", "drawdown behavior").
- Optional: regulatory/sentiment snippets (e.g. from market_tool / Tavily) with a `source` tag.

**Data flow:** Ingest pipeline (or manual script) turns text into `{ "content": "text...", "fund_id": "X", "source": "fact_sheet", "as_of_date": "2024-01-15" }`; `index_documents(docs)` embeds `content`, upserts into Milvus with metadata; `search(query, top_k, filter)` embeds query, runs vector search, returns list of docs with scores and metadata.

**Tool alignment:** When `MILVUS_URI` (and preferably `MILVUS_COLLECTION`) are set, `search` uses an embedding model (lazy-loaded from `EMBEDDING_MODEL` / `EMBEDDING_DIM`), connects to Milvus, runs similarity search, returns list of dicts with content, score, id, fund_id, source, etc. When unset, keep current mock. `index_documents` implements embed + upsert; return `{ "indexed": n, "status": "ok" }` (or error).

**→ Source: you.** yf/AV do not provide document text; you supply and index all content yourself (see § 1.4).

---

## 1.4 Data source: yf/AV vs source yourself (highlight)

| Store          | Can query / derive from **yf and Alpha Vantage**                                                                                                                                                                      | You must **source yourself**                                                                                                                                                                                                                                       |
| -------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Neo4j**      | —                                                                                                                                                                                                                     | **All graph data.** yf/AV do not expose fund–manager–sector–region relations. Build nodes (Fund, Manager, Issuer, Sector, Region, Index) and relations (MANAGED_BY, IN_SECTOR, etc.) from fund databases, prospectuses, or internal CSV/API and ingest into Neo4j. |
| **PostgreSQL** | **Returns:** compute from yf/AV price history or time-series (e.g. market_tool.get_stock_data_yf / AV). **Some metadata:** name, sector/category for tickers from yf/AV (e.g. get_fundamentals_yf, company overview). | **funds:** ISIN, symbol↔fund mapping, inception_date, fee_bps, AUM (unless you have an API that provides them). **holdings_snapshot**, **regulatory_filings:** from fund providers or manual/crawled data.                                                         |
| **Milvus**     | —                                                                                                                                                                                                                     | **All document text.** yf/AV give structured market data, not prose. You supply fact sheets, prospectus excerpts, report summaries, situation descriptions; then run `index_documents` (or an ingest pipeline) to embed and store in Milvus.                       |

---

## 2. Implementation plan (integration steps)

### 2.1 Dependencies and config

- Add optional dependencies: `neo4j`, `psycopg2-binary` (or `sqlalchemy`), `pymilvus`, `sentence-transformers`. Document in pyproject.toml under optional extra, e.g. `[project.optional-dependencies] backends = ["neo4j", "psycopg2-binary", "pymilvus", "sentence-transformers"]`.
- Config already has NEO4J_URI/USER/PASSWORD, DATABASE_URL, MILVUS_URI, MILVUS_COLLECTION, EMBEDDING_MODEL, EMBEDDING_DIM. Ensure defaults for embedding (e.g. all-MiniLM-L6-v2, 384) when env is set for Milvus.

### 2.2 Neo4j (kg_tool)

- In mcp/tools/kg_tool.py: if NEO4J_URI is set, create a Neo4j driver. `query_graph(cypher, params)`: run the Cypher query with params, map result to a dict with nodes, edges, and/or rows. `get_relations(entity)`: run a fixed Cypher pattern, normalize to `{ "nodes": [...], "edges": [...], "entity": entity }`. On failure, return `{"error": "..."}` and log. Keep mock when NEO4J_URI is unset.

### 2.3 PostgreSQL (sql_tool)

- In mcp/tools/sql_tool.py: if DATABASE_URL is set, create a connection with parameterization. `run_query(query, params)`: execute with params, return `{ "rows": rows, "schema": schema, "params": params or {} }`. On error, return `{"error": "..."}` and log. Keep mock when DATABASE_URL is unset.

### 2.4 Milvus (vector_tool)

- In mcp/tools/vector_tool.py: if MILVUS_URI is set, connect to Milvus and get or create collection. Lazy-load embedding model. `search`: embed query, run collection.search, return list of dicts. `index_documents`: embed each doc content, upsert; return `{ "indexed": n, "status": "ok" }`. Keep mock when MILVUS_URI is unset.

### 2.5 Documentation and progress

- Add a "Data stores" subsection under docs/backend.md (or docs/data-stores.md) and update docs/progress.md "Future implementation tracker" with a pointer to this data_prep doc.

### 2.6 Tests

- When env vars are set, call the real tools and assert response shape. When unset, existing mock behavior and E2E unchanged.

---

## 3. Suggested order of work

1. **PostgreSQL (sql_tool)** — Single connection, parameterized query, simple return shape; no embedding.
2. **Neo4j (kg_tool)** — Driver + query_graph + get_relations; normalize to existing nodes/edges/entity contract.
3. **Milvus (vector_tool)** — Embedding model + collection schema + search then index_documents; wire filter in MCP payload.
4. **Docs** — Data-model subsection and progress update.
5. **Optional** — Seed scripts or ingest docs for Neo4j, PostgreSQL, Milvus.

---

## 4. Summary

- **Milvus:** Unstructured/semi-structured text (fund facts, reports); semantic search by user query. **Source: you.**
- **Neo4j:** Entities and relations (fund, manager, sector, region, benchmark); "who/what is related". **Source: you.**
- **PostgreSQL:** Tabular fund metadata, returns, fees, optional holdings/filings; precise filters and time-series. **Source: mix of yf/AV (returns, some metadata) and you (ISIN, fees, filings).**
