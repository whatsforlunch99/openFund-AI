# Hardcoded / static logic that should be config or LLM-driven (per /docs)

Per PRD and backend.md: orchestrator decides sufficiency; specialists use LLM for tool selection; confidence and thresholds are configurable. The following issues exist in the codebase.

---

## 1. Config thresholds defined but never used

**Docs:** backend.md — "Sufficiency: threshold configurable"; "Thresholds: PLANNER_SUFFICIENCY_THRESHOLD (default 0.6), ANALYST_CONFIDENCE_THRESHOLD (default 0.6), RESPONDER_CONFIDENCE_THRESHOLD (default 0.75)."

**Code:** `config/config.py` defines `planner_sufficiency_threshold`, `analyst_confidence_threshold`, `responder_confidence_threshold` and loads them from env. None of these are passed into or used by the agents.

- **Planner:** Sufficiency is decided only by LLM (`_check_sufficiency` returns True/False from "SUFFICIENT"/"INSUFFICIENT"). `planner_sufficiency_threshold` is never read. So the documented "configurable threshold" is dead.
- **Analyst:** Uses hardcoded `0.5` in `needs_more_data()` and hardcoded `0.6`/`0.7` in `analyze()` stub. Does not receive or use `analyst_confidence_threshold`.
- **Responder:** `evaluate_confidence` and `should_terminate` are `NotImplementedError`; Responder never uses confidence to decide anything. So `responder_confidence_threshold` is unused.

**Fix options:** (a) Pass `Config` (or the three threshold floats) into Planner, Analyst, and Responder and use them where applicable; or (b) Document that sufficiency is LLM-only and remove/deprecate the planner threshold; and wire analyst/responder thresholds when those behaviors are implemented.

---

## 2. Planner: max rounds hardcoded to 2

**Docs:** PRD — "Orchestrated research (internal specialists used as needed; **one or more rounds**)."

**Code:** `agents/planner_agent.py` line 144: `elif round_num < 2:` and line 69 comment "max 2 rounds". So round-2 refinement is capped at exactly 2 rounds.

**Fix:** Make max rounds configurable (e.g. `Config.max_research_rounds` default 2, or env `MAX_RESEARCH_ROUNDS`). Planner would need to receive config or a single int.

---

## 3. Analyst: stub confidence and “needs more data” threshold hardcoded

**Docs:** backend.md — "Analyst may request more data below its threshold"; "ANALYST_CONFIDENCE_THRESHOLD (default 0.6)."

**Code:**
- `agents/analyst_agent.py` line 235: `return {"confidence": 0.7, ...}` when API succeeds.
- Line 237: `return {"confidence": 0.6, "summary": "Stub analysis", ...}` when stub.
- Line 249: `needs_more_data()` uses `return (analysis_result.get("confidence") or 0) < 0.5` — hardcoded `0.5`, not config.

**Fix:** Use `analyst_confidence_threshold` from config (Analyst needs to receive config or the float). Stub confidence values could align with that threshold or be derived from actual analysis/LLM when available.

---

## 4. Analyst.analyze() fallback: symbol, indicator, and dates hardcoded

**Docs:** Specialists use LLM to choose tools and parameters; query/context should drive behavior.

**Code:** `agents/analyst_agent.py` lines 223–230: when `mcp_client` exists, calls `analyst_tool.get_indicators` with fixed payload:
- `"symbol": "AAPL"`
- `"indicator": "sma_50"`
- `"as_of_date": "2024-01-15"`
- `"look_back_days": 10`

This path is used when the Analyst falls back to the non–tool-selection path (e.g. no LLM or empty tool list). The payload does not reflect the planner’s query or message content.

**Fix:** Derive symbol, indicator, and dates from `structured_data`, `market_data`, or the request `content` (e.g. query string or prior tool results). If nothing is available, keep a minimal stub but avoid hardcoding a specific ticker/date in the main code path.

---

## 5. Planner decompose_task fallback: only NVDA extracted as fund

**Docs:** Planner decomposes the user query into agent-specific sub-queries; params can include “tool-relevant hints.”

**Code:** `agents/planner_agent.py` lines 525–526: when LLM is unavailable or fails, `fund = "NVDA" if ("nvidia" in q_lower or "nvda" in q_lower) else ""`. No other tickers/symbols are inferred.

**Fix:** Either (a) use a small heuristic/NER or LLM to infer symbol from query (e.g. AAPL, TSLA) for the fallback path, or (b) leave `fund` empty when unknown and document that full decomposition requires LLM.

---

## 6. Planner _get_refined_steps: actions hardcoded per agent

**Docs:** Orchestrator decides which specialists to call and decomposes into sub-queries; round-2 “refined queries” are from LLM.

**Code:** `agents/planner_agent.py` lines 479–482: for round 2, the LLM returns only agent → query; the action is set statically: `"read_file"` for librarian, `"fetch_market"` for websearcher, `"analyze"` for analyst.

**Fix (optional):** If the refined-step LLM prompt is extended to return an action per agent, parse and use it; otherwise document that round-2 actions are fixed per role.

---

## 7. Responder: confidence-based termination not implemented

**Docs:** backend.md — "Responder uses confidence to decide terminate vs request refinement."

**Code:** `agents/responder_agent.py`: `evaluate_confidence()` and `should_terminate()` are `raise NotImplementedError`. The actual flow is: Planner decides sufficiency (LLM) and sends either consolidated data to Responder or marks insufficient; Responder only formats and sends the final answer. No confidence score is passed to Responder or used there.

**Fix:** Either (a) implement confidence flow (e.g. Planner passes analyst confidence to Responder; Responder uses `responder_confidence_threshold` and `should_terminate` to decide whether to format answer or request another round), or (b) Update docs to state that only the Planner evaluates sufficiency and Responder does not use confidence.

---

## Summary

| Location | Issue | Per docs |
|----------|--------|----------|
| Config + Planner | `planner_sufficiency_threshold` never used; sufficiency is LLM-only | Threshold configurable |
| Config + Analyst | `analyst_confidence_threshold` never used; 0.5/0.6/0.7 hardcoded | Use threshold |
| Config + Responder | `responder_confidence_threshold` never used | Confidence decides terminate/refinement |
| Planner | `round_num < 2` (max 2 rounds) | One or more rounds; could be config |
| Analyst | `needs_more_data` uses 0.5 | Use config threshold |
| Analyst | `analyze()` fallback: AAPL, sma_50, 2024-01-15, 10 | Query/context-driven |
| Planner | Fallback `fund` only NVDA | Decomposed params / hints |
| Planner | Round-2 actions fixed per agent | Optional: LLM could return action |
| Responder | evaluate_confidence / should_terminate not implemented | Responder uses confidence |

Recommended order to fix: (1) wire config thresholds into agents that should use them; (2) make max rounds configurable; (3) replace Analyst stub and fallback hardcoding with query/context-driven or config-based values; (4) align docs with behavior or implement Responder confidence flow.
