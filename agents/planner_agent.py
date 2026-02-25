"""Planner agent: task decomposition and research request creation."""

from __future__ import annotations

from typing import Any, Optional

from a2a.acl_message import ACLMessage, Performative
from a2a.message_bus import MessageBus
from agents.base_agent import BaseAgent


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
    """

    def __init__(self, name: str, message_bus: MessageBus) -> None:
        super().__init__(name, message_bus)

    def handle_message(self, message: ACLMessage) -> None:
        """Handle incoming messages directed to the Planner.

        - STOP: ignore (BaseAgent.run() will exit the loop).
        - INFORM from librarian: forward as INFORM to responder with final_response
          so Responder can register_reply and broadcast_stop.
        - REQUEST from api: decompose_task (Slice 3: one step to librarian), merge in
          optional path from content (for E2E), create_research_request, send to step.agent.

        Args:
            message: The received ACL message.
        """
        if message.performative == Performative.STOP:
            return
        content = message.content or {}
        conversation_id = content.get("conversation_id") or message.conversation_id

        # Librarian replied with file/content; forward to Responder so it can close the conversation
        if message.performative == Performative.INFORM and message.sender == "librarian":
            final = content.get("content") or content.get("error") or str(content)
            self.bus.send(
                ACLMessage(
                    performative=Performative.INFORM,
                    sender=self.name,
                    receiver="responder",
                    content={
                        "final_response": final,
                        "conversation_id": conversation_id,
                    },
                    conversation_id=conversation_id,
                )
            )
            return

        # New request from API: decompose and send first step to librarian
        query = content.get("query", "")
        reply_to = self.name
        if not query:
            return
        steps = self.decompose_task(query)
        if not steps:
            return
        step = steps[0]
        step.params = dict(step.params)
        if "path" in content:
            step.params["path"] = content["path"]  # E2E passes path for file_tool
        req = self.create_research_request(query, step, context=None)
        req.conversation_id = conversation_id or req.conversation_id
        req.reply_to = reply_to
        self.bus.send(req)

    def decompose_task(self, query: str) -> list[TaskStep]:
        """Produce a ReAct-style task chain from the user query.

        Slice 3: single step to librarian only.

        Args:
            query: Raw user investment query.

        Returns:
            Ordered list of task steps (e.g. retrieve_fund_facts then answer_question).
        """
        return [
            TaskStep(agent="librarian", action="read_file", params={"query": query}),
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
