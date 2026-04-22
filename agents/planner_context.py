"""Planner context and contract builders."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from a2a.message_bus import MessageBus
from agents.planner_formatting import (
    collected_has_answer_signal,
)
from agents.planner_types import VALID_USER_PROFILES
from llm.prompts import (
    PLANNER_CLASSIFY_QUERY_TYPE,
    get_planner_classification_user_content,
)
from util.agent_heuristics import get_planner_heuristics
from util.planner_symbol_resolution import (
    derive_cache_key,
    get_cached_entry,
    maybe_use_cached_resolution,
    put_cached_entry,
    resolution_summary_for_prompt,
)

if TYPE_CHECKING:
    from llm.base import LLMClient

_VALID_QUERY_TYPES = ("price", "facts", "news", "compare", "portfolio", "thesis")


class PlannerContextMixin:
    """Split part for readability."""

    def __init__(
        self,
        name: str,
        message_bus: MessageBus,
        llm_client: Optional[LLMClient] = None,
        conversation_manager: Any = None,
        max_research_rounds: int = 2,
    ) -> None:
        super().__init__(name, message_bus)
        self._llm_client = llm_client
        self._conversation_manager = conversation_manager
        self._round_pending: dict[str, set[str]] = {}
        self._collected: dict[str, dict[str, Any]] = {}
        self._user_profile_by_conversation: dict[str, str] = {}
        self._round_number: dict[str, int] = {}
        self._original_query_by_conversation: dict[str, str] = {}
        self._max_rounds = max(1, max_research_rounds)
        self._symbol_resolution_by_conversation: dict[str, dict[str, Any]] = {}
        self._query_type_by_conversation: dict[str, str] = {}

    def _normalize_query_type(self, value: Any) -> Optional[str]:
        """Normalize raw classifier output into a valid query type."""
        if not isinstance(value, str):
            return None
        t = value.strip().lower()
        return t if t in _VALID_QUERY_TYPES else None

    def _classify_query_type_with_llm(self, query: str) -> Optional[str]:
        """Use LLM to classify query type; return None on failure."""
        if self._llm_client is None:
            return None
        try:
            user_content = get_planner_classification_user_content(query)
            raw = self._llm_client.complete(PLANNER_CLASSIFY_QUERY_TYPE, user_content)
            return self._normalize_query_type(raw)
        except Exception:
            return None

    def _classify_query_type(self, query: str) -> str:
        """Classify query type with strict fallback to facts."""
        q = (query or "").strip()
        if not q:
            return "facts"
        classified = self._classify_query_type_with_llm(q)
        return classified or "facts"

    def _symbols_from_resolution(
        self, symbol_resolution: Optional[dict[str, Any]]
    ) -> list[str]:
        """Return canonical symbols from planner symbol resolution."""
        if not isinstance(symbol_resolution, dict):
            return []
        listings = symbol_resolution.get("listings")
        if not isinstance(listings, list):
            return []
        symbols: list[str] = []
        for rec in listings:
            if not isinstance(rec, dict):
                continue
            raw = (
                rec.get("symbol_yahoo")
                or rec.get("symbol_compact")
                or rec.get("symbol")
            )
            if isinstance(raw, str):
                sym = raw.strip().upper()
                if sym and sym not in symbols:
                    symbols.append(sym)
        return symbols

    def _build_research_plan(
        self,
        query: str,
        user_profile: str,
        symbol_resolution: Optional[dict[str, Any]],
        query_type: Optional[str] = None,
    ) -> dict[str, Any]:
        """Build canonical planner research-plan contract."""
        return {
            "query_type": query_type or self._classify_query_type(query),
            "symbols": self._symbols_from_resolution(symbol_resolution),
            "freshness_requirements": {
                "price_max_age_minutes": 15,
                "fundamentals_max_age_days": 90,
                "news_lookback_days": 7,
            },
            "evidence_requirements": {"min_sources": 2, "require_citations": True},
            "user_profile": user_profile
            if user_profile in VALID_USER_PROFILES
            else "beginner",
        }

    def _build_evidence_ledger(self, collected: dict[str, Any]) -> dict[str, Any]:
        """Normalize specialist outputs into a planner evidence-ledger contract."""
        facts: list[dict[str, Any]] = []
        market_snapshot: dict[str, Any] = {}
        for source in ("librarian", "websearcher", "analyst"):
            payload = collected.get(source)
            if not isinstance(payload, dict):
                continue
            source_payload = payload
            if source == "analyst":
                nested = payload.get("analysis")
                if isinstance(nested, dict):
                    source_payload = nested
            summary = source_payload.get("summary")
            if isinstance(summary, str) and summary.strip():
                facts.append(
                    {
                        "fact": summary.strip(),
                        "source": source,
                        "timestamp": source_payload.get("timestamp", ""),
                        "confidence": source_payload.get("confidence"),
                    }
                )
            if source == "websearcher":
                nf = payload.get("normalized_fund")
                if isinstance(nf, list) and nf and isinstance(nf[0], dict):
                    rec = nf[0]
                    symbol = rec.get("symbol")
                    price = rec.get("price")
                    if isinstance(symbol, str) and symbol.strip():
                        market_snapshot["symbol"] = symbol.strip().upper()
                    if isinstance(price, (int, float)):
                        market_snapshot["price"] = float(price)
                    ts = payload.get("timestamp") or payload.get("news_timestamp")
                    if isinstance(ts, str) and ts.strip():
                        market_snapshot["price_timestamp"] = ts.strip()
        return {"facts": facts, "market_snapshot": market_snapshot}

    def _evaluate_recommendation_gate(
        self,
        collected: dict[str, Any],
        evidence_ledger: dict[str, Any],
        query_type: Optional[str] = None,
    ) -> dict[str, Any]:
        """Decide recommendation eligibility from evidence + confidence gates."""
        facts = evidence_ledger.get("facts")
        fact_count = len(facts) if isinstance(facts, list) else 0
        web = collected.get("websearcher")
        analyst = collected.get("analyst")
        confidence = None
        if isinstance(analyst, dict):
            c = analyst.get("confidence")
            if isinstance(c, (int, float)):
                confidence = float(c)
            if confidence is None:
                nested = analyst.get("analysis")
                if isinstance(nested, dict):
                    c2 = nested.get("confidence")
                    if isinstance(c2, (int, float)):
                        confidence = float(c2)
        has_market_data = False
        if isinstance(web, dict):
            nf = web.get("normalized_fund")
            if isinstance(nf, list):
                for row in nf:
                    if not isinstance(row, dict):
                        continue
                    price = row.get("price")
                    if isinstance(price, (int, float)):
                        has_market_data = True
                        break
        if fact_count < 2:
            return {
                "recommendation_allowed": False,
                "confidence": confidence,
                "reason_code": "insufficient_evidence",
            }
        if not has_market_data:
            return {
                "recommendation_allowed": False,
                "confidence": confidence,
                "reason_code": "stale_or_missing_market_data",
            }
        if confidence is None or confidence < 0.75:
            return {
                "recommendation_allowed": False,
                "confidence": confidence,
                "reason_code": "low_confidence",
            }
        if isinstance(query_type, str) and query_type not in ("thesis", "portfolio"):
            return {
                "recommendation_allowed": False,
                "confidence": confidence,
                "reason_code": "query_type_not_recommendation",
            }
        freshness = web.get("freshness") if isinstance(web, dict) else None
        if isinstance(freshness, dict):
            if freshness.get("price_is_fresh") is False:
                return {
                    "recommendation_allowed": False,
                    "confidence": confidence,
                    "reason_code": "stale_or_missing_market_data",
                }
        return {
            "recommendation_allowed": True,
            "confidence": confidence,
            "reason_code": "gate_passed",
        }

    def _build_final_response_object(
        self,
        final_text: str,
        evidence_ledger: dict[str, Any],
        recommendation: dict[str, Any],
        *,
        original_query: str = "",
        symbols: Optional[list[str]] = None,
        collected: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Build structured responder object from final text + contracts.

        Aligns with docs/workflow/00_overview/handoff_contracts.md: summary, evidence,
        optional analysis/risks from Analyst, recommendation gate, disclaimer flag.
        """
        sym_list = list(symbols) if isinstance(symbols, list) else []
        risks: list[str] = []
        limitations: list[str] = []
        scenario_outcomes: list[Any] = []
        analysis_confidence: Optional[float] = None
        analyst = (
            collected.get("analyst") if isinstance(collected, dict) else None
        )
        if isinstance(analyst, dict):
            rf = analyst.get("risk_factors")
            if isinstance(rf, list):
                risks = [str(x).strip() for x in rf if str(x).strip()]
            lim = analyst.get("limitations")
            if isinstance(lim, list):
                limitations = [str(x).strip() for x in lim if str(x).strip()]
            so = analyst.get("scenario_outcomes")
            if isinstance(so, list):
                scenario_outcomes = so
            ac = analyst.get("confidence")
            if isinstance(ac, (int, float)):
                analysis_confidence = float(ac)
            else:
                nested = analyst.get("analysis")
                if isinstance(nested, dict):
                    ac2 = nested.get("confidence")
                    if isinstance(ac2, (int, float)):
                        analysis_confidence = float(ac2)
        if analysis_confidence is None:
            rc = recommendation.get("confidence")
            if isinstance(rc, (int, float)):
                analysis_confidence = float(rc)
        if analysis_confidence is None:
            analysis_confidence = 0.0

        allowed = bool(recommendation.get("recommendation_allowed"))
        rec_obj: dict[str, Any] = {
            "allowed": allowed,
            "action": "hold" if allowed else "none",
            "reason": str(recommendation.get("reason_code", "") or ""),
            "horizon": "mid" if allowed else "",
        }

        return {
            "query": original_query if isinstance(original_query, str) else "",
            "symbols": sym_list,
            "summary": final_text if isinstance(final_text, str) else str(final_text),
            "evidence": evidence_ledger.get("facts", []),
            "analysis": {
                "confidence": analysis_confidence,
                "scenario_outcomes": scenario_outcomes,
            },
            "recommendation": rec_obj,
            "risks": risks,
            "limitations": limitations,
            "disclaimer_required": True,
        }

    def _apply_insufficient_policy(
        self, final: str, collected: dict[str, Any], insufficient: bool
    ) -> tuple[str, bool]:
        """Apply insufficient/partial-insufficient policy to final text."""
        if not insufficient:
            return (final, False)
        if collected_has_answer_signal(collected):
            ph = get_planner_heuristics()
            return (
                ph.partial_insufficient_prefix + final + ph.partial_insufficient_suffix,
                True,
            )
        return ("Insufficient information.", False)

    def _append_planner_complete_flow(
        self,
        conversation_id: str,
        final: str,
        insufficient: bool,
        partial_insufficient: bool,
    ) -> None:
        """Append final planner flow event before responder handoff."""
        if not self._conversation_manager:
            return
        complete_msg = "All agents have responded. Sending combined results to Responder to format your answer."
        if insufficient and partial_insufficient:
            complete_msg = "Research was marked insufficient after max rounds, but substantive data exists; sending a partial answer with caveats to Responder."
        elif insufficient:
            complete_msg = f"Information still insufficient after {self._max_rounds} round(s). Responder will reply with insufficient."
        self._conversation_manager.append_flow(
            conversation_id,
            {
                "step": "planner_complete",
                "message": complete_msg,
                "detail": {
                    "final_length": len(final),
                    "partial_insufficient": partial_insufficient,
                },
            },
        )

    def _reset_conversation_state(self, conversation_id: str) -> None:
        """Clear planner per-conversation state after responder handoff."""
        del self._round_pending[conversation_id]
        del self._collected[conversation_id]
        self._user_profile_by_conversation.pop(conversation_id, None)
        self._round_number.pop(conversation_id, None)
        self._original_query_by_conversation.pop(conversation_id, None)
        self._symbol_resolution_by_conversation.pop(conversation_id, None)
        self._query_type_by_conversation.pop(conversation_id, None)

    def _resolve_request_context(
        self, query: str
    ) -> tuple[Optional[str], dict[str, Any], str]:
        """Resolve cache key + symbol resolution for a new request."""
        cache_key = derive_cache_key(query)
        cached = get_cached_entry(cache_key) if cache_key else None
        symbol_resolution = maybe_use_cached_resolution(
            query, cached, llm_client=self._llm_client
        )
        if (
            cached is None
            and cache_key
            and (symbol_resolution.get("status") == "resolved")
        ):
            put_cached_entry(cache_key, symbol_resolution)
        return (
            cache_key,
            symbol_resolution,
            resolution_summary_for_prompt(symbol_resolution),
        )
