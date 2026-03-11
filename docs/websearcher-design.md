# WebSearcher Agent Design

Design for the WebSearcher specialist agent: parallel multi-source query, normalized output schema, and integration with the Planner and MCP tool layer. Implementation lives in `agents/websearch_agent.py` and MCP tools; see [backend.md](backend.md) for orchestration and [agent-tools-reference.md](agent-tools-reference.md) for tool contracts.

---

## Overview

### Role in the pipeline

- **Planner** sends a **REQUEST** to WebSearcher with a **decomposed sub-query** (and optional `fund` / `symbol`) in the message content.
- **WebSearcher** resolves symbols, **queries all data sources in parallel** (FinanceDatabase, Stooq, Yahoo, ETFdb, market_tool, and optionally LLM when configured), normalizes to a standard schema, **merges all returned data**, and sends a single **INFORM** back to the Planner.
- All external data access is **only via MCP tools**; no direct HTTP or DB access from the agent.

### Design goals

1. **Query all sources in parallel** — No priority order; FinanceDatabase (FinDB), Stooq, Yahoo, ETFdb, market_tool (Alpha Vantage / Finnhub), and LLM API (when available) are called concurrently.
2. **Merge and return all results** — Every source that returns usable data is included in the reply; no source is discarded based on priority.
3. **Output structured, traceable data** for the Decision path: every payload has a **source** map and **timestamp**.

---

## Integration with Planner

### Request (Planner → WebSearcher)

- **Performative:** `REQUEST`
- **Content:** At least one of:
  - `query` (string) — decomposed sub-query for this agent (e.g. “current price and expense ratio for ”).
  - `fund` or `symbol` (string) — explicit identifier when the Planner has already resolved it.
- **Other:** `conversation_id`, `reply_to` (Planner), `sender` (e.g. `"planner"`).

The agent may derive a **symbol** from `query` via heuristics or by calling a search/catalog tool (e.g. FinanceDatabase-backed MCP tool) when `fund`/`symbol` is not provided.

### Response (WebSearcher → Planner)

- **Performative:** `INFORM`
- **Receiver:** `reply_to` from the REQUEST (typically Planner).
- **Content:** A structured payload that the Planner can merge with Librarian and Analyst results and pass to the Responder. Required shape:
  - **Timestamp:** All returned data must include a `timestamp` (e.g. ISO 8601). Existing behaviour uses `market_data`, `sentiment`, and `regulatory` each with their own `timestamp`; a future unified shape can use a single top-level `timestamp` and a `source` map (see below).
  - **Source attribution:** Either per-field (e.g. `source.static`, `source.price`, `source.fundamentals`) or per-section so that the Decision path can trace provenance.

This contract aligns with [backend.md](backend.md) (TaskStep with `agent: "websearcher"`, params with decomposed query; Planner aggregates INFORMs and runs the planner sufficiency check before sending consolidated data to the Responder).

---

## Data sources (parallel query)

All sources are queried **in parallel**; there is no priority order. Each source that returns usable data is merged into the output.

| Data source        | MCP tool                     | Typical data                          |
|--------------------|------------------------------|----------------------------------------|
| FinanceDatabase    | `fund_catalog_tool.search`   | ETF/Fund list, symbol resolution, static metadata |
| stooq              | `stooq_tool.get_price`       | Latest price                           |
| Yahoo Finance      | `yahoo_finance_tool.get_fundamental` / `get_price` | Price, fundamentals, holdings, sector |
| ETFdb              | `etfdb_tool.get_fund_data`   | Expense ratio, AUM, holdings, sector breakdown |
| market_tool        | `get_fundamentals`, `get_news`, `get_global_news` | Fundamentals, news (Alpha Vantage / Finnhub) |
| LLM API            | (optional)                   | Data search; all-tools-fail and news fallback |
| **News**           | `news_tool.search_rss`, `search_yahoo_rss`, `search_gdelt` | See [news-searcher-design.md](news-searcher-design.md). |

- **Symbol resolution:** If `fund`/`symbol` is not provided, symbol(s) are derived from the query via FinanceDatabase search or heuristics.
- **Parallel invocation:** For each resolved symbol, all applicable tools are called concurrently.
- **Merge:** All non-error responses are merged into the normalised schema; the `source` map records which backend supplied which field.

---

## Standard output schema

A single fund/ETF result should be normalised to a common shape so the Planner and Analyst can consume it regardless of the underlying source. All returned data must include a **timestamp** and **source** attribution.

**Example normalised payload (per symbol):**

```json
{
  "symbol": "VTI",
  "name": "Vanguard Total Stock Market ETF",
  "asset_class": "Equity",
  "expense_ratio": 0.03,
  "aum": 350000000000,
  "price": 245.31,
  "sector_exposure": {},
  "holdings_top10": [],
  "source": {
    "static": "FinanceDatabase",
    "price": "stooq",
    "price_yahoo": "yahoo",
    "fundamentals": "ETFdb",
    "fundamentals_yahoo": "yahoo"
  },
  "timestamp": "2026-03-04T12:00:00Z"
}
```

- **source** documents which backend supplied which part of the data; multiple sources can contribute (e.g. both stooq and Yahoo for price).

Current implementation returns `market_data`, `sentiment`, and `regulatory` with per-section timestamps; evolving toward this schema should preserve backward compatibility with existing Planner aggregation (e.g. by adding a `normalized_fund` key or by gradually replacing the inner shape).

---

## Functional flow (high level)

1. **Parse request** — Read `query`, `fund`, or `symbol` from REQUEST content; set `conversation_id` for logging and flow.
2. **Resolve symbol(s)** — If no symbol: call FinanceDatabase (or heuristics) to derive symbol(s). If symbol given, use it directly.
3. **Fetch from all sources in parallel** — For each symbol, invoke **all** applicable tools concurrently: fund_catalog, stooq, Yahoo Finance, ETFdb, market_tool; optionally LLM API when configured. No priority; all are called at once (e.g. `ThreadPoolExecutor` or `asyncio.gather`).
4. **Merge and normalise** — Combine all non-error responses into the standard output schema; fill `source` for each field; set `timestamp`.
5. **Return** — Send one INFORM to Planner with the merged payload (and optional LLM summary when `llm_client` is set).

---

## FinanceDatabase integration

- **Reference:** [FinanceDatabase](https://github.com/JerBouma/FinanceDatabase) (ETF/Mutual Fund catalog).
- **Integration:** Via an MCP tool (e.g. `fund_catalog_tool.search` or similar) that wraps the library so the agent never imports it directly in the research path. Example tool contract:
  - **Input:** `query` (string) or `name` (string) for search.
  - **Output:** List of matches with at least `symbol`, `name`, and optional classification (sector/country/exchange).
- **Usage:** WebSearcher calls this tool when the REQUEST contains a textual query and no `symbol`; results drive symbol resolution and optional static metadata for the normalised schema.

---

## Data source tools (all invoked in parallel)

### stooq

- **Purpose:** Latest and historical price.
- **Exposure:** As an MCP tool (e.g. `market_tool.get_stooq_price` or a dedicated `stooq_tool`) with payload `symbol` (and optional date range). Response must include `timestamp`.
- **Implementation detail:** Use a stable URL pattern (e.g. `https://stooq.com/q/l/?s={symbol}.us&i=d`) and parse CSV/text; handle errors and return `{"error": "..."}` so the agent can fall back to cache or other sources.

### Yahoo Finance

- **Purpose:** Price, fundamentals (expense ratio, AUM, holdings, sector) via quoteSummary or chart API fallback.
- **Exposure:** `yahoo_finance_tool.get_fundamental` (preferred) or `get_price`; payload `symbol`. Response includes `timestamp` and normalised fields.
- **Implementation detail:** `query1.finance.yahoo.com` quoteSummary (with 401 fallback to chart); User-Agent, crumb session; host fallback (query1→query2).

### ETFdb

- **Purpose:** Expense ratio, AUM, holdings, sector breakdown.
- **Exposure:** `etfdb_tool.get_fund_data` with payload `symbol`. Response includes `timestamp` and normalised fields (`expense_ratio`, `aum`, etc.).
- **Implementation detail:** HTTP request with browser-like headers; parse HTML; may return 403 in some regions.

---

## Data normalisation

- Different sources use different field names and units. A **normaliser** (inside the agent or inside a dedicated MCP tool) should:
  - Map all identifiers to a single **symbol** (and optional **name**).
  - Express **expense_ratio** as a decimal (e.g. 0.03 for 3 bp).
  - Express **aum** in a consistent unit (e.g. dollars).
  - Express **price** as a number with consistent currency.
  - Populate **source** for each logical field (static, price, fundamentals).
- The agent (or tool) must set **timestamp** on every returned structure.

---

## Caching

- **Rationale:** Reduce load on external sites, avoid rate limits, and improve latency.
- **Placement:** Cache can live inside MCP tools (e.g. Redis or local SQLite) or in a small cache layer used by the agent; all access remains behind the MCP boundary.
- **Suggested TTLs:**

| Data type     | Suggested TTL |
|---------------|---------------|
| Real-time price | 5 min       |
| AUM           | 24 h          |
| Expense ratio | 7 d           |
| Holdings      | 24 h          |

- On cache hit, the tool returns cached data with a **timestamp** indicating when it was fetched; the normaliser and agent behaviour stay unchanged.

---

## Fact conflict resolution

When different data sources return **conflicting factual data** (e.g. stooq and Yahoo report different prices for the same symbol, or ETFdb AUM disagrees with another source):

1. WebSearcher does **not** arbitrarily discard or prefer one source.
2. WebSearcher passes **all conflicting data** to the LLM (when `llm_client` is set).
3. The LLM decides which source is **more credible** and returns both the chosen value and the **reasoning** (e.g. recency, source reputation, data freshness).
4. The reply to the Planner includes the LLM’s chosen value, the `source` attribution (e.g. `source.price = "stooq"` or `"yahoo"`), and an optional `conflict_resolution` field with the reasoning.

This keeps traceability and allows the Planner and Responder to surface the choice and rationale when relevant.

---

## All-tools-fail fallback

When **all** WebSearcher tools fail to return usable data (e.g. stooq, Yahoo, ETFdb, market_tool all error or return empty):

1. WebSearcher does **not** return an empty or error-only payload.
2. WebSearcher directly calls the **LLM** to perform a **data search** (e.g. “find the current price of SPY”).
3. The LLM’s response (facts, numbers, or structured text it infers from its knowledge) is returned to the Planner.
4. The reply is **explicitly annotated** that the data comes from the LLM, e.g. `source.price = "llm"` or a top-level `source: {"primary": "llm"}` and optional `llm_fallback: true`.
5. The Planner can treat this as lower-confidence data and, if desired, surface a disclaimer in the final answer.

This ensures a best-effort answer even when external APIs and tools are unavailable, while preserving provenance and allowing downstream logic to adjust presentation.

---

## Error handling

| Situation              | Behaviour |
|------------------------|-----------|
| Individual source fails | Omit that source’s fields; keep data from other sources. No fallback chain; all sources are queried in parallel. |
| FinanceDatabase no hit | Use heuristics or other sources for symbol; return whatever data other sources provide. |
| **All tools fail**     | See [All-tools-fail fallback](#all-tools-fail-fallback): call LLM for data search and return with `source: "llm"` annotation. |
| **Conflicting facts**  | See [Fact conflict resolution](#fact-conflict-resolution): pass all data to LLM for credibility decision and reasoning. |

All MCP tools should return a dict with either a normal payload (including `timestamp`) or `{"error": "..."}` so the agent can detect failure and apply fallbacks without raising.

---

## Concurrency and performance

- **Parallel fetches:** All data sources (FinanceDatabase, stooq, Yahoo, ETFdb, market_tool, optionally LLM) are invoked **in parallel** for each symbol. No sequential priority; total latency is dominated by the slowest source (e.g. 0.5–2 s).
- **Batching:** If the Planner sends multiple symbols in one REQUEST, the agent may batch or parallelise per-symbol fetches within timeout and rate-limit constraints.

---

## Extensibility

Future sources (Yahoo Finance, Alpha Vantage, SEC, Morningstar) should be:

- Wrapped as **MCP tools** with a clear payload and response contract.
- Documented in [agent-tools-reference.md](agent-tools-reference.md).
- Wired into WebSearcher’s allowed tool list in `llm/tool_descriptions.py` so that LLM-based tool selection can use them when appropriate.

The existing **market_tool** (Alpha Vantage / Finnhub) already provides fundamentals, news, and global news; the WebSearcher continues to use it. New tools (FinanceDatabase, stooq, ETFdb) extend the data surface without changing the Planner–WebSearcher REQUEST/INFORM contract.

---

## File and module layout

- **Agent:** `agents/websearch_agent.py` — handles REQUEST, symbol resolution, tool calls, normalisation, INFORM. See [file-structure.md](file-structure.md).
- **MCP tools:** Existing: `mcp/tools/market_tool.py`. New or extended tools (e.g. FinanceDatabase wrapper, stooq, ETFdb) live under `mcp/tools/` and are registered in `MCPServer.register_default_tools()`.
- **Prompts / tool list:** `llm/prompts.py` (e.g. `WEBSEARCHER_SYSTEM`, `WEBSEARCHER_TOOL_SELECTION`), `llm/tool_descriptions.py` (`WEBSEARCHER_ALLOWED_TOOL_NAMES`, tool descriptions). Keep [agent-tools-reference.md](agent-tools-reference.md) in sync when adding tools.

Optional internal structure for a richer WebSearcher stack (e.g. parsers, normaliser, cache) can live under `agents/` or a dedicated package; the external boundary remains REQUEST/INFORM and MCP only.

---

## Summary

- WebSearcher receives a **decomposed query** (and optional symbol) from the **Planner** via REQUEST and returns a single INFORM with **structured, timestamped, source-attributed** data.
- Data is sourced by **parallel query** of all APIs: FinanceDatabase, Stooq, Yahoo, ETFdb, market_tool, and optionally LLM API. No priority order; all sources are invoked concurrently; all returned data is merged and passed to the Planner.
- **Fact conflict:** When sources disagree, all conflicting data is sent to the LLM; the LLM picks the more credible value and returns reasoning.
- **All tools fail:** When no tool returns data, WebSearcher calls the LLM for a data search and returns the result with `source: "llm"` annotation.
- Output is **normalised** to a common schema and can be **cached** with configurable TTLs; **errors** from individual sources are omitted while keeping data from others.
- This design aligns with [backend.md](backend.md), [prd.md](prd.md), and [file-structure.md](file-structure.md) and allows the Planner to aggregate WebSearcher results with Librarian and Analyst before passing consolidated data to the Responder.

---

## Related design

- [news-searcher-design.md](news-searcher-design.md) — News Search subsystem: parallel aggregation, structured output, citation system.

---

## Future work

- **Permission tags:** Inject `access_control` block (e.g. classification, roles_allowed) into INFORM content before returning to Planner; allow downstream components (Responder, compliance) to enforce access rules.
- **Security and robustness:** Rate limiting in MCP tools (stooq, ETFdb) to avoid bans; enforce secrets via env/config only; sanitise user input in tool payloads; respect robots.txt and terms of use for scraped sites.
