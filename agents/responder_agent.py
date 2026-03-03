"""Responder agent: confidence evaluation, termination, and output formatting."""

import logging
from typing import TYPE_CHECKING, Any

from a2a.acl_message import ACLMessage, Performative
from a2a.message_bus import MessageBus
from agents.base_agent import BaseAgent
from util.trace_log import trace
from util import interaction_log

if TYPE_CHECKING:
    from llm.base import LLMClient

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
        llm_client: "LLMClient | None" = None,
    ) -> None:
        """Initialize the responder agent.

        Args:
            name: Unique agent name.
            message_bus: Shared A2A transport.
            output_rail: Optional OutputRail for compliance and user-profile formatting.
            conversation_manager: ConversationManager for register_reply and broadcast_stop.
            llm_client: Optional LLM client for format_response (uses RESPONDER_SYSTEM when set).
        """
        super().__init__(name, message_bus)
        self.output_rail = output_rail
        self.conversation_manager = conversation_manager
        self._llm_client = llm_client

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
        if not isinstance(conversation_id, str):
            conversation_id = str(conversation_id)
        interaction_log.set_conversation_id(conversation_id)
        interaction_log.log_call(
            "agents.responder_agent.ResponderAgent.handle_message",
            params={
                "performative": getattr(message.performative, "value", str(message.performative)),
                "sender": message.sender,
                "content_keys": list(content.keys()) if content else [],
                "conversation_id": conversation_id,
            },
        )
        # When planner marks insufficient after max rounds, force this exact message
        if content.get("insufficient"):
            final_response = "Insufficient information."
        # Normalize profile value before formatting so OutputRail logic is deterministic.
        user_profile = content.get("user_profile") or "beginner"
        if isinstance(user_profile, str):
            user_profile = user_profile.strip() or "beginner"
        else:
            user_profile = "beginner"
        trace(
            13,
            "responder_inform_received",
            in_={
                "conversation_id": conversation_id,
                "user_profile": user_profile,
                "draft_len": len(final_response)
                if isinstance(final_response, str)
                else 0,
            },
            out="ok",
            next_="format_for_user, check_compliance",
        )
        if self.conversation_manager and conversation_id:
            self.conversation_manager.append_flow(
                conversation_id,
                {
                    "step": "responder_formatting",
                    "message": f"**Responder** received the combined answer. Formatting for your profile ({user_profile}) and checking compliance.",
                    "detail": {"user_profile": user_profile},
                },
            )

        # Formatting phase: derive user-facing draft and run policy compliance checks.
        final_text = (
            final_response if isinstance(final_response, str) else str(final_response)
        )
        if self.output_rail is not None:
            if self._llm_client is not None:
                from llm.prompts import RESPONDER_SYSTEM, get_responder_user_content

                user_content = get_responder_user_content(user_profile, final_text)
                draft = self._llm_client.complete(RESPONDER_SYSTEM, user_content)
            else:
                draft = self.output_rail.format_for_user(final_text, user_profile)
            trace(
                13,
                "responder_format_for_user",
                in_={"conversation_id": conversation_id},
                out=f"draft_len={len(draft)}",
                next_="check_compliance",
            )
            comp = self.output_rail.check_compliance(draft)
            trace(
                13,
                "responder_check_compliance",
                in_={"conversation_id": conversation_id},
                out=f"passed={comp.passed}",
                next_="register_reply or append disclaimer",
            )
            if not comp.passed:
                draft = f"{draft}\n\nThis is not investment advice."
            final_response = draft

        # Finalization phase: persist answer to conversation state and stop all agent loops.
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
            trace(
                13,
                "responder_register_reply",
                in_={"conversation_id": conversation_id},
                out="final_response stored",
                next_="broadcast_stop",
            )
            self.conversation_manager.append_flow(
                conversation_id,
                {
                    "step": "response_ready",
                    "message": "Your answer is ready.",
                    "detail": {},
                },
            )
            trace(
                13,
                "responder_broadcast_stop",
                in_={"conversation_id": conversation_id},
                out="STOP sent",
                next_="agents exit",
            )
            self.conversation_manager.register_reply(conversation_id, reply_msg)
            self.conversation_manager.broadcast_stop(conversation_id)
            interaction_log.log_call(
                "agents.responder_agent.ResponderAgent.handle_message",
                result={"reply_registered": True, "broadcast_stop": True},
            )

    def evaluate_confidence(self, _analysis: dict) -> float:
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

    def format_response(self, _analysis: dict, user_profile: str) -> str:
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
