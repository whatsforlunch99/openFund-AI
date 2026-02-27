"""Planner agent: task decomposition and research request creation."""

from __future__ import annotations

import logging
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
                self._conversation_manager.append_flow(
                    conversation_id,
                    {
                        "step": "agent_returned",
                        "message": f"**{message.sender}** has returned results to the planner (pending: {list(self._round_pending[conversation_id]) or 'none'}).",
                        "detail": {
                            "agent": message.sender,
                            "pending": list(self._round_pending[conversation_id]),
                        },
                    },
                )
            if not self._round_pending[conversation_id]:
                final = self._format_final(self._collected[conversation_id])
                user_profile = self._user_profile_by_conversation.get(
                    conversation_id, "beginner"
                )
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
                            "message": f"Planner has combined all results (final length {len(final)} chars) and is sending the answer to the responder.",
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
        if self._conversation_manager:
            self._conversation_manager.append_flow(
                conversation_id,
                {
                    "step": "planner_invoked",
                    "message": "Planner is decomposing your query into research steps.",
                    "detail": {
                        "query": query[:200] + ("..." if len(query) > 200 else "")
                    },
                },
            )
        raw_profile = content.get("user_profile") or "beginner"
        if isinstance(raw_profile, str):
            profile = raw_profile.strip().lower()
        else:
            profile = "beginner"
        if profile not in VALID_USER_PROFILES:
            profile = "beginner"
        self._user_profile_by_conversation[conversation_id] = profile
        steps = self.decompose_task(query)
        if not steps:
            return
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
                self._conversation_manager.append_flow(
                    conversation_id,
                    {
                        "step": "planner_sent",
                        "message": f"Planner is sending a request to **{s.agent}**: content (action: {s.action}, query: '{query[:80]}{'...' if len(query) > 80 else ''}'). Your query: \"{query[:60]}{'...' if len(query) > 60 else ''}\"",
                        "detail": {
                            "agent": s.agent,
                            "action": s.action,
                            "query_preview": query[:100],
                        },
                    },
                )
        self._round_pending[conversation_id] = {s.agent for s in steps}
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
            except Exception:
                pass
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
        # Content includes query, action, and any step.params (e.g. path for file_tool)
        content = {"query": query, "action": step.action, **step.params}
        return ACLMessage(
            performative=Performative.REQUEST,
            sender=self.name,
            receiver=step.agent,
            content=content,
        )

    def resolve_conflicts(self, agent_outputs: dict[str, Any]) -> Any:
        """Self-reflection when agent results conflict (Phase 2).

        Args:
            agent_outputs: Map of agent name to output.

        Returns:
            Reconciled result.
        """
        raise NotImplementedError
