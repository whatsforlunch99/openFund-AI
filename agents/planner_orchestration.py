"""Planner message orchestration and dispatch."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Optional

from a2a.acl_message import ACLMessage, Performative
from agents.planner_decompose import decompose_planner_task
from agents.planner_formatting import (
    conversation_state_snippet,
    format_aggregated_for_sufficiency,
    format_planner_final,
)
from agents.planner_sufficiency import (
    check_planner_sufficiency,
    get_planner_refined_steps,
)
from agents.planner_types import VALID_USER_PROFILES, TaskStep
from util import interaction_log
from util.answer_coverage import strong_equity_evidence_for_sufficiency
from util.specialist_snapshot import build_data_sources_from_collected

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    pass

_VALID_QUERY_TYPES = ("price", "facts", "news", "compare", "portfolio", "thesis")


class PlannerOrchestrationMixin:
    """Split part for readability."""

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

        # Normalize common request metadata for tracing and conversation state.
        content = message.content or {}
        conversation_id = (
            content.get("conversation_id") or message.conversation_id or ""
        )
        interaction_log.set_conversation_id(conversation_id)
        interaction_log.log_call(
            "agents.planner_agent.PlannerAgent.handle_message",
            params={
                "performative": getattr(
                    message.performative, "value", str(message.performative)
                ),
                "sender": message.sender,
                "content_keys": list(content.keys()) if content else [],
                "conversation_id": conversation_id,
                **interaction_log.content_preview_for_log(content),
            },
        )

        # Process specialist INFORM messages by aggregating per-conversation state.
        if message.performative == Performative.INFORM and message.sender in (
            "librarian",
            "websearcher",
            "analyst",
        ):
            if conversation_id not in self._collected:
                interaction_log.log_call(
                    "agents.planner_agent.PlannerAgent.handle_message",
                    result={
                        "skipped": True,
                        "reason": "conversation_id not in _collected",
                    },
                )
                return
            self._collected[conversation_id][message.sender] = content
            self._round_pending[conversation_id].discard(message.sender)
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
                            "result_keys": [
                                k for k in (content or {}).keys() if k != "query"
                            ],
                        },
                    },
                )
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

                # Run sufficiency check; optionally trigger one refinement round.
                if self._llm_client and original_query:
                    aggregated = format_aggregated_for_sufficiency(collected)
                    sufficient = check_planner_sufficiency(
                        self._llm_client, original_query, aggregated
                    )
                    if not sufficient and strong_equity_evidence_for_sufficiency(
                        collected
                    ):
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
                                            ]
                                        },
                                    },
                                )
                            for step in refined_steps:
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
                                        **interaction_log.content_preview_for_log(
                                            req.content
                                        ),
                                    },
                                )
                                if self._conversation_manager:
                                    q = step.params.get("query", original_query)
                                    q_display = q if len(q) <= 120 else q[:100] + "..."
                                    self._conversation_manager.append_flow(
                                        conversation_id,
                                        {
                                            "step": "planner_sent",
                                            "message": f'Request sent to **{step.agent}** (query: "{q_display}").',
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

                # Finalize planner payload and hand off to responder.
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
                    sr = self._symbol_resolution_by_conversation.get(conversation_id)
                    sym_for_fro = self._symbols_from_resolution(
                        sr if isinstance(sr, dict) else None
                    )
                    final_response_object = self._build_final_response_object(
                        final,
                        evidence_ledger,
                        recommendation,
                        original_query=original_query,
                        symbols=sym_for_fro,
                        collected=collected,
                    )
                    self._append_planner_complete_flow(
                        conversation_id, final, insufficient, partial_insufficient
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

        # Handle new incoming REQUEST from API side.
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
        self._query_type_by_conversation[conversation_id] = self._classify_query_type(
            query
        )
        self._round_number[conversation_id] = 1
        user_memory = content.get("user_memory")
        if not isinstance(user_memory, str):
            user_memory = ""
        cache_key, symbol_resolution, res_summary = self._resolve_request_context(query)
        self._symbol_resolution_by_conversation[conversation_id] = symbol_resolution
        if res_summary:
            user_memory = (user_memory + "\n\n" + res_summary).strip()

        # Record symbol-resolution context before decomposition.
        if self._conversation_manager:
            self._conversation_manager.append_flow(
                conversation_id,
                {
                    "step": "planner_symbol_resolution",
                    "message": f"Symbol resolution: **{symbol_resolution.get('status', '')}** — {symbol_resolution.get('canonical_name') or symbol_resolution.get('reason_code', '') or 'n/a'}",
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
        query_short = query[:80] + ("..." if len(query) > 80 else "")
        step_parts = [s.agent for s in steps]
        agents_waiting = ", ".join(s.agent for s in steps)
        waiting_set = {s.agent for s in steps}

        # Emit planner decomposition details for UI flow visibility.
        if self._conversation_manager:
            steps_detail = [
                {"agent": s.agent, "query": s.params.get("query", query)} for s in steps
            ]
            self._conversation_manager.append_flow(
                conversation_id,
                {
                    "step": "planner_decomposed",
                    "message": f'''Planner has decomposed your query "{query_short}" into: {"; ".join(step_parts)}. Waiting for {agents_waiting} to respond.''',
                    "detail": {
                        "query_preview": query[:200]
                        + ("..." if len(query) > 200 else ""),
                        "steps": steps_detail,
                        "waiting_for": list(waiting_set),
                    },
                },
            )
        if self._conversation_manager:
            for s in steps:
                q = s.params.get("query", query)
                q_display = q if len(q) <= 120 else q[:100] + "..."
                self._conversation_manager.append_flow(
                    conversation_id,
                    {
                        "step": "planner_sent",
                        "message": f'Request sent to **{s.agent}** (query: "{q_display}").',
                        "detail": {
                            "agent": s.agent,
                            "query": q,
                            "query_preview": q[:100],
                        },
                    },
                )
        self._round_pending[conversation_id] = waiting_set
        self._collected[conversation_id] = {}

        # Dispatch one REQUEST per planned specialist step.
        for step in steps:
            step.params = dict(step.params)
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
            result={
                "REQUEST": "sent to specialists",
                "agents": [s.agent for s in steps],
            },
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
        step_query = step.params.get("query", query)
        content = {"query": step_query, **step.params}
        sr = self._symbol_resolution_by_conversation.get(conversation_id)
        user_profile = self._user_profile_by_conversation.get(
            conversation_id, "beginner"
        )
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
