"""Analyst agent: quantitative analysis via MCP analyst_tool (custom API)."""

from typing import Any

from agents.base_agent import BaseAgent
from a2a.acl_message import ACLMessage
from a2a.message_bus import MessageBus


class AnalystAgent(BaseAgent):
    """
    Performs quantitative reasoning and uncertainty estimation.

    Uses MCP analyst_tool (custom API) for heavy quant; may use local
    helpers for sharpe_ratio, max_drawdown, monte_carlo_simulation.
    """

    def __init__(self, name: str, message_bus: MessageBus, mcp_client: Any = None) -> None:
        super().__init__(name, message_bus)
        self.mcp_client = mcp_client

    def handle_message(self, message: ACLMessage) -> None:
        """
        Process analysis requests: receive structured_data and market_data,
        call analyze; if needs_more_data send refinement request else
        send result to Responder.

        Args:
            message: The received ACL message.
        """
        raise NotImplementedError

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
        raise NotImplementedError

    def needs_more_data(self, analysis_result: dict) -> bool:
        """
        Determine if additional information is required for refinement.

        Args:
            analysis_result: Current analysis output.

        Returns:
            True if another research cycle is needed.
        """
        raise NotImplementedError

    def sharpe_ratio(self, returns: list, risk_free_rate: float) -> float:
        """
        Compute Sharpe ratio for a return series.

        Args:
            returns: List of period returns.
            risk_free_rate: Risk-free rate (e.g. annual).

        Returns:
            Sharpe ratio.
        """
        raise NotImplementedError

    def max_drawdown(self, returns: list) -> float:
        """
        Compute maximum drawdown for a return series.

        Args:
            returns: List of period returns.

        Returns:
            Max drawdown (e.g. as positive decimal).
        """
        raise NotImplementedError

    def monte_carlo_simulation(
        self,
        returns: list,
        horizon: int,
        n_sims: int,
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
        raise NotImplementedError
