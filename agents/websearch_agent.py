"""Web Searcher agent: real-time market and regulatory data via MCP (Tavily, Yahoo)."""

from typing import Any

from a2a.acl_message import ACLMessage
from a2a.message_bus import MessageBus
from agents.base_agent import BaseAgent


class WebSearcherAgent(BaseAgent):
    """
    Fetches real-time market and regulatory information.

    Uses MCP market_tool (Tavily + Yahoo APIs). All returned data
    must include a timestamp.
    """

    def __init__(
        self, name: str, message_bus: MessageBus, mcp_client: Any = None
    ) -> None:
        super().__init__(name, message_bus)
        self.mcp_client = mcp_client

    def handle_message(self, message: ACLMessage) -> None:
        """
        Process market/sentiment/regulatory requests.

        Args:
            message: The received ACL message.
        """
        raise NotImplementedError

    def fetch_market_data(self, fund: str) -> dict:
        """
        Retrieve live market metrics via MCP market_tool.

        Args:
            fund: Fund or symbol identifier.

        Returns:
            Market data payload; must include 'timestamp'.
        """
        raise NotImplementedError

    def fetch_sentiment(self, symbol_or_fund: str) -> dict:
        """
        Retrieve social/regulatory sentiment via MCP (e.g. Tavily).

        Args:
            symbol_or_fund: Symbol or fund identifier.

        Returns:
            Sentiment payload; must include 'timestamp'.
        """
        raise NotImplementedError

    def fetch_regulatory(self, fund: str) -> dict:
        """
        Retrieve regulatory disclosures for a fund.

        Args:
            fund: Fund identifier.

        Returns:
            Regulatory data; must include 'timestamp'.
        """
        raise NotImplementedError
