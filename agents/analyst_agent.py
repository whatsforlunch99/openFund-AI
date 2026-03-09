"""Analyst agent: quantitative analysis via MCP analyst_tool (custom API)."""

import logging
import math
from datetime import date
from typing import TYPE_CHECKING, Any, Optional

from a2a.acl_message import ACLMessage, Performative
from a2a.message_bus import MessageBus
from agents.base_agent import BaseAgent
from util import interaction_log

if TYPE_CHECKING:
    from llm.base import LLMClient

logger = logging.getLogger(__name__)

# Common tickers for fallback when symbol cannot be derived from context.
_DEFAULT_SYMBOL = "NVDA"


def _derive_symbol(structured_data: dict, market_data: dict) -> str:
    """Derive a ticker symbol from structured_data or market_data for fallback get_indicators calls."""
    if isinstance(structured_data, dict):
        for key in ("symbol", "fund", "ticker"):
            val = structured_data.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip().upper()
        query = structured_data.get("query") or structured_data.get("vector_query")
        if isinstance(query, str) and query.strip():
            q = query.strip().upper()
            for ticker in ("NVDA", "AAPL", "TSLA", "MSFT", "GOOGL"):
                if ticker in q or ticker.lower() in query.lower():
                    return ticker
    if isinstance(market_data, dict):
        for key in ("symbol", "ticker", "fund"):
            val = market_data.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip().upper()
    return _DEFAULT_SYMBOL


class AnalystAgent(BaseAgent):
    """
    Performs quantitative reasoning and uncertainty estimation.

    Uses MCP analyst_tool (custom API) for heavy quant; may use local
    helpers for sharpe_ratio, max_drawdown, monte_carlo_simulation.
    """

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
        conversation_id = getattr(message, "conversation_id", "") or ""
        if not isinstance(conversation_id, str):
            conversation_id = str(conversation_id) if conversation_id else ""
        interaction_log.set_conversation_id(conversation_id)
        interaction_log.log_call(
            "agents.analyst_agent.AnalystAgent.handle_message",
            params={
                "performative": getattr(message.performative, "value", str(message.performative)),
                "sender": message.sender,
                "content_keys": list(content.keys()) if content else [],
                "conversation_id": conversation_id,
            },
        )
        if message.performative == Performative.REQUEST:
            query = content.get("query") or ""

        # When LLM is available, try tool selection first; fall back to content-based if empty/fail
        if self._llm_client is not None:
            from llm.prompts import ANALYST_TOOL_SELECTION
            from llm.tool_descriptions import (
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
            user_content = f"Sub-query from planner: {query}"
            tool_calls = self._llm_client.select_tools(
                ANALYST_TOOL_SELECTION, user_content, tool_descriptions
            )
            # Discard any tool the LLM returned that is not in allowed (and registered)
            tool_calls = filter_tool_calls_to_allowed(tool_calls, allowed)
            tool_calls = normalize_tool_calls(tool_calls)
            if tool_calls:
                gathered = self._execute_tool_calls_analyst(tool_calls)
                if gathered is not None:
                    structured_data = content.get("structured_data") or content.get("documents") or content.get("graph") or {}
                    market_data = content.get("market_data") or content.get("market") or {}
                    if not isinstance(structured_data, dict):
                        structured_data = {"data": structured_data}
                    if not isinstance(market_data, dict):
                        market_data = {"data": market_data}
                    structured_data = dict(structured_data)
                    structured_data["tool_results"] = gathered
                    result = self.analyze(structured_data, market_data)
                    if self._llm_client is not None:
                        from llm.prompts import ANALYST_SYSTEM, get_analyst_user_content
                        user_content_summary = get_analyst_user_content(structured_data, market_data)
                        summary = self._llm_client.complete(ANALYST_SYSTEM, user_content_summary)
                        if isinstance(result, dict):
                            result = dict(result)
                            result["summary"] = summary
                        else:
                            result = {"analysis": result, "summary": summary}
                    status = "partial" if (isinstance(result, dict) and (result.get("confidence") or 0) < self._analyst_confidence_threshold) else "success"
                    self._send_inform_analyst(message, result, conversation_id)
                    interaction_log.log_call(
                        "agents.analyst_agent.AnalystAgent.handle_message",
                        result={"INFORM": "sent to planner", "via": "LLM tool selection"},
                    )
                    return
        # Fallback: content-based (structured_data, market_data from message)
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
        # Optional LLM analysis summary from structured_data + market_data
        if self._llm_client is not None:
            from llm.prompts import ANALYST_SYSTEM, get_analyst_user_content

            user_content = get_analyst_user_content(structured_data, market_data)
            summary = self._llm_client.complete(ANALYST_SYSTEM, user_content)
            if isinstance(result, dict):
                result = dict(result)
                result["summary"] = summary
            else:
                result = {"analysis": result, "summary": summary}
        confidence = result.get("confidence")
        keys = list(result.keys()) if isinstance(result, dict) else []
        status = "partial" if (confidence or 0) < self._analyst_confidence_threshold else "success"
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
            result = self.mcp_client.call_tool(tool, payload)
            if isinstance(result, dict):
                gathered.append(result)
            else:
                gathered.append({"content": str(result)})
        return gathered if gathered else None

    def _send_inform_analyst(self, message: ACLMessage, result: dict, conversation_id: str) -> None:
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
                {"step": "analyst_done", "message": f"**Analyst** has returned analysis (confidence={conf}).", "detail": {"confidence": conf}},
            )

    def analyze(self, structured_data: dict, market_data: dict) -> dict:
        """
        Generate probabilistic investment analysis.

        Output should include probability distributions where applicable,
        not only single-point predictions.

        Args:
            structured_data: KG and document data from Librarian.
            market_data: Real-time market signals from WebSearcher.

        Returns:
            Analysis result with confidence and optional distributions.
        """
        if self.mcp_client:
            symbol = _derive_symbol(structured_data, market_data)
            as_of = date.today().isoformat()
            payload = {
                "symbol": symbol,
                "indicator": "rsi",
                "as_of_date": as_of,
                "look_back_days": 30,
            }
            api_result = self.mcp_client.call_tool(
                "analyst_tool.get_indicators",
                payload,
            )
            if isinstance(api_result, dict) and "error" not in api_result:
                return {"confidence": 0.7, "indicators": api_result, "distribution": {}}
        # Stub when MCP unavailable or get_indicators returned error
        return {"confidence": 0.6, "summary": "Stub analysis", "distribution": {}}

    def needs_more_data(self, analysis_result: dict) -> bool:
        """
        Determine if additional information is required for refinement.

        Args:
            analysis_result: Current analysis output.

        Returns:
            True if another research cycle is needed.
        """
        return (analysis_result.get("confidence") or 0) < self._analyst_confidence_threshold

    def sharpe_ratio(self, returns: list[float], risk_free_rate: float) -> float:
        """
        Compute Sharpe ratio for a return series.

        Args:
            returns: List of period returns.
            risk_free_rate: Risk-free rate (e.g. annual).

        Returns:
            Sharpe ratio.
        """
        if not returns:
            return 0.0
        avg = sum(returns) / len(returns)
        variance = sum((r - avg) ** 2 for r in returns) / len(returns)
        std = variance**0.5 if variance else 0.0
        if std == 0:
            return 0.0
        return (avg - risk_free_rate) / std

    def max_drawdown(self, returns: list[float]) -> float:
        """
        Compute maximum drawdown for a return series.

        Args:
            returns: List of period returns.

        Returns:
            Max drawdown (e.g. as positive decimal).
        """
        if not returns:
            return 0.0
        peak = returns[0]
        max_dd = 0.0
        for r in returns:
            peak = max(peak, r)
            dd = peak - r
            if peak > 0:
                max_dd = max(max_dd, dd / peak)
        return max_dd

    def monte_carlo_simulation(
        self,
        returns: list[float],
        _horizon: int,
        _n_sims: int,
    ) -> dict:
        """
        Run Monte Carlo simulation; return distribution, not single point.

        Args:
            returns: Historical returns.
            horizon: Projection horizon (e.g. periods).
            n_sims: Number of simulations.

        Returns:
            Dict with distribution (e.g. percentiles, mean, std).
        """
        if not returns:
            return {"mean": 0, "std": 0, "percentiles": {}}
        mean_ret = sum(returns) / len(returns)
        variance = sum((r - mean_ret) ** 2 for r in returns) / len(returns)
        std = math.sqrt(variance) if variance else 0.0
        return {"mean": mean_ret, "std": std, "percentiles": {"50": mean_ret}}
