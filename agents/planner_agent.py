"""Planner agent: task decomposition and research request creation."""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Any, Optional

from a2a.acl_message import ACLMessage, Performative
from a2a.message_bus import MessageBus
from agents.base_agent import BaseAgent
from util.trace_log import trace

logger = logging.getLogger(__name__)
if TYPE_CHECKING:
    from llm.base import LLMClient

# Same allowed values as api/rest.py; normalize so Responder/OutputRail get consistent profile.
VALID_USER_PROFILES = ("beginner", "long_term", "analyst")


class TaskStep:
    """Single step in a decomposed task chain.

    Attributes:
        agent: Target agent: "librarian" | "websearcher" | "analyst".
        action: Step type (e.g. retrieve_fund_facts, answer_question).
        params: Optional parameters for the step (forwarded as ACLMessage content extras).
    """

    def __init__(
        self,
        agent: str,
        action: str,
        params: Optional[dict[str, Any]] = None,
    ) -> None:
        self.agent = agent
        self.action = action
        self.params = params or {}


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
    ) -> None:
        super().__init__(name, message_bus)
        self._llm_client = llm_client
        self._conversation_manager = conversation_manager
        self._round_pending: dict[
            str, set[str]
        ] = {}  # conversation_id -> agents we're waiting for
        self._collected: dict[
            str, dict[str, Any]
        ] = {}  # conversation_id -> { agent: content }
        self._user_profile_by_conversation: dict[
            str, str
        ] = {}  # conversation_id -> user_profile
        self._round_number: dict[str, int] = {}  # conversation_id -> 1 or 2 (max 2 rounds)
        self._original_query_by_conversation: dict[str, str] = {}  # for sufficiency/refined

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

        # Specialist replied: store content, mark agent done, forward when all three received
        if message.performative == Performative.INFORM and message.sender in (
            "librarian",
            "websearcher",
            "analyst",
        ):
            if conversation_id not in self._collected:
                return
            self._collected[conversation_id][message.sender] = content
            self._round_pending[conversation_id].discard(message.sender)
            trace(
                12,
                "planner_inform_received",
                in_={
                    "conversation_id": conversation_id,
                    "sender": message.sender,
                    "pending": list(self._round_pending[conversation_id]),
                },
                out="stored",
                next_="all received → format_final else wait",
            )
            if self._conversation_manager:
                pending_list = list(self._round_pending[conversation_id])
                still_waiting = ", ".join(pending_list) if pending_list else "none"
                snippet = self._agent_content_snippet(content)
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
            if not self._round_pending[conversation_id]:
                collected = self._collected[conversation_id]
                final = self._format_final(collected)
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
                    aggregated = self._format_aggregated_for_sufficiency(collected)
                    sufficient = self._check_sufficiency(original_query, aggregated)
                    if sufficient:
                        pass
                    elif round_num < 2:
                        refined_steps = self._get_refined_steps(
                            original_query, aggregated
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
                                                {"agent": s.agent, "action": s.action}
                                                for s in refined_steps
                                            ],
                                        },
                                    },
                                )
                            for step in refined_steps:
                                step.params = dict(step.params)
                                req = self.create_research_request(
                                    original_query, step, context=collected
                                )
                                req.conversation_id = conversation_id
                                req.reply_to = self.name
                                self.bus.send(req)
                                if self._conversation_manager:
                                    q = step.params.get("query", original_query)
                                    q_display = q if len(q) <= 120 else (q[:100] + "...")
                                    self._conversation_manager.append_flow(
                                        conversation_id,
                                        {
                                            "step": "planner_sent",
                                            "message": f"Request sent to **{step.agent}** (action: {step.action}, query: \"{q_display}\").",
                                            "detail": {
                                                "agent": step.agent,
                                                "action": step.action,
                                                "query": q,
                                                "query_preview": q[:100],
                                            },
                                        },
                                    )
                            send_to_responder = False
                        else:
                            insufficient = True
                    else:
                        insufficient = True
                if send_to_responder:
                    if insufficient:
                        final = "Insufficient information."
                    trace(
                        12,
                        "planner_format_final",
                        in_={
                            "conversation_id": conversation_id,
                            "user_profile": user_profile,
                        },
                        out=f"final_len={len(final)}",
                        next_="send INFORM to responder",
                    )
                    if self._conversation_manager:
                        self._conversation_manager.append_flow(
                            conversation_id,
                            {
                                "step": "planner_complete",
                                "message": "All agents have responded. Sending combined results to Responder to format your answer."
                                if not insufficient
                                else "Information still insufficient after 2 rounds. Responder will reply with insufficient.",
                                "detail": {"final_length": len(final)},
                            },
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
                                "insufficient": insufficient,
                            },
                            conversation_id=conversation_id,
                        )
                    )
                    trace(
                        12,
                        "planner_sent_to_responder",
                        in_={"conversation_id": conversation_id},
                        out="sent",
                        next_="responder handles",
                    )
                    del self._round_pending[conversation_id]
                    del self._collected[conversation_id]
                    self._user_profile_by_conversation.pop(conversation_id, None)
                    self._round_number.pop(conversation_id, None)
                    self._original_query_by_conversation.pop(conversation_id, None)
            return

        # New request from API: send REQUEST to all three agents (one round)
        query = content.get("query", "")
        if not query:
            return
        trace(
            6,
            "planner_request_received",
            in_={"conversation_id": conversation_id, "query_len": len(query)},
            out="ok",
            next_="decompose_task",
        )
        raw_profile = content.get("user_profile") or "beginner"
        if isinstance(raw_profile, str):
            profile = raw_profile.strip().lower()
        else:
            profile = "beginner"
        if profile not in VALID_USER_PROFILES:
            profile = "beginner"
        self._user_profile_by_conversation[conversation_id] = profile
        self._original_query_by_conversation[conversation_id] = query
        self._round_number[conversation_id] = 1
        steps = self.decompose_task(query)
        if not steps:
            return
        # Flow: one summary message with actual decomposed steps and full sub-queries
        query_short = query[:80] + ("..." if len(query) > 80 else "")
        step_parts = [f"{s.agent} ({s.action})" for s in steps]
        agents_waiting = ", ".join(s.agent for s in steps)
        waiting_set = {s.agent for s in steps}
        if self._conversation_manager:
            steps_detail = [
                {"agent": s.agent, "action": s.action, "query": s.params.get("query", query)}
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
        trace(
            7,
            "planner_handle_request",
            in_={
                "conversation_id": conversation_id,
                "query_len": len(query),
                "user_profile": profile,
                "steps": [s.agent for s in steps],
            },
            out="ok",
            next_="send REQUEST to each agent",
        )
        if self._conversation_manager:
            for s in steps:
                q = s.params.get("query", query)
                q_display = q if len(q) <= 120 else (q[:100] + "...")
                self._conversation_manager.append_flow(
                    conversation_id,
                    {
                        "step": "planner_sent",
                        "message": f"Request sent to **{s.agent}** (action: {s.action}, query: \"{q_display}\").",
                        "detail": {
                            "agent": s.agent,
                            "action": s.action,
                            "query": q,
                            "query_preview": q[:100],
                        },
                    },
                )
        self._round_pending[conversation_id] = waiting_set
        self._collected[conversation_id] = {}
        for step in steps:
            step.params = dict(step.params)
            if "path" in content:
                step.params["path"] = content[
                    "path"
                ]  # E2E and API can pass file path for file_tool
            req = self.create_research_request(query, step, context=None)
            req.conversation_id = conversation_id
            req.reply_to = self.name
            self.bus.send(req)
        trace(
            7,
            "planner_sent_requests",
            in_={"conversation_id": conversation_id},
            out="sent to librarian, websearcher, analyst",
            next_="wait INFORMs",
        )

    def _format_final(self, collected: dict[str, Any]) -> str:
        """Turn collected agent outputs into a single string for Responder.

        Args:
            collected: Map of agent name to INFORM content (e.g. librarian, websearcher, analyst).

        Returns:
            Concatenated summary string (file content, or "Librarian/WebSearcher/Analyst: ...").
        """
        parts = []
        if "librarian" in collected:
            c = collected["librarian"]
            if c.get("content"):
                parts.append(str(c["content"]))
            elif c.get("documents") or c.get("graph"):
                parts.append("Librarian: documents and graph data retrieved.")
            elif (
                c.get("file")
                and isinstance(c["file"], dict)
                and c["file"].get("content")
            ):
                parts.append(c["file"]["content"])
            else:
                parts.append("Librarian: data retrieved.")
        if "websearcher" in collected:
            w = collected["websearcher"]
            if w.get("market_data") or w.get("sentiment"):
                parts.append("WebSearcher: market and sentiment data retrieved.")
        if "analyst" in collected:
            a = collected["analyst"]
            if a.get("analysis"):
                parts.append("Analyst: analysis complete.")
        return " ".join(parts) if parts else "Research round complete."

    def _agent_content_snippet(self, content: dict[str, Any], max_chars: int = 350) -> str:
        """Human-readable summary of agent result for flow display (errors, summary, or key fields)."""
        if not content:
            return ""
        # Explicit error (e.g. from tool or MCP)
        err = content.get("error")
        if isinstance(err, str) and err.strip():
            s = err.strip()[:250]
            return f"Error: {s}{'...' if len(err) > 250 else ''}"
        if isinstance(content.get("market_data"), dict) and content["market_data"].get("error"):
            e = content["market_data"]["error"]
            s = str(e)[:250]
            return f"Error: {s}{'...' if len(str(e)) > 250 else ''}"
        # Summary from LLM or agent
        summary = content.get("summary")
        if isinstance(summary, str) and summary.strip():
            s = summary.strip()[:max_chars]
            return f"Summary: {s}{'...' if len(summary) > max_chars else ''}"
        # File content
        if content.get("file") and isinstance(content["file"], dict):
            fc = content["file"].get("content")
            if isinstance(fc, str) and fc.strip():
                s = fc.strip()[:250]
                return f"Content: {s}{'...' if len(fc) > 250 else ''}"
        # Structured keys: describe what's present and show a short preview
        parts = []
        for key in ("market_data", "sentiment", "analysis", "documents", "graph", "combined_data"):
            val = content.get(key)
            if val is None:
                continue
            if isinstance(val, dict) and val.get("error"):
                parts.append(f"{key}: Error: {str(val['error'])[:120]}")
            elif isinstance(val, dict):
                parts.append(f"{key}: present ({len(val)} keys)")
            elif isinstance(val, list):
                parts.append(f"{key}: {len(val)} items")
            else:
                text = str(val)[:150]
                parts.append(f"{key}: {text}{'...' if len(str(val)) > 150 else ''}")
        if parts:
            return " | ".join(parts)
        text = str(content)[:max_chars]
        return f"Result: {text}{'...' if len(str(content)) > max_chars else ''}"

    def _format_aggregated_for_sufficiency(self, collected: dict[str, Any]) -> str:
        """Build a string from collected agent outputs for LLM sufficiency check."""
        parts = []
        for agent in ("librarian", "websearcher", "analyst"):
            if agent not in collected:
                continue
            c = collected[agent]
            summary = c.get("summary")
            if isinstance(summary, str) and summary.strip():
                parts.append(f"[{agent}]\n{summary.strip()}")
            elif c.get("file") and isinstance(c["file"], dict) and c["file"].get("content"):
                parts.append(f"[{agent}]\n{(c['file']['content'] or '')[:2000]}")
            elif c.get("market_data") or c.get("sentiment"):
                parts.append(f"[{agent}] market/sentiment data present.")
            elif c.get("analysis") is not None:
                parts.append(f"[{agent}]\n{str(c.get('analysis', ''))[:2000]}")
            else:
                parts.append(f"[{agent}] data retrieved.")
        return "\n\n".join(parts) if parts else "No data."

    def _check_sufficiency(self, user_query: str, aggregated: str) -> bool:
        """Call LLM to decide if aggregated info is sufficient. Returns True if SUFFICIENT."""
        assert self._llm_client is not None  # caller checks before invoking
        try:
            from llm.prompts import get_planner_sufficiency_user_content

            system = "You decide if the research is sufficient to answer the user. Answer only SUFFICIENT or INSUFFICIENT."
            user_content = get_planner_sufficiency_user_content(user_query, aggregated)
            out = self._llm_client.complete(system, user_content)
            s = (out or "").strip().upper()
            # Must start with SUFFICIENT but not INSUFFICIENT (substring would match both)
            return s.startswith("SUFFICIENT") and not s.startswith("INSUFFICIENT")
        except Exception as e:
            logger.debug("Sufficiency check failed, treating as sufficient: %s", e)
            return True

    def _get_refined_steps(
        self, user_query: str, aggregated: str
    ) -> list[TaskStep]:
        """Get steps for round 2 from LLM refined-queries JSON. Returns empty list on parse failure."""
        assert self._llm_client is not None  # caller checks before invoking
        try:
            from llm.prompts import get_planner_refined_user_content

            system = "You output a JSON object with keys librarian, websearcher, analyst (only include agents that can fill gaps). Each value is a query string."
            user_content = get_planner_refined_user_content(user_query, aggregated)
            out = self._llm_client.complete(system, user_content)
            text = (out or "").strip()
            if "```" in text:
                match = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text)
                if match:
                    text = match.group(1)
            raw = json.loads(text)
            if not isinstance(raw, dict):
                return []
            steps = []
            for agent in ("librarian", "websearcher", "analyst"):
                q = raw.get(agent)
                if isinstance(q, str) and q.strip():
                    steps.append(
                        TaskStep(
                            agent=agent,
                            action="read_file" if agent == "librarian" else "fetch_market" if agent == "websearcher" else "analyze",
                            params={"query": q.strip()},
                        )
                    )
            return steps
        except Exception as e:
            logger.debug("Refined steps parse failed: %s", e)
            return []

    def decompose_task(self, query: str) -> list[TaskStep]:
        """Produce a ReAct-style task chain from the user query.

        Uses llm_client.decompose_to_steps when available (Stage 10.2); otherwise
        returns a fixed one-round chain (librarian, websearcher, analyst).

        Args:
            query: Raw user investment query.

        Returns:
            Ordered list of TaskSteps (one per specialist).
        """
        if self._llm_client is not None:
            try:
                # Use LLM to get step dicts; filter to allowed agents and build TaskSteps
                step_dicts = self._llm_client.decompose_to_steps(query)
                if step_dicts:
                    return [
                        TaskStep(
                            agent=s.get("agent", "librarian"),
                            action=s.get("action", "analyze"),
                            params=dict(s.get("params") or {}),
                        )
                        for s in step_dicts
                        if isinstance(s, dict)
                        and (s.get("agent") or "").strip().lower()
                        in ("librarian", "websearcher", "analyst")
                    ]
            except Exception as e:
                logger.debug("LLM task parse failed, using default steps: %s", e)
        # No LLM or parse failed; use fixed three steps (librarian, websearcher, analyst)
        # Pass vector_query and fund so the librarian calls vector_tool and kg_tool
        # (demo can then use populated backends; file_tool uses path=query)
        q_lower = query.lower()
        fund = "NVDA" if ("nvidia" in q_lower or "nvda" in q_lower) else ""
        return [
            TaskStep(
                agent="librarian",
                action="read_file",
                params={
                    "query": query,
                    "path": query,
                    "vector_query": query,
                    "fund": fund,
                },
            ),
            TaskStep(
                agent="websearcher", action="fetch_market", params={"query": query}
            ),
            TaskStep(agent="analyst", action="analyze", params={"query": query}),
        ]

    def create_research_request(
        self,
        query: str,
        step: TaskStep,
        context: Optional[dict[str, Any]] = None,
    ) -> ACLMessage:
        """Build a request ACL message for Librarian, WebSearcher, or Analyst.

        Args:
            query: User query.
            step: Current task step.
            context: Optional prior context.

        Returns:
            ACL message addressed to the appropriate agent.
        """
        # Content includes query (role-specific from step.params or fallback), action, and any step.params
        step_query = step.params.get("query", query)
        content = {"query": step_query, "action": step.action, **step.params}
        return ACLMessage(
            performative=Performative.REQUEST,
            sender=self.name,
            receiver=step.agent,
            content=content,
        )

    def resolve_conflicts(self, _agent_outputs: dict[str, Any]) -> Any:
        """Self-reflection when agent results conflict (Phase 2).

        Args:
            agent_outputs: Map of agent name to output.

        Returns:
            Reconciled result.
        """
        raise NotImplementedError
