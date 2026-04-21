"""Responder agent: confidence evaluation, termination, and output formatting."""

import logging
from typing import TYPE_CHECKING, Any

from a2a.acl_message import ACLMessage, Performative
from a2a.message_bus import MessageBus
from agents.base_agent import BaseAgent
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

    def _format_from_final_response_object(self, obj: dict[str, Any]) -> str:
        """Render planner final_response_object into user-facing text."""
        summary = obj.get("summary")
        text = summary.strip() if isinstance(summary, str) else ""
        parts: list[str] = [text] if text else []

        evidence = obj.get("evidence")
        if isinstance(evidence, list) and evidence:
            lines: list[str] = []
            for item in evidence[:3]:
                if not isinstance(item, dict):
                    continue
                fact = item.get("fact")
                if isinstance(fact, str) and fact.strip():
                    meta: list[str] = []
                    src = item.get("source")
                    if isinstance(src, str) and src.strip():
                        meta.append(src.strip())
                    ts = item.get("timestamp")
                    if isinstance(ts, str) and ts.strip():
                        meta.append(ts.strip())
                    cid = item.get("citation_id")
                    if isinstance(cid, str) and cid.strip():
                        meta.append(cid.strip())
                    suffix = f" ({', '.join(meta)})" if meta else ""
                    lines.append(f"- {fact.strip()}{suffix}")
            if lines:
                parts.append("Evidence:\n" + "\n".join(lines))

        risks = obj.get("risks")
        if isinstance(risks, list) and risks:
            risk_lines = [f"- {str(r).strip()}" for r in risks if str(r).strip()]
            if risk_lines:
                parts.append("Risks:\n" + "\n".join(risk_lines))

        limitations = obj.get("limitations")
        if isinstance(limitations, list) and limitations:
            lim_lines = [f"- {str(x).strip()}" for x in limitations if str(x).strip()]
            if lim_lines:
                parts.append("Limitations:\n" + "\n".join(lim_lines))

        rec = obj.get("recommendation")
        if isinstance(rec, dict) and rec.get("allowed"):
            action = rec.get("action")
            reason = rec.get("reason")
            if isinstance(action, str) and action.strip():
                rec_line = f"Recommendation: {action.strip().upper()}"
                if isinstance(reason, str) and reason.strip():
                    rec_line += f" - {reason.strip()}"
                parts.append(rec_line)
        return "\n\n".join(p for p in parts if p).strip()

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
        fro = content.get("final_response_object")
        if not conversation_id or (
            final_response is None and not isinstance(fro, dict)
        ):
            return
        if not isinstance(conversation_id, str):
            conversation_id = str(conversation_id)
        interaction_log.set_conversation_id(conversation_id)
        interaction_log.log_call(
            "agents.responder_agent.ResponderAgent.handle_message",
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
        # When planner marks insufficient after max rounds, force a short failure message unless
        # planner already attached a partial answer body (substantive research + caveats).
        if content.get("insufficient") and not content.get("partial_insufficient"):
            final_response = "Insufficient information."
        # Normalize profile value before formatting so OutputRail logic is deterministic.
        user_profile = content.get("user_profile") or "beginner"
        if isinstance(user_profile, str):
            user_profile = user_profile.strip() or "beginner"
        else:
            user_profile = "beginner"
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
            final_response
            if isinstance(final_response, str)
            else str(final_response or "")
        )
        if not (
            content.get("insufficient") and not content.get("partial_insufficient")
        ):
            if isinstance(fro, dict):
                rendered = self._format_from_final_response_object(fro)
                if rendered:
                    final_text = rendered
        final_response = final_text
        if self.output_rail is not None:
            try:
                if self._llm_client is not None:
                    from llm.prompts import RESPONDER_SYSTEM, get_responder_user_content

                    user_content = get_responder_user_content(user_profile, final_text)
                    draft = self._llm_client.complete(RESPONDER_SYSTEM, user_content)
                else:
                    draft = self.output_rail.format_for_user(final_text, user_profile)
                comp = self.output_rail.check_compliance(draft)
                if not comp.passed:
                    # Fall back to a deterministic safe response when compliance fails.
                    safe_fallback = (
                        "I can share general information only and cannot provide "
                        "personalized investment advice.\n\n"
                        "This is not investment advice."
                    )
                    fallback_comp = self.output_rail.check_compliance(safe_fallback)
                    draft = (
                        safe_fallback
                        if fallback_comp.passed
                        else "This is not investment advice."
                    )
                final_response = draft
            except Exception as e:
                logger.warning("Responder formatting/compliance failed: %s", e)
                final_response = (
                    "I can share general information only and cannot provide "
                    "personalized investment advice.\n\n"
                    "This is not investment advice."
                )

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
            self.conversation_manager.append_flow(
                conversation_id,
                {
                    "step": "response_ready",
                    "message": "Your answer is ready.",
                    "detail": {},
                },
            )
            self.conversation_manager.register_reply(conversation_id, reply_msg)
            self.conversation_manager.broadcast_stop(conversation_id)
            interaction_log.log_call(
                "agents.responder_agent.ResponderAgent.handle_message",
                result={"reply_registered": True, "broadcast_stop": True},
            )
        else:
            # Fallback for non-managed runtime: still deliver final response to API.
            self.bus.send(reply_msg)
            interaction_log.log_call(
                "agents.responder_agent.ResponderAgent.handle_message",
                result={"reply_sent_via_bus": True, "broadcast_stop": False},
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
