"""Responder agent: confidence evaluation, termination, and output formatting."""

from typing import Any, Optional

from agents.base_agent import BaseAgent
from a2a.acl_message import ACLMessage
from a2a.message_bus import MessageBus


class ResponderAgent(BaseAgent):
    """
    Evaluates sufficiency and terminates or continues the research loop.

    Uses OutputRail for compliance check and user-profile formatting.
    Only this agent may trigger STOP broadcast.
    """

    def __init__(
        self,
        name: str,
        message_bus: MessageBus,
        output_rail: Any = None,
    ) -> None:
        super().__init__(name, message_bus)
        self.output_rail = output_rail

    def handle_message(self, message: ACLMessage) -> None:
        """
        Receive analysis; evaluate_confidence; if not should_terminate
        send request_refinement else run OutputRail and send final
        response; optionally broadcast_stop.

        Args:
            message: The received ACL message (analysis payload).
        """
        raise NotImplementedError

    def evaluate_confidence(self, analysis: dict) -> float:
        """
        Compute confidence score for the analysis output.

        Args:
            analysis: Analyst output dict.

        Returns:
            Confidence score between 0 and 1.
        """
        raise NotImplementedError

    def should_terminate(self, confidence: float) -> bool:
        """
        Determine if the research loop should stop.

        Args:
            confidence: Current confidence score.

        Returns:
            True if termination condition is met.
        """
        raise NotImplementedError

    def format_response(self, analysis: dict, user_profile: str) -> str:
        """
        Turn analysis dict into user-facing text via OutputRail.

        Args:
            analysis: Analyst output.
            user_profile: User type (e.g. beginner, long_term, analyst).

        Returns:
            Formatted string for the user.
        """
        raise NotImplementedError

    def request_refinement(self, reason: str) -> ACLMessage:
        """
        Build message back to Planner for another research cycle.

        Args:
            reason: Why refinement is needed.

        Returns:
            ACL message addressed to Planner.
        """
        raise NotImplementedError
