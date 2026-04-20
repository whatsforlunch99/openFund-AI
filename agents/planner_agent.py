"""Planner agent: task decomposition and research request creation."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Optional

from a2a.acl_message import ACLMessage, Performative
from a2a.message_bus import MessageBus
from agents.base_agent import BaseAgent
from agents.planner_decompose import decompose_planner_task
from agents.planner_formatting import (
    collected_has_answer_signal,
    conversation_state_snippet,
    format_aggregated_for_sufficiency,
    format_planner_final,
)
from agents.planner_sufficiency import check_planner_sufficiency, get_planner_refined_steps
from agents.planner_types import VALID_USER_PROFILES, TaskStep
from llm.prompts import PLANNER_CLASSIFY_QUERY_TYPE, get_planner_classification_user_content
from util import interaction_log
from util.agent_heuristics import get_planner_heuristics
from util.answer_coverage import strong_equity_evidence_for_sufficiency
from util.planner_symbol_resolution import (
    derive_cache_key,
    get_cached_entry,
    maybe_use_cached_resolution,
    put_cached_entry,
    resolution_summary_for_prompt,
    resolve_symbol_resolution_for_query,
)
from util.specialist_snapshot import build_data_sources_from_collected

logger = logging.getLogger(__name__)
if TYPE_CHECKING:
    from llm.base import LLMClient

_VALID_QUERY_TYPES = ("price", "facts", "news", "compare", "portfolio", "thesis")


class PlannerAgent(BaseAgent):
    """Decomposes user queries into structured tasks and initiates conversations.

    Creates research requests for Librarian, WebSearcher, and Analyst.
    Slice 5: sends to all three in one round; aggregates INFORMs then forwards to Responder.
    """

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

        # store agents we're waiting for for each conversation_id
        self._round_pending: dict[
            str, set[str]
        ] = {}

        # store collected content from each agent for each conversation_id
        self._collected: dict[
            str, dict[str, Any]
        ] = {} 

        # store user profile for each conversation
        self._user_profile_by_conversation: dict[
            str, str
        ] = {}
        self._round_number: dict[str, int] = {}  # conversation_id -> round (capped by max_research_rounds)
        self._original_query_by_conversation: dict[str, str] = {}  # for sufficiency/refined
        self._max_rounds = max(1, max_research_rounds)
        # Planner symbol resolution (cached via util.planner_symbol_resolution); reused round 2
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

    def _symbols_from_resolution(self, symbol_resolution: Optional[dict[str, Any]]) -> list[str]:
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
            raw = rec.get("symbol_yahoo") or rec.get("symbol_compact") or rec.get("symbol")
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
            "evidence_requirements": {
                "min_sources": 2,
                "require_citations": True,
            },
            "user_profile": user_profile if user_profile in VALID_USER_PROFILES else "beginner",
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

        # Minimal deterministic gate defaults derived from improvement-plan targets.
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
    ) -> dict[str, Any]:
        """Build structured responder object from final text + contracts."""
        return {
            "summary": final_text if isinstance(final_text, str) else str(final_text),
            "evidence": evidence_ledger.get("facts", []),
            "recommendation": {
                "allowed": bool(recommendation.get("recommendation_allowed")),
                "action": "hold" if recommendation.get("recommendation_allowed") else "none",
                "reason": recommendation.get("reason_code", ""),
            },
        }

    def _apply_insufficient_policy(
        self, final: str, collected: dict[str, Any], insufficient: bool
    ) -> tuple[str, bool]:
        """Apply insufficient/partial-insufficient policy to final text."""
        if not insufficient:
            return final, False
        if collected_has_answer_signal(collected):
            ph = get_planner_heuristics()
            return (
                ph.partial_insufficient_prefix + final + ph.partial_insufficient_suffix,
                True,
            )
        return "Insufficient information.", False

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
        complete_msg = (
            "All agents have responded. Sending combined results to Responder to format your answer."
        )
        if insufficient and partial_insufficient:
            complete_msg = (
                "Research was marked insufficient after max rounds, but substantive "
                "data exists; sending a partial answer with caveats to Responder."
            )
        elif insufficient:
            complete_msg = (
                f"Information still insufficient after {self._max_rounds} round(s). "
                "Responder will reply with insufficient."
            )
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
            and symbol_resolution.get("status") == "resolved"
        ):
            put_cached_entry(cache_key, symbol_resolution)
        return cache_key, symbol_resolution, resolution_summary_for_prompt(symbol_resolution)

    def handle_message(self, message: ACLMessage) -> None:
        """Handle incoming messages directed to the Planner.

        Handles STOP (ignore), INFORM from specialist agents (aggregate then
        forward to Responder), and REQUEST from API (send to all three agents).

        Args:
            message: The received ACL message (REQUEST from api, or INFORM from
                librarian/websearcher/analyst).
        """
        if message.performative == Performative.STOP:
            return
        content = message.content or {}
        conversation_id = (
            content.get("conversation_id") or message.conversation_id or ""
        )
        interaction_log.set_conversation_id(conversation_id)
        interaction_log.log_call(
            "agents.planner_agent.PlannerAgent.handle_message",
            params={
                "performative": getattr(message.performative, "value", str(message.performative)),
                "sender": message.sender,
                "content_keys": list(content.keys()) if content else [],
                "conversation_id": conversation_id,
                **interaction_log.content_preview_for_log(content),
            },
        )

        # Specialist replied: store content, mark agent done, forward when all three received
        if message.performative == Performative.INFORM and message.sender in (
            "librarian",
            "websearcher",
            "analyst",
        ):
            # Aggregation phase: store specialist payload and track pending agents.
            if conversation_id not in self._collected:
                interaction_log.log_call(
                    "agents.planner_agent.PlannerAgent.handle_message",
                    result={"skipped": True, "reason": "conversation_id not in _collected"},
                )
                return
            
            # collect content from the agent 
            self._collected[conversation_id][message.sender] = content
            # remove the agent from the list of agents we're waiting for
            self._round_pending[conversation_id].discard(message.sender)

            # if the conversation manager is set, append a flow event
            if self._conversation_manager:
                pending_list = list(self._round_pending[conversation_id])
                still_waiting = ", ".join(pending_list) if pending_list else "none"
                snippet = conversation_state_snippet(content)
                self._conversation_manager.append_flow(
                    conversation_id,
                    {
                        "step": "agent_returned",
                        "message": f"**{message.sender}** has responded. Still waiting for: {still_waiting}. {snippet}",
                        "detail": {
                            "agent": message.sender,
                            "pending": pending_list,
                            "result_summary": snippet,
                            "result_keys": [k for k in (content or {}).keys() if k != "query"],
                        },
                    },
                )
            
            # if all agents have responded, compute the combined answer candidate
            if not self._round_pending[conversation_id]:
                collected = self._collected[conversation_id]
                final = format_planner_final(collected)
                user_profile = self._user_profile_by_conversation.get(
                    conversation_id, "beginner"
                )
                original_query = self._original_query_by_conversation.get(
                    conversation_id, ""
                )
                round_num = self._round_number.get(conversation_id, 1)
                send_to_responder = True
                insufficient = False
                if self._llm_client and original_query:
                    # Sufficiency phase: decide whether to stop or run a refined second round.
                    aggregated = format_aggregated_for_sufficiency(collected)
                    sufficient = check_planner_sufficiency(
                        self._llm_client, original_query, aggregated
                    )
                    if not sufficient and strong_equity_evidence_for_sufficiency(collected):
                        sufficient = True
                    if sufficient:
                        pass
                    elif round_num < self._max_rounds:
                        refined_steps = get_planner_refined_steps(
                            self._llm_client, original_query, aggregated
                        )
                        if refined_steps:
                            self._round_number[conversation_id] = 2
                            self._round_pending[conversation_id] = {
                                s.agent for s in refined_steps
                            }
                            if self._conversation_manager:
                                self._conversation_manager.append_flow(
                                    conversation_id,
                                    {
                                        "step": "planner_round2",
                                        "message": "Information insufficient after first round. Starting second round with refined queries.",
                                        "detail": {
                                            "steps": [
                                                {"agent": s.agent}
                                                for s in refined_steps
                                            ],
                                        },
                                    },
                                )
                            for step in refined_steps:
                                # Dispatch each refined step as a new REQUEST to the target specialist.
                                step.params = dict(step.params)
                                req = self.create_research_request(
                                    original_query,
                                    step,
                                    context=collected,
                                    conversation_id=conversation_id,
                                )
                                req.conversation_id = conversation_id
                                req.reply_to = self.name
                                self.bus.send(req)
                                interaction_log.log_call(
                                    "agents.planner_agent.PlannerAgent.handle_message",
                                    result={
                                        "sent_to": step.agent,
                                        **interaction_log.content_preview_for_log(req.content),
                                    },
                                )
                                if self._conversation_manager:
                                    q = step.params.get("query", original_query)
                                    q_display = q if len(q) <= 120 else (q[:100] + "...")
                                    self._conversation_manager.append_flow(
                                        conversation_id,
                                        {
                                            "step": "planner_sent",
                                            "message": f"Request sent to **{step.agent}** (query: \"{q_display}\").",
                                            "detail": {
                                                "agent": step.agent,
                                                "query": q,
                                                "query_preview": q[:100],
                                            },
                                        },
                                    )
                            send_to_responder = False
                            interaction_log.log_call(
                                "agents.planner_agent.PlannerAgent.handle_message",
                                result={
                                    "refined_REQUEST": "sent to specialists",
                                    "agents": [s.agent for s in refined_steps],
                                },
                            )
                        else:
                            insufficient = True
                    else:
                        insufficient = True
                partial_insufficient = False
                if send_to_responder:
                    evidence_ledger = self._build_evidence_ledger(collected)
                    query_type = self._query_type_by_conversation.get(conversation_id)
                    if not query_type:
                        query_type = self._classify_query_type(original_query)
                        self._query_type_by_conversation[conversation_id] = query_type
                    recommendation = self._evaluate_recommendation_gate(
                        collected, evidence_ledger, query_type=query_type
                    )
                    final, partial_insufficient = self._apply_insufficient_policy(
                        final, collected, insufficient
                    )
                    final_response_object = self._build_final_response_object(
                        final, evidence_ledger, recommendation
                    )
                    # Finalization phase: send one INFORM to responder and clean planner state.
                    self._append_planner_complete_flow(
                        conversation_id,
                        final,
                        insufficient,
                        partial_insufficient,
                    )
                    if self._conversation_manager:
                        self._conversation_manager.merge_data_sources(
                            conversation_id,
                            build_data_sources_from_collected(collected),
                        )
                    self.bus.send(
                        ACLMessage(
                            performative=Performative.INFORM,
                            sender=self.name,
                            receiver="responder",
                            content={
                                "final_response": final,
                                "conversation_id": conversation_id,
                                "user_profile": user_profile,
                                "evidence_ledger": evidence_ledger,
                                "recommendation": recommendation,
                                "final_response_object": final_response_object,
                                "insufficient": insufficient,
                                "partial_insufficient": partial_insufficient,
                            },
                            conversation_id=conversation_id,
                        )
                    )
                    interaction_log.log_call(
                        "agents.planner_agent.PlannerAgent.handle_message",
                        result={"INFORM": "sent to responder"},
                    )
                    self._reset_conversation_state(conversation_id)
            return

        # New user request phase: decompose into specialist steps and dispatch round 1.
        query = content.get("query", "")
        if not query:
            return
        raw_profile = content.get("user_profile") or "beginner"
        if isinstance(raw_profile, str):
            profile = raw_profile.strip().lower()
        else:
            profile = "beginner"
        if profile not in VALID_USER_PROFILES:
            profile = "beginner"
        self._user_profile_by_conversation[conversation_id] = profile
        self._original_query_by_conversation[conversation_id] = query
        self._query_type_by_conversation[conversation_id] = self._classify_query_type(query)
        self._round_number[conversation_id] = 1
        user_memory = content.get("user_memory")
        if not isinstance(user_memory, str):
            user_memory = ""

        cache_key, symbol_resolution, res_summary = self._resolve_request_context(query)
        self._symbol_resolution_by_conversation[conversation_id] = symbol_resolution

        if res_summary:
            user_memory = (user_memory + "\n\n" + res_summary).strip()

        if self._conversation_manager:
            self._conversation_manager.append_flow(
                conversation_id,
                {
                    "step": "planner_symbol_resolution",
                    "message": (
                        f"Symbol resolution: **{symbol_resolution.get('status', '')}** — "
                        f"{symbol_resolution.get('canonical_name') or symbol_resolution.get('reason_code', '') or 'n/a'}"
                    ),
                    "detail": {
                        "status": symbol_resolution.get("status"),
                        "cache_key": cache_key,
                        "listings_count": len(symbol_resolution.get("listings") or []),
                    },
                },
            )

        steps = self.decompose_task(
            query, user_memory=user_memory, symbol_resolution=symbol_resolution
        )
        if not steps:
            interaction_log.log_call(
                "agents.planner_agent.PlannerAgent.handle_message",
                result={"skipped": True, "reason": "no steps"},
            )
            return
        # Flow: one summary message with actual decomposed steps and full sub-queries
        query_short = query[:80] + ("..." if len(query) > 80 else "")
        step_parts = [s.agent for s in steps]
        agents_waiting = ", ".join(s.agent for s in steps)
        waiting_set = {s.agent for s in steps}
        if self._conversation_manager:
            steps_detail = [
                {"agent": s.agent, "query": s.params.get("query", query)}
                for s in steps
            ]
            self._conversation_manager.append_flow(
                conversation_id,
                {
                    "step": "planner_decomposed",
                    "message": f'Planner has decomposed your query "{query_short}" into: {"; ".join(step_parts)}. Waiting for {agents_waiting} to respond.',
                    "detail": {
                        "query_preview": query[:200] + ("..." if len(query) > 200 else ""),
                        "steps": steps_detail,
                        "waiting_for": list(waiting_set),
                    },
                },
            )
        if self._conversation_manager:
            for s in steps:
                q = s.params.get("query", query)
                q_display = q if len(q) <= 120 else (q[:100] + "...")
                self._conversation_manager.append_flow(
                    conversation_id,
                    {
                        "step": "planner_sent",
                        "message": f"Request sent to **{s.agent}** (query: \"{q_display}\").",
                        "detail": {
                            "agent": s.agent,
                            "query": q,
                            "query_preview": q[:100],
                        },
                    },
                )
        self._round_pending[conversation_id] = waiting_set
        self._collected[conversation_id] = {}
        for step in steps:
            step.params = dict(step.params)
            q = step.params.get("query", query)
            req = self.create_research_request(
                query, step, context=None, conversation_id=conversation_id
            )
            req.conversation_id = conversation_id
            req.reply_to = self.name
            self.bus.send(req)
            interaction_log.log_call(
                "agents.planner_agent.PlannerAgent.handle_message",
                result={
                    "sent_to": step.agent,
                    **interaction_log.content_preview_for_log(req.content),
                },
            )
        interaction_log.log_call(
            "agents.planner_agent.PlannerAgent.handle_message",
            result={"REQUEST": "sent to specialists", "agents": [s.agent for s in steps]},
        )

    def decompose_task(
        self,
        query: str,
        user_memory: str = "",
        symbol_resolution: Optional[dict[str, Any]] = None,
    ) -> list[TaskStep]:
        """Produce a task chain from the user query (LLM or fixed three-step fallback)."""
        return decompose_planner_task(
            self._llm_client,
            query,
            user_memory=user_memory,
            symbol_resolution=symbol_resolution,
        )

    def create_research_request(
        self,
        query: str,
        step: TaskStep,
        context: Optional[dict[str, Any]] = None,
        conversation_id: str = "",
    ) -> ACLMessage:
        """Build a request ACL message for Librarian, WebSearcher, or Analyst.

        Args:
            query: User query.
            step: Current task step (TaskStep object that holds target agent and instructions for the specific step).
            context: Optional prior context (not used in this implementation).
            conversation_id: When set, attaches planner symbol_resolution for specialists.

        Returns:
            ACL message addressed to the appropriate agent.
        """
        # Content includes query (role-specific from step.params or fallback) and any step params   
        step_query = step.params.get("query", query)
        content = {"query": step_query, **step.params} # ** dictionary unpacking, overwrite query with step.params if it exists
        sr = self._symbol_resolution_by_conversation.get(conversation_id)
        user_profile = self._user_profile_by_conversation.get(conversation_id, "beginner")
        intent_query = self._original_query_by_conversation.get(conversation_id, query)
        query_type = self._query_type_by_conversation.get(conversation_id)
        if not query_type:
            query_type = self._classify_query_type(intent_query)
            self._query_type_by_conversation[conversation_id] = query_type
        content["research_plan"] = self._build_research_plan(
            intent_query, user_profile, sr, query_type=query_type
        )
        if isinstance(sr, dict) and sr:
            content = {**content, "symbol_resolution": sr}
            if sr.get("status") == "resolved":
                listings = sr.get("listings")
                if isinstance(listings, list) and listings:
                    content["resolution_listings"] = listings
                st = sr.get("symbol_type")
                if isinstance(st, str) and st.strip():
                    content["resolution_symbol_type"] = st.strip()
                cn = sr.get("canonical_name")
                if isinstance(cn, str) and cn.strip():
                    content["resolution_canonical_name"] = cn.strip()
        return ACLMessage(
            performative=Performative.REQUEST,
            sender=self.name,
            receiver=step.agent,
            content=content,
        )

