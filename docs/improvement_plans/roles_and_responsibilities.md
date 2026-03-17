# Roles and Responsibilities

## Planner (Orchestrator + Policy Enforcer)
1. **Primary responsibility**
   - Decide which agents to call and in what order based on query type, risk, and freshness needs.
2. **What it must do**
   - **Classify query** into one of: price/quote, fund facts, news/sentiment, comparative analysis, portfolio/strategy, or complex thesis.
   - **Resolve entities** up front: run a Symbol/Entity Resolution Gate that outputs a canonical symbol list (e.g., ["NVDA"]) plus asset type (equity/ETF/index).
   - **Set evidence requirements** per query type.
   - **Dispatch tasks** with strict contracts: each agent gets explicit expected outputs (schema).
   - **Aggregate** results into a structured evidence ledger, not a concatenated string.
   - **Apply sufficiency checks** based on evidence ledger completeness and freshness; if insufficient, trigger a refined round with targeted sub-queries.
3. **How to achieve**
   - Add a planner-side query classifier (rules or LLM).
   - Add a shared entity resolution function reused by all agents.
   - Emit a Research Plan object containing: query_type, symbols, required_evidence, agents_to_call.
   - Enforce a minimum evidence contract; if unmet, instruct responder to return "insufficient evidence".

## Librarian (Internal Knowledge + Long-horizon Context)
1. **Primary responsibility**
   - Retrieve internal documents, historical context, and knowledge graph relationships (e.g., fund holdings, sector exposure, corporate structure).
2. **What it must do**
   - **Only run when required**: skip for pure price checks.
   - Provide structured output: documents, graph, summary, and citations (internal doc IDs).
   - Extract stable facts (e.g., business model, sector exposure, historic performance).
3. **How to achieve**
   - Use MCP tools to search vector DB and KG with symbol + query intent.
   - Summarize in a schema-first way:
     - key_facts: list of statements
     - evidence: {doc_id -> excerpt}
     - confidence: derived from doc coverage
   - Avoid hallucination: if no docs, return empty with explicit error/low confidence.

## WebSearcher (Real-time Market + News + Citations)
1. **Primary responsibility**
   - Retrieve fresh market data and recent news with sources and timestamps.
2. **What it must do**
   - **Always honor freshness** rules: price data must include timestamp; if stale, mark freshness as stale.
   - Provide normalized schema for each symbol: price, timestamp, source, fundamentals, news_items, citations.
   - Resolve conflicts between sources and label which source won and why.
   - Provide URL citations for all web/news claims.
3. **How to achieve**
   - Use MCP APIs as primary sources.
   - Use web search only when APIs fail or for news enrichment.
   - Maintain a source ranking: official API > reputable financial news > other sources.
   - Return normalized_fund + news + citations in a single canonical format.

## Analyst (Quantitative Reasoning + Scenarios)
1. **Primary responsibility**
   - Transform evidence into quantitative analysis, risk profiles, and scenario-based outputs.
2. **What it must do**
   - Consume structured inputs only: market data snapshot from WebSearcher and context from Librarian.
   - Output: confidence, risk_factors, scenario_outcomes, key_metrics, limitations.
   - Provide numeric outputs with uncertainty bands when possible.
3. **How to achieve**
   - Use MCP analyst_tool and local helpers for indicators.
   - Require explicit input validation: if price missing or stale, degrade confidence.
   - Use a confidence gate: if confidence < threshold, signal planner to avoid explicit recommendations.
   - Provide a reasoning trace: data sources used, methods applied, assumptions.

## Responder (User-facing Answer + Compliance Gate)
1. **Primary responsibility**
   - Convert structured evidence + analysis into a user-profile-appropriate response while enforcing compliance.
2. **What it must do**
   - Use OutputRail to apply compliance rules and disclaimers.
   - Format final answer with: summary, evidence with citations, risks/limitations, recommendation (only if planner marked safe).
   - If evidence is insufficient, explicitly say so with suggested next info.
3. **How to achieve**
   - Accept a structured response object from planner, not raw text.
   - Apply compliance logic: explicit recommendations only when planner marks recommendation_allowed true.
   - Ensure any recommendation includes horizon, risk profile, and evidence list.

## Orchestration Contract Summary
1. Planner emits a Research Plan with query_type, symbols, freshness_requirements, evidence_requirements.
2. Librarian and WebSearcher return structured evidence with timestamps.
3. Analyst consumes both and returns scenario + confidence.
4. Planner builds a final evidence ledger and decides recommendation_allowed yes/no and insufficient yes/no.
5. Responder formats and enforces compliance.
