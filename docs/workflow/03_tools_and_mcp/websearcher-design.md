# WebSearcher Agent Design

Design for the WebSearcher specialist agent: parallel multi-source query, normalized output schema, and integration with the Planner and MCP tool layer. **Implementation:** `agents/websearch_agent.py` and MCP tools under `mcp/tools/` loaded by path in `openfund_mcp/fastmcp_server.py`. See [backend.md](../02_planning/backend.md) for orchestration and [agent-tools-reference.md](agent-tools-reference.md) for tool contracts.

---

## Overview

### Role in the pipeline

- **Planner** sends a **REQUEST** to WebSearcher with a **decomposed sub-query** (and optional `fund` / `symbol`) in the message content.
- **WebSearcher** resolves symbols, runs **Financial Data Search** and **News Search** in parallel (two top-level threads), merges into `normalized_fund` plus backward-compat `market_data` / `sentiment` / `regulatory`, and sends a single **INFORM** back to the Planner.
- All external data access is **only via MCP tools**; no direct HTTP or DB access from the agent.

### Design goals

1. **Query applicable sources in parallel** — Per symbol, stooq, Yahoo, ETFdb, and market_tool are invoked concurrently via `ThreadPoolExecutor`. News RSS/GDELT and market news run in parallel with the financial bundle.
2. **Merge and return all usable results** — Non-error fields are merged into one normalised record per symbol; `source` records provenance per field.
3. **Structured, traceable data** — Every payload includes **timestamp** and **source**; optional `conflict_resolution` when stooq vs Yahoo price differs.

---

## Integration with Planner

### Request (Planner → WebSearcher)

- **Performative:** `REQUEST`
- **Content:** At least one of:
  - `query` (string) — decomposed sub-query.
  - `fund` or `symbol` (string) — explicit identifier when the Planner has already resolved it.
- **Optional:** `days` / `look_back_days` (int, clamped 1–30) for news lookback.
- **Other:** `conversation_id`, `reply_to`, `sender`.

### Response (WebSearcher → Planner)

- **Performative:** `INFORM`
- **Content (current implementation):**

| Key | Purpose |
|-----|--------|
| `normalized_fund` | **Primary.** List of per-symbol records (see schema below). Planner and `_format_final` use this for price lines when `market_data`/`sentiment` are error-only. |
| `market_data` | Backward compat; first symbol’s `market_tool.get_fundamentals` result or `{timestamp}` placeholder. |
| `sentiment` | Backward compat; from `market_tool.get_news` when configured, else `{error}` or `{timestamp}`. |
| `regulatory` | Backward compat; from `market_tool.get_global_news` with **required** `as_of_date` / `look_back_days` (empty payload caused parse errors before fix). |
| `news` | Normalised list `{title, source, date, url, summary, id?}` with citation ids `NEWS1`… |
| `citations` | Map `NEWSn` → URL. |
| `news_timestamp` | ISO time of news aggregation. |
| `summary` | Optional LLM narrative; if LLM fails, replaced by `_fallback_summary_from_normalized(normalized_fund)`. |
| `llm_fallback` | True when all-tools-fail path used LLM for data. |

**Planner aggregation:** `agents/planner_agent.py` `_format_final` prepends a **`price: SYMBOL $x.xx (source)`** line from `normalized_fund` when present so the Responder always receives numeric price even when `summary` is long or `market_data` only contains errors.

---

## Symbol resolution (implementation detail)

- **`_resolve_symbols(content)`** — If `fund`/`symbol` is a 1–5 letter ticker **and not blocklisted**, use it. Otherwise calls `fund_catalog_tool.search(query)` when registered; else `_normalize_symbol(query|fund)`.
- **Blocklist** (`_TICKER_BLOCKLIST`): English words that look like tickers (e.g. `WHAT`, `IS`, `PRICE`) so Planner passing `fund="WHAT"` from “What is the price of SPY?” does not query `WHAT.US`. Known tickers **SPY**, **QQQ**, etc. are detected in free text via regex before blocklist tokens.
- **Default symbol** when nothing matches: `AAPL` (legacy behaviour).

---

## Data sources (parallel query)

### Financial bundle (per symbol, `_fetch_all_sources_for_symbol`)

| Source | MCP tool | Notes |
|--------|----------|--------|
| Stooq | `stooq_tool.get_price` | Latest price/close; primary price source when OK. |
| Yahoo | `yahoo_finance_tool.get_fundamental` (or `get_price`) | Price, AUM, holdings, sector_exposure; `price_yahoo` stored when both stooq and Yahoo OK. |
| ETFdb | `etfdb_tool.get_fund_data` | Often 403; omitted from merge if error. |
| market_tool | `get_fundamentals`, `get_news`, `get_global_news` | Requires API keys/vendor; **get_news** must include `start_date`/`end_date` for Alpha Vantage; **get_global_news** must include `as_of_date` and `look_back_days` (never call with `{}`). |

### News bundle (`_fetch_news_sources`, parallel with financial)

| Source | MCP tool |
|--------|----------|
| RSS | `news_tool.search_rss` |
| Yahoo RSS | `news_tool.search_yahoo_rss` |
| GDELT | `news_tool.search_gdelt` |
| market_tool | `get_news` / `get_global_news` with dates as above |

See [news-searcher-design.md](news-searcher-design.md) for citation schema.

---

## Standard output schema (`normalized_fund` entry)

Single fund/ETF record shape produced by `_normalise_to_schema`:

```json
{
  "symbol": "SPY",
  "name": "State Street SPDR S&P 500 ETF Trust",
  "asset_class": "Equity",
  "expense_ratio": null,
  "aum": 698270220288.0,
  "price": 677.18,
  "price_yahoo": 678.27,
  "sector_exposure": {},
  "holdings_top10": [],
  "source": {
    "price": "stooq",
    "price_yahoo": "yahoo",
    "fundamentals_yahoo": "yahoo"
  },
  "timestamp": "2026-03-11T08:50:08Z",
  "yahoo_fundamentals_raw": {}
}
```

- **`price`** — After conflict resolution, may be chosen from stooq or Yahoo; `source.price` updated accordingly.
- **`conflict_resolution`** — Optional `{chosen_source, chosen_value, reason}` when LLM resolves stooq vs Yahoo discrepancy (>1% relative).

---

## Functional flow (code-aligned)

1. **handle_message** — Trace + flow UI; `_run_parallel_flow(content)`.
2. **_run_parallel_flow** — `_resolve_symbols` → **parallel** `do_financial` (per-symbol `_fetch_all_sources_for_symbol` + `_merge_financial_results`) and `do_news` (`_fetch_news_sources`) → merge news → optional `_llm_news_fallback`.
3. **All-tools-fail** — If `_all_tools_failed(reply_content)` and `llm_client` set, replace with `_llm_data_search_fallback` (`llm_fallback` on record).
4. **Conflict resolution** — For each `normalized_fund` record with `_has_price_conflict`, `_resolve_conflict_with_llm` updates `price` and `source.price`.
5. **Summary** — `WEBSEARCHER_SYSTEM` + `get_websearcher_user_content`; on failure or empty, `_fallback_summary_from_normalized`.
6. **INFORM** — `reply_content` sent to Planner; status `limited_data` if any of market_data/sentiment/regulatory has `error`.

---

## FinanceDatabase integration

- **Tool:** `fund_catalog_tool.search` — query/name + limit; returns `matches` with `symbol`, `name`, etc.
- **Registration:** Loaded by **file path** in `fastmcp_server` / `mcp_server` because PyPI package `mcp` shadows the local `mcp/` package.

---

## Fact conflict resolution

- When stooq and Yahoo prices differ by **>1%**, `_resolve_conflict_with_llm` uses `WEBSEARCHER_CONFLICT_RESOLUTION_SYSTEM`; parser expects lines `CHOSEN:`, `VALUE:`, `REASON:`.
- On parse failure defaults to **stooq**.

---

## All-tools-fail fallback

- `_all_tools_failed` — No price in `normalized_fund` and no usable content in market_data/sentiment/regulatory.
- `_llm_data_search_fallback` — `WEBSEARCHER_LLM_FALLBACK_SYSTEM`; record gets `llm_fallback`, `llm_fallback_content`, `source.primary` / `source.price` = `llm`.

---

## Error handling

| Situation | Behaviour |
|-----------|------------|
| Single source fails | Field omitted or filled from another source; `error` dict only for that tool’s slot in parallel fetch. |
| ETFdb 403 | etfdb omitted; Yahoo/stooq still populate. |
| market_tool without API key | `market_data`/`sentiment`/`regulatory` carry `error`; **normalized_fund** still has price from stooq/Yahoo. |
| LLM unavailable | Summary falls back to `_fallback_summary_from_normalized`; conflict resolution skipped. |

---

## Stdio server and tool registration

- **Path load:** `openfund_mcp/fastmcp_server.py` uses `importlib.util.spec_from_file_location` for `mcp/tools/fund_catalog_tool.py`, `yahoo_finance_tool.py`, `stooq_tool.py`, `etfdb_tool.py`.
- **Critical:** Do **not** bind stooq module as `st` after `sql_tool` is imported as `st` — use `stooq_mod` so `sql_tool.run_query` closures stay correct.
- **Capabilities:** `_websearcher_tool_names` appended to `get_capabilities` only for tools actually registered.

---

## File and module layout

| Piece | Location |
|-------|----------|
| Agent | `agents/websearch_agent.py` |
| Parallel financial fetch | `_fetch_all_sources_for_symbol`, `_merge_financial_results`, `_normalise_to_schema` |
| News | `_fetch_news_sources`, `_normalize_and_merge_news`, `_build_news_with_citations` |
| Planner price line | `agents/planner_agent.py` — `_websearcher_price_line`, `_format_final` |
| Prompts | `llm/prompts.py` — `WEBSEARCHER_SYSTEM`, `WEBSEARCHER_NEWS_FALLBACK_SYSTEM`, `WEBSEARCHER_LLM_FALLBACK_SYSTEM`, `WEBSEARCHER_CONFLICT_RESOLUTION_SYSTEM` |
| Tool allowlist | `llm/tool_descriptions.py` — `WEBSEARCHER_ALLOWED_TOOL_NAMES` |

---

## Caching

- Not implemented in-agent; design intent remains: cache inside MCP tools with TTLs as in previous revision if added later.

---

## Related design

- [news-searcher-design.md](news-searcher-design.md) — News aggregation and citations.

---

## Future work

- Permission tags / access_control on INFORM.
- Rate limiting in stooq/ETFdb tools; robots/terms compliance.
