# Comprehensive Plan: MCP Tool Restructure + WebSearcher Role + Authoritative News Pipeline

## Summary
Define WebSearcher as the time‑sensitive external facts agent for all tradable assets, and implement a deterministic authoritative news pipeline that behaves like “Google‑style discovery,” including allowlisted sources, weighted ranking, long‑form digest with what/where/how/consequence, and explicit JSON output.

## WebSearcher Documentation

### High‑Level Goal
Deliver same‑day, authoritative market context for any tradable entity by combining real‑time price snapshots with a long‑form, citation‑backed news digest that explains what happened, where it happened, how it happened, and the consequences.

### Contribution
- Provides the freshest external facts and headlines, complementing Librarian’s historical retrieval and Analyst’s quantitative interpretation.
- Reduces noise by filtering to authoritative sources and ranking relevance, so summaries reflect real market drivers rather than generic coverage.
- Surfaces performance‑impacting factors (supply chain shocks, disasters, regulatory actions, macro releases) that explain price moves and risk.

### Details (Behavior and Outputs)
- Scope: all tradable assets (equities, ETFs, crypto, FX, commodities, rates).
- Data sources: Google News RSS, Yahoo Finance RSS, GDELT.
- Filtering: authoritative domain allowlist; limited fallback if too few results.
- Ranking: fixed weighted score using authority, recency, and query match.
- Digest: 6–10 sentences covering what/where/how/consequence, with exactly three citations when available.
- Output: `normalized_fund` prices + `news_digest` + `citations` + `news_items` + timestamp (see schema below).



## Part B — WebSearcher Role, Tools, and Sources

### B1) Role Definition
- **Mission:** Provide same‑day or latest‑trading‑day market facts and authoritative news.
- **Scope:** All tradable assets (equities, ETFs, crypto, FX, commodities, rates).
- **Boundaries:** No internal DB queries, no long‑term analysis, no speculative commentary.

### B2) Tools Required (Conceptual)
- Price snapshots: equities/ETFs, crypto, FX, commodities, rates.
- News sources: general finance, company/fund, macro/regulatory.
- Macro/reg calendar: CPI/jobs/Fed events.
- Conflict resolution tool for price discrepancies.
- LLM fallback only when all news tools fail (explicitly flagged).

---

## Part C — Authoritative News Pipeline (Fully Specified, No Assumptions)

### C1) Data Sources (Exact)
- Google News RSS (`search_rss`)
- Yahoo Finance RSS (`search_yahoo_rss`)
- GDELT (`search_gdelt`)

### C2) Authoritative Allowlist (Exact)
Hard‑code the following domains as authoritative. Accept only items whose domain **ends with** one of these entries:

`reuters.com, bloomberg.com, wsj.com, ft.com, cnbc.com, barrons.com, marketwatch.com, sec.gov, federalreserve.gov, ecb.europa.eu, bankofengland.co.uk, bis.org, imf.org, worldbank.org, oecd.org, bls.gov, bea.gov, treasury.gov, nasdaq.com, nyse.com, cboe.com, ice.com, cmegroup.com, spglobal.com, moodys.com, fitchratings.com, finra.org, investing.com, fxstreet.com, coindesk.com, cointelegraph.com, theblock.co, ic3.gov, dataplus.sec.gov, edgar.sec.gov`

### C3) Fallback Rules (Exact)
- If allowlist yields fewer than **3** items:
  - Include up to **2** non‑allowlist items **only if** `score >= 0.60`.
  - Mark them `authority_tier: "secondary"`, `allowlist_pass: false`.
- If still fewer than **2** items:
  - Return empty list and set `news_digest` to:
    `"No authoritative news found in the last 7 days for the specified assets."`

### C4) Query Construction (Exact)
```
"<TICKER>" OR "<FUND_NAME>" OR "<FUND_NAME> ETF" OR "<ASSET_CLASS> ETF" OR "<ISSUER>"
```
Omit missing segments, always include ticker when present.

### C5) Ranking & Scoring (Exact)
```
score = (0.50 * authority_score) + (0.30 * recency_score) + (0.20 * match_score)
```
- authority_score = 1.0 allowlist, else 0.0
- recency_score = 1.0 (today), 0.7 (1–2d), 0.4 (3–7d), 0.0 (older/unknown)
- match_score = 1.0 ticker in title, 0.7 fund name, 0.4 issuer, 0.2 any query term, else 0.0  
Sort: score desc → published desc → source alpha.

### C6) Performance‑Impact Drivers (Explicit Scope)
If found, include in digest:
- supply chain disruption
- natural disaster
- geopolitical events
- regulatory actions
- macro releases
- commodity input shocks
- sector‑specific catalysts

---

## Part D — Long‑Form Digest Requirement

### D1) Digest Content (Exact)
- 6–10 sentences total.
- Must include:
  - **What happened**
  - **Where it happened**
  - **How it happened**
  - **Consequence / market impact**
- If any dimension is missing:
  - Explicitly state: `"Unclear from current sources how/where/impact occurred."`

### D2) Citations
- Must include **exactly 3 citations** when ≥3 items exist.
- If <3 items, include citations only for existing items.

---

## Part E — Output Schema (Exact)
```json
{
  "normalized_fund": [
    {
      "symbol": "VTI",
      "price": 252.34,
      "timestamp": "2026-04-08T15:42:00Z",
      "source": "yahoo_finance",
      "authority_tier": "primary"
    }
  ],
  "news_digest": "6–10 sentence digest with what/where/how/consequence.",
  "citations": [
    {"title": "Title", "source": "Reuters", "url": "https://reuters.com/..."}
  ],
  "news_items": [
    {
      "title": "Title",
      "source": "Reuters",
      "url": "https://reuters.com/...",
      "published": "2026-04-08",
      "authority_tier": "primary",
      "allowlist_pass": true,
      "score": 0.92,
      "domain": "reuters.com"
    }
  ],
  "timestamp": "2026-04-08T15:45:00Z"
}
```

---

## Part F — Sample Queries + Explicit Outputs

### F1) Sample Queries
1. “What’s going on with VTI and SPY today?”
2. “Any news on ARKK and tech ETFs?”
3. “What’s happening in BTC and ETH this week?”
4. “How are oil and USD reacting to today’s CPI?”

### F2) Explicit Example Output (Digest Style)
```json
{
  "news_digest": "U.S. equity ETFs are moving higher after a macro data release signaled steady growth (Reuters). The movement is centered in U.S. large‑cap funds such as VTI and SPY, with broad market participation reported across major exchanges (Bloomberg). Analysts cited easing inflation pressure as the key mechanism reducing rate‑sensitivity in equities (WSJ). The reaction is most visible in sectors that benefit from stable borrowing costs, with renewed inflows into index funds (Reuters). Consequences include modest ETF inflows and a rotation toward defensive sectors, according to Bloomberg. Unclear from current sources whether any supply‑chain or disaster‑related disruptions are materially affecting these funds today."
}
```

---

## Part G — Test Plan (Exact)
1. Allowlist filter test  
2. Fallback test (≤2 secondary items, score≥0.60)  
3. Scoring test (weights + ordering)  
4. Digest test (6–10 sentences + 3 citations)  
5. Performance‑driver inclusion test  

---

## Assumptions (Explicitly None Left)
- All required lists, scoring rules, and output fields are fully specified above.  
- No additional assumptions are permitted.
