"""Responder agent: confidence evaluation, termination, and output formatting."""

import logging
from typing import Any

from a2a.acl_message import ACLMessage, Performative
from a2a.message_bus import MessageBus
from agents.base_agent import BaseAgent

logger = logging.getLogger(__name__)


class ResponderAgent(BaseAgent):
    """Evaluates sufficiency and terminates or continues the research loop.

    Uses OutputRail for compliance check and user-profile formatting.
    Only this agent may trigger STOP broadcast.
    """

    def __init__(
        self,
        name: str,
        message_bus: MessageBus,
        output_rail: Any = None,
        conversation_manager: Any = None,
    ) -> None:
        """Initialize the responder agent.

        Args:
            name: Unique agent name.
            message_bus: Shared A2A transport.
            output_rail: Optional OutputRail for compliance and user-profile formatting.
            conversation_manager: ConversationManager for register_reply and broadcast_stop.
        """
        super().__init__(name, message_bus)
        self.output_rail = output_rail
        self.conversation_manager = conversation_manager

    def handle_message(self, message: ACLMessage) -> None:
        """Register reply and broadcast STOP.

        On INFORM with final_response and conversation_id: get user_profile from
        content (default "beginner"). If output_rail is set: format via
        format_for_user, check_compliance; if not passed append disclaimer;
        register reply with formatted final_response then broadcast STOP.
        If output_rail is None, register with original final_response.

        Args:
            message: The received ACL message (expected INFORM with final_response).
        """
        if message.performative != Performative.INFORM:
            return
        content = message.content or {}
        conversation_id = content.get("conversation_id") or message.conversation_id
        final_response = content.get("final_response")
        if not conversation_id or final_response is None:
            return
        user_profile = content.get("user_profile") or "beginner"
        if isinstance(user_profile, str):
            user_profile = user_profile.strip() or "beginner"
        else:
            user_profile = "beginner"
        logger.info(
            "[trace] step=13 stage=responder_inform_received conversation_id=%s user_profile=%s draft_len=%s",
            conversation_id, user_profile, len(final_response) if isinstance(final_response, str) else 0,
        )

        # Format by profile and check compliance; append disclaimer if blocked phrase found
        if self.output_rail is not None:
            draft = self.output_rail.format_for_user(
                (
                    final_response
                    if isinstance(final_response, str)
                    else str(final_response)
                ),
                user_profile,
            )
            logger.info("[trace] step=13a stage=responder_format_for_user conversation_id=%s draft_len=%s", conversation_id, len(draft))
            comp = self.output_rail.check_compliance(draft)
            logger.info("[trace] step=13b stage=responder_check_compliance conversation_id=%s passed=%s", conversation_id, comp.passed)
            if not comp.passed:
                draft = f"{draft}\n\nThis is not investment advice."
            final_response = draft

        # Register reply and broadcast STOP so other agents exit their run loop
        reply_content = {
            "final_response": final_response,
            "conversation_id": conversation_id,
        }
        reply_msg = ACLMessage(
            performative=Performative.INFORM,
            sender=self.name,
            receiver="api",
            content=reply_content,
            conversation_id=conversation_id,
        )
        if self.conversation_manager:
            logger.debug("[trace] step=13c stage=responder_register_reply conversation_id=%s", conversation_id)
            self.conversation_manager.register_reply(conversation_id, reply_msg)
            logger.debug("[trace] step=13d stage=responder_broadcast_stop conversation_id=%s", conversation_id)
            self.conversation_manager.broadcast_stop(conversation_id)

    def evaluate_confidence(self, analysis: dict) -> float:
        """Compute confidence score for the analysis output.

        Args:
            analysis: Analyst output dict.

        Returns:
            Confidence score between 0 and 1.
        """
        raise NotImplementedError

    def should_terminate(self, confidence: float) -> bool:
        """Determine if the research loop should stop.

        Args:
            confidence: Current confidence score.

        Returns:
            True if termination condition is met.
        """
        raise NotImplementedError

    def format_response(self, analysis: dict, user_profile: str) -> str:
        """Turn analysis dict into user-facing text via OutputRail.

        Args:
            analysis: Analyst output.
            user_profile: User type (e.g. beginner, long_term, analyst).

        Returns:
            Formatted string for the user.
        """
        raise NotImplementedError

    def request_refinement(self, reason: str) -> ACLMessage:
        """Build message back to Planner for another research cycle.

        Args:
            reason: Why refinement is needed.

        Returns:
            ACL message addressed to Planner.
        """
        raise NotImplementedError
