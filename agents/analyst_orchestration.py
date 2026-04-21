"""Analyst message handling and tool orchestration."""

from typing import TYPE_CHECKING, Any, Optional

from a2a.acl_message import ACLMessage, Performative
from a2a.message_bus import MessageBus
from agents.analyst_helpers import (
    apply_resolved_symbol_to_analyst_calls,
    resolved_symbol_from_planner,
    tool_error_is_av_cooldown,
)
from openfund_mcp.tools.market.routing import alpha_vantage_cooldown_active
from util import interaction_log

if TYPE_CHECKING:
    from llm.base import LLMClient


class AnalystOrchestrationMixin:
    """Split part for readability."""

    def __init__(
        self,
        name: str,
        message_bus: MessageBus,
        mcp_client: Any = None,
        conversation_manager: Any = None,
        llm_client: "LLMClient | None" = None,
        analyst_confidence_threshold: float = 0.6,
    ) -> None:
        super().__init__(name, message_bus)
        self.mcp_client = mcp_client
        self.conversation_manager = conversation_manager
        self._llm_client = llm_client
        self._analyst_confidence_threshold = analyst_confidence_threshold

    def handle_message(self, message: ACLMessage) -> None:
        """Process analysis requests and send INFORM to planner.

        When llm_client is set: use LLM (prompt + tool descriptions) to select tools and
        parameters, execute via call_tool, run analyze() on gathered data, then send INFORM.
        If select_tools returns empty or fails, fall back to content-based flow (structured_data, market_data from message).
        When llm_client is None: use content-based flow only.

        Args:
            message: The received ACL message; content may include structured_data,
                market_data, documents, graph, and query (decomposed from planner).
        """
        content = message.content or {}
        query = content.get("query") or ""
        conversation_id = getattr(message, "conversation_id", "") or ""
        if not isinstance(conversation_id, str):
            conversation_id = str(conversation_id) if conversation_id else ""
        interaction_log.set_conversation_id(conversation_id)
        interaction_log.log_call(
            "agents.analyst_agent.AnalystAgent.handle_message",
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

        def _inject_resolved_symbol(base: dict) -> dict:
            out = dict(base) if isinstance(base, dict) else {"data": base}
            sr = content.get("symbol_resolution")
            if isinstance(sr, dict) and sr.get("status") == "resolved":
                lst = sr.get("listings") or []
                if lst and isinstance(lst[0], dict):
                    sym = lst[0].get("symbol_yahoo") or lst[0].get("symbol_compact")
                    if isinstance(sym, str) and sym.strip():
                        out["resolved_symbol"] = sym.strip()
            return out

        if self._llm_client is not None:
            from llm.prompts import ANALYST_TOOL_SELECTION
            from openfund_mcp.tools.registry_metadata import (
                ANALYST_ALLOWED_TOOL_NAMES,
                filter_tool_calls_to_allowed,
                get_analyst_tool_descriptions,
                normalize_tool_calls,
            )

            registered = (
                set(self.mcp_client.get_registered_tool_names())
                if self.mcp_client
                else None
            )
            allowed = (
                frozenset(ANALYST_ALLOWED_TOOL_NAMES & registered)
                if registered is not None
                else ANALYST_ALLOWED_TOOL_NAMES
            )
            tool_descriptions = get_analyst_tool_descriptions(registered)
            lock = resolved_symbol_from_planner(content.get("symbol_resolution"))
            lock_line = (
                f"\nPlanner resolved symbol (use this for all analyst market calls): {lock}\n"
                if lock
                else ""
            )
            user_content = f"Sub-query from planner: {query}{lock_line}"
            tool_calls = self._llm_client.select_tools(
                ANALYST_TOOL_SELECTION, user_content, tool_descriptions
            )
            tool_calls = filter_tool_calls_to_allowed(tool_calls, allowed)
            tool_calls = normalize_tool_calls(tool_calls)
            tool_calls = apply_resolved_symbol_to_analyst_calls(
                tool_calls, content.get("symbol_resolution")
            )
            if tool_calls:
                gathered = self._execute_tool_calls_analyst(tool_calls)
                if gathered is not None:
                    structured_data = (
                        content.get("structured_data")
                        or content.get("documents")
                        or content.get("graph")
                        or {}
                    )
                    market_data = (
                        content.get("market_data") or content.get("market") or {}
                    )
                    if not isinstance(structured_data, dict):
                        structured_data = {"data": structured_data}
                    if not isinstance(market_data, dict):
                        market_data = {"data": market_data}
                    structured_data = _inject_resolved_symbol(dict(structured_data))
                    structured_data["tool_results"] = gathered
                    result = self.analyze(structured_data, market_data)
                    if self._llm_client is not None:
                        from llm.prompts import ANALYST_SYSTEM, get_analyst_user_content

                        user_content_summary = get_analyst_user_content(
                            structured_data, market_data
                        )
                        summary = self._llm_client.complete(
                            ANALYST_SYSTEM, user_content_summary
                        )
                        if isinstance(result, dict):
                            result = dict(result)
                            result["summary"] = summary
                        else:
                            result = {"analysis": result, "summary": summary}
                    self._send_inform_analyst(message, result, conversation_id)
                    interaction_log.log_call(
                        "agents.analyst_agent.AnalystAgent.handle_message",
                        result={
                            "INFORM": "sent to planner",
                            "via": "LLM tool selection",
                        },
                    )
                    return
        structured_data = (
            content.get("structured_data")
            or content.get("documents")
            or content.get("graph")
            or {}
        )
        market_data = content.get("market_data") or content.get("market") or {}
        if not isinstance(structured_data, dict):
            structured_data = {"data": structured_data}
        if not isinstance(market_data, dict):
            market_data = {"data": market_data}
        structured_data = _inject_resolved_symbol(dict(structured_data))
        if self.conversation_manager and conversation_id:
            self.conversation_manager.append_flow(
                conversation_id,
                {
                    "step": "analyst_start",
                    "message": "**Analyst** received request. Running quantitative analysis on the gathered data.",
                    "detail": {},
                },
            )
        result = self.analyze(structured_data, market_data)
        if self._llm_client is not None:
            from llm.prompts import ANALYST_SYSTEM, get_analyst_user_content

            user_content = get_analyst_user_content(structured_data, market_data)
            summary = self._llm_client.complete(ANALYST_SYSTEM, user_content)
            if isinstance(result, dict):
                result = dict(result)
                result["summary"] = summary
            else:
                result = {"analysis": result, "summary": summary}
        # Keep one INFORM path so payload shape stays identical across branches.
        self._send_inform_analyst(message, result, conversation_id)

    def _execute_tool_calls_analyst(self, tool_calls: list) -> Optional[list]:
        """Execute analyst tool calls; return list of result dicts or None if no mcp_client."""
        if not self.mcp_client or not tool_calls:
            return None
        gathered = []
        for tc in tool_calls:
            tool = tc.get("tool", "")
            payload = tc.get("payload") or {}
            if not isinstance(tool, str) or not tool.strip():
                continue
            if (
                tool == "analyst_tool.get_indicators"
                and alpha_vantage_cooldown_active()
            ):
                gathered.append(
                    {
                        "error": "analyst_tool.get_indicators skipped: Alpha Vantage cooldown active (batch skip for this turn)."
                    }
                )
                break
            result = self.mcp_client.call_tool(tool, payload)
            if isinstance(result, dict):
                gathered.append(result)
                if tool == "analyst_tool.get_indicators" and tool_error_is_av_cooldown(
                    result
                ):
                    break
            else:
                gathered.append({"content": str(result)})
        return gathered if gathered else None

    def _send_inform_analyst(
        self, message: ACLMessage, result: dict, conversation_id: str
    ) -> None:
        """Send INFORM to reply_to with analysis result and append flow event."""
        reply_to = getattr(message, "reply_to", None) or message.sender
        reply = ACLMessage(
            performative=Performative.INFORM,
            sender=self.name,
            receiver=reply_to,
            content={"analysis": result, "conversation_id": message.conversation_id},
            conversation_id=message.conversation_id,
            reply_to=message.sender,
        )
        self.bus.send(reply)
        interaction_log.log_call(
            "agents.analyst_agent.AnalystAgent.handle_message",
            result={"INFORM": "sent to planner"},
        )
        if self.conversation_manager and conversation_id:
            conf = result.get("confidence")
            self.conversation_manager.append_flow(
                conversation_id,
                {
                    "step": "analyst_done",
                    "message": f"**Analyst** has returned analysis (confidence={conf}).",
                    "detail": {"confidence": conf},
                },
            )
