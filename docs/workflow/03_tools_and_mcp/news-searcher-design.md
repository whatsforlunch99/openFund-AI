# News Searcher Design

Design for the News Search subsystem within WebSearcher: parallel multi-source news aggregation, structured output with citations, and integration with the Planner. News Search runs alongside Financial Data Search in the WebSearcher agent. All external news access is **only via MCP tools**; see [websearcher-design.md](websearcher-design.md) for overall WebSearcher behaviour and [agent-tools-reference.md](agent-tools-reference.md) for tool contracts.

---

## Overview

### Role in the pipeline

- **Planner** sends a **REQUEST** to WebSearcher with a decomposed sub-query that may include news intent (e.g. “recent news about NVDA ETF exposure”, “latest AI semiconductor news”).
- **WebSearcher** invokes **Financial Data Search** and **News Search** in parallel. News Search queries all news sources concurrently, merges results, assigns citation IDs, and includes them in the INFORM.
- All external news access is **only via MCP tools**; no direct HTTP or scraping from the agent.

### Design goals

1. **Parallel news aggregation** — All news sources (Google News RSS, market_tool news, and any future news tools) are called concurrently. No priority order; every source that returns usable data is merged into the output.
2. **Structured, traceable news** — Each news item has `id`, `title`, `source`, `date`, `url`, and `summary` so the Decision path can attribute provenance.
3. **Citation system** — News items are assigned stable citation IDs (e.g. [NEWS1], [NEWS2]) so Planner and Responder can reference sources in the final answer.

---

## Integration with WebSearcher and Planner

### Request (Planner → WebSearcher)

Same as [websearcher-design.md](websearcher-design.md): REQUEST content includes `query` and optionally `fund` or `symbol`. WebSearcher infers whether news is needed from the query (or always includes news when relevant tools exist) and runs News Search in parallel with Financial Data Search.

### Response (WebSearcher → Planner)

The INFORM content is extended with:

- **`news`** (array): List of structured news items with citation IDs.
- **`citations`** (object): Mapping from citation ID to URL for downstream use.

Existing keys (`normalized_fund`, `market_data`, `sentiment`, `regulatory`) remain for backward compatibility. `news` and `citations` augment rather than replace them; `sentiment` and `regulatory` may continue to hold market_tool output when that tool is used, while `news` holds the unified, citation-enabled list.

---

## News data sources (parallel query)

All news sources are queried **in parallel**; there is no priority or fallback chain. Each source that returns usable data is merged into the output.

| Data source        | MCP tool                         | Typical data                     |
|--------------------|----------------------------------|----------------------------------|
| Google News RSS    | `news_tool.search_rss`           | Headlines, links, dates, sources |
| Yahoo Finance RSS  | `news_tool.search_yahoo_rss`     | General finance news (fixed feed)|
| GDELT API          | `news_tool.search_gdelt`         | Query-based news (may 429)       |
| market_tool        | `market_tool.get_news`, `get_global_news` | Ticker and macro news (Alpha Vantage / Finnhub) |

- **news_tool.search_rss** — Google News RSS. Input: `query` (string), `days` (int, default 7). Output: items with `title`, `link`, `published`, `source`.
- **news_tool.search_yahoo_rss** — Yahoo Finance fixed feed. Input: `limit` (optional int, default 20). No query param.
- **news_tool.search_gdelt** — GDELT API (free, no key). Input: `query` (string), `limit` (optional, default 10). Retries once on 429.
- **market_tool** — Existing tools; WebSearcher calls `get_news` (ticker) and `get_global_news` (macro). Their output is normalised into the same schema as RSS-derived items.

Future sources should be added as MCP tools and invoked in parallel. See [News source verification](#news-source-verification) for verified availability.

---

## News source verification

Verified 2026-03 via `scripts/verify_news_sources.py`. Run `python scripts/verify_news_sources.py` to re-check.

| Source              | Status      | Notes |
|---------------------|-------------|-------|
| **Google News RSS** | ✅ OK       | Implemented in `news_tool.search_rss`. Free, query-based. May require proxy in some regions. |
| **Yahoo Finance RSS** | ✅ OK     | Fixed feed `https://finance.yahoo.com/news/rssindex` (~42 items). No query param; use as general finance supplement. |
| **GDELT API**       | ✅ OK       | `https://api.gdeltproject.org/api/v2/doc/doc`. Free, no key. May return 429 under load; tool retries once. |
| **market_tool**     | Config      | Alpha Vantage NEWS_SENTIMENT (needs `ALPHA_VANTAGE_API_KEY`). Finnhub when `MCP_MARKET_VENDOR=finnhub`. |

---

## Standard news output schema

Each news item is normalised to a common shape:

```json
{
  "id": "NEWS1",
  "title": "Nvidia rally lifts semiconductor ETFs",
  "source": "Yahoo Finance",
  "date": "2026-03-05",
  "url": "https://finance.yahoo.com/news/...",
  "summary": "Semiconductor ETFs surged following Nvidia earnings..."
}
```

- **id** — Stable citation ID (e.g. NEWS1, NEWS2) assigned by the agent. Used by Planner/Responder as [NEWS1] in text.
- **title** — Headline.
- **source** — Publication or feed name (e.g. Yahoo Finance, Google News, GDELT).
- **date** — Publication date (ISO 8601 date or datetime; normalised to `yyyy-mm-dd` for consistency).
- **url** — Canonical article URL.
- **summary** — Short excerpt or description. May be empty if not available; RSS typically provides title only.

All news returned must include a **timestamp** (when the agent fetched/merged) for traceability; the payload may carry a top-level `news_timestamp` or each item may include `fetched_at` if needed.

---

## Citation system

### Citation ID format

- IDs are assigned sequentially: `NEWS1`, `NEWS2`, … `NEWSn`.
- Assignment happens after merge, in presentation order (e.g. by date descending, then by source).

### Citations map

```json
{
  "citations": {
    "NEWS1": "https://finance.yahoo.com/news/...",
    "NEWS2": "https://news.google.com/..."
  }
}
```

Planner and Responder use this map to resolve [NEWS1] to the URL when rendering or when the user requests sources.

### Usage by Planner / Responder

When generating the answer, the Planner or Responder can reference:

> According to recent news [NEWS1], semiconductor ETFs surged after Nvidia earnings. [NEWS2] reports strong inflows into AI-focused funds.

---

## Time range configuration

News search accepts a configurable look-back window:

| Parameter | Description        | Default |
|-----------|--------------------|---------|
| `days`    | Look-back in days  | 7       |

Supported values: `1`, `7`, `30` (or as implemented). The agent passes `days` to news tools; RSS and market_tool each apply it according to their own semantics (e.g. RSS uses query params; market_tool uses `start_date`/`end_date` or `look_back_days`).

---

## Functional flow (high level)

1. **Parse request** — WebSearcher reads `query`, `fund`, `symbol` from REQUEST content.
2. **Invoke Financial Data Search and News Search in parallel** — Both run concurrently. News Search calls all news tools (`search_rss`, `search_yahoo_rss`, `search_gdelt`, `market_tool.get_news`, `get_global_news`) in parallel.
3. **Normalise and merge** — Convert items to the standard schema; deduplicate by URL; sort by date descending.
4. **Build citations** — Assign `NEWS1`, `NEWS2`, … and populate the `citations` map.
5. **Return** — Include `news` and `citations` in the INFORM alongside `normalized_fund`, `market_data`, etc.

---

## MCP tools for News Search

Implemented in `openfund_mcp/tools/news_tool.py` and documented in [agent-tools-reference.md](agent-tools-reference.md):

- **news_tool.search_rss** — Google News RSS; payload: `query`, `days`.
- **news_tool.search_yahoo_rss** — Yahoo Finance fixed feed; payload: `limit`.
- **news_tool.search_gdelt** — GDELT API; payload: `query`, `limit`.

### market_tool.get_news / get_global_news

- **Purpose:** Ticker-specific and macro news (Alpha Vantage / Finnhub).
- **Payload:** Per [agent-tools-reference.md](agent-tools-reference.md).
- **Returns:** `{"content": str, "timestamp": str}` or `{"error": str}`. Content is typically unstructured text; the agent or a normaliser should parse and map to the standard news item schema where possible (e.g. extract title/source/url if present).

---

## Article parser (optional)

When the Planner or a downstream step needs **full article body** (e.g. for deeper analysis):

- Expose an MCP tool, e.g. `news_tool.parse_article`, with payload `url` (required).
- Implementation wraps a library (e.g. `newspaper3k`) and returns `{"text": str, "summary": str}` or `{"error": str}`.
- Call only on demand (not during normal News Search) to avoid rate limits and extra latency.
- Respect robots.txt and terms of use; implement retries and timeouts.

---

## Data normalisation

- Map `published` (RSS) and market_tool date fields to `yyyy-mm-dd` or ISO 8601.
- Map `link` to `url`.
- If market_tool returns unstructured `content`, extract title/summary/url via heuristics or parsing; if not possible, create a minimal item with `title` from first line and `url` empty.

---

## Caching

| Data type    | Suggested TTL |
|--------------|---------------|
| News search  | 10 min        |
| Article body | 1 h           |

Cache can live inside MCP tools (e.g. in-memory or Redis). On cache hit, return cached data with `timestamp` indicating fetch time. Agent behaviour stays unchanged.

---

## Error handling

| Situation                | Behaviour |
|--------------------------|-----------|
| Individual source fails  | Omit that source’s items; merge items from other sources. No fallback chain. |
| All news tools fail      | Return empty `news` array and empty `citations`; do not fail the entire INFORM. |
| Parse error in tool      | Log and skip that item; include others. |

All news tools must return a dict with either a normal payload or `{"error": "..."}` so the agent can detect failure and merge partial results.

---

## Concurrency and performance

- **Financial and News in parallel:** Financial Data Search and News Search run concurrently; total latency is dominated by the slower of the two.
- **News sources in parallel:** All news tools (RSS, market_tool.get_news, market_tool.get_global_news) are invoked concurrently. No sequential priority.
- **Article parsing:** Optional and on-demand; not part of the main News Search flow.

---

## File and module layout

- **Agent:** `agents/websearch_agent.py` — Invokes news tools in parallel, normalises, merges, builds citations. See [file-structure.md](file-structure.md).
- **MCP tools:** `openfund_mcp/tools/news_tool.py` — `search_rss`, `search_yahoo_rss`, `search_gdelt`. Registered in `openfund_mcp/mcp_server.py` (FastMCP app and MCPServer.register_default_tools()).
- **Tool list:** `llm/tool_descriptions.py` (`WEBSEARCHER_ALLOWED_TOOL_NAMES`); [agent-tools-reference.md](agent-tools-reference.md) for contracts.

---

## Backward compatibility

- Keep `sentiment` and `regulatory` in the INFORM when market_tool is used, so existing Planner aggregation logic continues to work.
- Add `news` and `citations` as new keys. Downstream components can adopt them incrementally.
- If market_tool news is also folded into `news`, the same items can appear in both `sentiment`/`regulatory` (legacy) and `news` (unified) until migration is complete.

---

## Summary

- News Search is a subsystem of WebSearcher, running in parallel with Financial Data Search.
- All news sources are queried **in parallel**; results are merged with no priority-based discarding.
- Output is a structured `news` array and `citations` map, enabling [NEWS1]‑style references in answers.
- All external news access is via MCP tools (`news_tool.search_rss`, `search_yahoo_rss`, `search_gdelt`, plus market_tool).
- Time range, caching, and optional article parsing are supported as specified above.
- This design aligns with [websearcher-design.md](websearcher-design.md), [backend.md](backend.md), and [prd.md](prd.md).

---

## Future work

- **Additional sources:** Add new MCP tools for extra feeds when available; invoke in parallel with existing tools.
- **Deduplication:** Improve URL-based or fuzzy deduplication across sources.
- **Ranking:** Optional relevance ranking (e.g. by date, source reputation) before citation assignment.

---

## Verification script

Run `python scripts/verify_news_sources.py` to check availability of the implemented news sources.
