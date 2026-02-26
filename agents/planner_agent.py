"""Planner agent: task decomposition and research request creation."""

from __future__ import annotations

from typing import Any, Optional

from a2a.acl_message import ACLMessage, Performative
from a2a.message_bus import MessageBus
from agents.base_agent import BaseAgent

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

    def __init__(self, name: str, message_bus: MessageBus) -> None:
        super().__init__(name, message_bus)
        self._round_pending: dict[str, set[str]] = {}  # conversation_id -> agents we're waiting for
        self._collected: dict[str, dict[str, Any]] = {}  # conversation_id -> { agent: content }
        self._user_profile_by_conversation: dict[str, str] = {}  # conversation_id -> user_profile

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
        conversation_id = content.get("conversation_id") or message.conversation_id or ""

        # Specialist replied: store content, mark agent done, forward when all three received
        if message.performative == Performative.INFORM and message.sender in ("librarian", "websearcher", "analyst"):
            if conversation_id not in self._collected:
                return
            self._collected[conversation_id][message.sender] = content
            self._round_pending[conversation_id].discard(message.sender)
            if not self._round_pending[conversation_id]:
                final = self._format_final(self._collected[conversation_id])
                user_profile = self._user_profile_by_conversation.get(conversation_id, "beginner")
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
                del self._round_pending[conversation_id]
                del self._collected[conversation_id]
                self._user_profile_by_conversation.pop(conversation_id, None)
            return

        # New request from API: send REQUEST to all three agents (one round)
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
        steps = self.decompose_task(query)
        if not steps:
            return
        self._round_pending[conversation_id] = {s.agent for s in steps}
        self._collected[conversation_id] = {}
        for step in steps:
            step.params = dict(step.params)
            if "path" in content:
                step.params["path"] = content["path"]  # E2E passes path for file_tool
            req = self.create_research_request(query, step, context=None)
            req.conversation_id = conversation_id
            req.reply_to = self.name
            self.bus.send(req)

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
            elif c.get("file") and isinstance(c["file"], dict) and c["file"].get("content"):
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

        Slice 5: one round with all three agents (librarian, websearcher, analyst).

        Args:
            query: Raw user investment query.

        Returns:
            Ordered list of TaskSteps (one per specialist).
        """
        return [
            TaskStep(agent="librarian", action="read_file", params={"query": query}),
            TaskStep(agent="websearcher", action="fetch_market", params={"query": query}),
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
