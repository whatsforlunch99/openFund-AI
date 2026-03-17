# Multi-Agent Orchestration Memo for Accurate, Fast Financial Advice

This memo defines how the planner, librarian, websearcher, analyst, and responder should coordinate to deliver accurate, fast, and compliant financial advice across trading-related queries. It clarifies role boundaries, tightens handoff contracts, and establishes orchestration gates so recommendations are only produced when evidence and freshness requirements are met.


**Title: Multi‑Agent Orchestration Memo for Accurate, Fast Financial Advice**

**Summary**
1. Produce a structured memo that explains current roles (planner, librarian, websearcher, analyst, responder), identifies concrete gaps impacting accuracy/latency/compliance, and recommends a tighter orchestration model optimized for financial advice.
2. Include explicit guidance on enabling buy/sell/hold recommendations safely by adjusting compliance policy and adding hard gating criteria.

**Implementation Changes (Design‑Level Recommendations in Memo)**
1. **Role clarity and responsibilities**
   - Planner: shift from “always parallel” to “decision‑tree” orchestration based on question type, data freshness need, and risk (e.g., price lookup vs thesis vs portfolio).
   - Librarian: focus on internal/docs/KB context, historical or explanatory data; avoid being called for pure price checks.
   - WebSearcher: primary source for real‑time and news; enforce data freshness and source ranking; provide citations and timestamps.
   - Analyst: require structured inputs (normalized symbol, market data snapshot, librarian context) and produce confidence + scenario‑based outputs.
   - Responder: enforce final policy/formatting; include evidence list, timestamps, and rationale for recommendations.

2. **Orchestration improvements**
   - Add a **Symbol/Entity Resolution Gate** before any tools, producing a canonical symbol shared by all agents.
   - Add an **Evidence Ledger** in planner aggregation: normalized facts with source, timestamp, reliability.
   - Replace planner’s current string concat with **structured aggregation**; responder consumes structured facts instead of summaries.
   - Introduce **confidence gates**: only allow explicit recommendations if confidence ≥ 0.75 and key data is fresh (e.g., price ≤ 15 minutes; fundamentals ≤ 90 days).
   - Use **fail‑soft paths**: if web data is missing or stale, responder returns “insufficient evidence” rather than LLM hallucination.
   - Add **fast‑path** for “price/quote” or “basic fund facts” using only websearcher when safe.

3. **Compliance policy changes (to allow explicit recs)**
   - Update OutputRail/guardrails to permit buy/sell/hold phrasing **only** when:
     - Confidence gate passed.
     - Evidence ledger includes minimum sources (e.g., 2 independent data sources or 1 API + 1 web citation).
     - Risks and horizon are stated.
   - Add explicit disclaimer template for recommendations.

4. **Reliability and latency**
   - Cache market data per symbol with TTLs (short for price, longer for fundamentals).
   - Prioritize API tools; use web search only as backup or for news/citations.
   - Enforce timeouts and fallback ordering per agent.

**Test Plan (for future implementation)**
1. Query types: price check, ETF comparison, earnings/news impact, valuation thesis, portfolio rebalancing.
2. Verify:
   - Symbol resolution consistency across agents.
   - Recommendations only when gates pass.
   - Freshness timestamps present in final response.
   - Evidence citations included when using web sources.
   - Latency within budget for fast‑path queries.

**Assumptions**
1. Explicit recommendations are allowed only after compliance policy updates.
2. Confidence gate default: ≥ 0.75; freshness gate default: price ≤ 15 minutes; fundamentals ≤ 90 days.
3. APIs remain primary sources; web citations are secondary and must be labeled.
4. The memo will reference current code behavior in `agents/planner_agent.py`, `agents/websearch_agent.py`, `agents/analyst_agent.py`, `agents/responder_agent.py`, and `safety/safety_gateway.py` only to describe current roles and gaps.

