"""Planner agent: task decomposition and research request creation."""

from __future__ import annotations

from typing import Any, Optional

from a2a.acl_message import ACLMessage
from a2a.message_bus import MessageBus
from agents.base_agent import BaseAgent


class TaskStep:
    """
    Single step in a decomposed task chain.

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
    """
    Decomposes user queries into structured tasks and initiates conversations.

    Creates research requests for Librarian, WebSearcher, and Analyst.
    """

    def __init__(self, name: str, message_bus: MessageBus) -> None:
        super().__init__(name, message_bus)

    def handle_message(self, message: ACLMessage) -> None:
        """
        Handle incoming messages directed to the Planner.

        Parse content, call decompose_task, create and send research
        requests via the bus; handle STOP.

        Args:
            message: The received ACL message.
        """
        raise NotImplementedError

    def decompose_task(self, query: str) -> list[TaskStep]:
        """
        Produce a ReAct-style task chain from the user query.

        Args:
            query: Raw user investment query.

        Returns:
            Ordered list of task steps (e.g. retrieve_fund_facts then answer_question).
        """
        raise NotImplementedError

    def create_research_request(
        self,
        query: str,
        step: TaskStep,
        context: Optional[dict[str, Any]] = None,
    ) -> ACLMessage:
        """
        Build a request ACL message for Librarian, WebSearcher, or Analyst.

        Args:
            query: User query.
            step: Current task step.
            context: Optional prior context.

        Returns:
            ACL message addressed to the appropriate agent.
        """
        raise NotImplementedError

    def resolve_conflicts(self, agent_outputs: dict[str, Any]) -> Any:
        """
        Self-reflection when agent results conflict (Phase 2).

        Args:
            agent_outputs: Map of agent name to output.

        Returns:
            Reconciled result.
        """
        raise NotImplementedError
