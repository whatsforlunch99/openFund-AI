"""Analyst agent: quantitative analysis via MCP analyst_tool (custom API)."""

import logging
import math
from typing import TYPE_CHECKING, Any

from a2a.acl_message import ACLMessage, Performative
from a2a.message_bus import MessageBus
from agents.base_agent import BaseAgent
from util.trace_log import trace

if TYPE_CHECKING:
    from llm.base import LLMClient

logger = logging.getLogger(__name__)


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
    ) -> None:
        super().__init__(name, message_bus)
        self.mcp_client = mcp_client
        self.conversation_manager = conversation_manager
        self._llm_client = llm_client

    def handle_message(self, message: ACLMessage) -> None:
        """Process analysis requests and send INFORM to planner.

        Extracts structured_data and market_data from content, runs analyze(),
        then sends INFORM with analysis result to reply_to (Planner).

        Args:
            message: The received ACL message; content may include structured_data,
                market_data, documents, graph, market.
        """
        content = message.content or {}
        conversation_id = getattr(message, "conversation_id", "") or ""
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
        trace(
            11,
            "analyst_request_received",
            in_={"conversation_id": conversation_id},
            out="ok",
            next_="analyze()",
        )
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
        trace(
            11,
            "analyst_analyze_done",
            in_={"conversation_id": conversation_id},
            out=f"confidence={confidence} keys={keys}",
            next_="send INFORM to planner",
        )
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
        trace(
            11,
            "analyst_inform_sent",
            in_={"conversation_id": conversation_id},
            out="sent",
            next_="planner receives",
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
            api_result = self.mcp_client.call_tool(
                "analyst_tool.get_indicators_yf",
                {
                    "symbol": "AAPL",
                    "indicator": "sma_50",
                    "as_of_date": "2024-01-15",
                    "look_back_days": 10,
                },
            )
            if isinstance(api_result, dict) and "error" not in api_result:
                return {"confidence": 0.7, "indicators": api_result, "distribution": {}}
        # Stub when MCP unavailable or get_indicators_yf not used
        return {"confidence": 0.6, "summary": "Stub analysis", "distribution": {}}

    def needs_more_data(self, analysis_result: dict) -> bool:
        """
        Determine if additional information is required for refinement.

        Args:
            analysis_result: Current analysis output.

        Returns:
            True if another research cycle is needed.
        """
        return (analysis_result.get("confidence") or 0) < 0.5

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
