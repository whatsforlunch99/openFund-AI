"""Web Searcher agent: real-time market and regulatory data via MCP (Tavily, Yahoo)."""

import logging
from typing import TYPE_CHECKING, Any

from a2a.acl_message import ACLMessage, Performative
from a2a.message_bus import MessageBus
from agents.base_agent import BaseAgent
from util.trace_log import trace

if TYPE_CHECKING:
    from llm.base import LLMClient

logger = logging.getLogger(__name__)


class WebSearcherAgent(BaseAgent):
    """
    Fetches real-time market and regulatory information.

    Uses MCP market_tool (Tavily + Yahoo APIs). All returned data
    must include a timestamp.
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
        """Process market/sentiment/regulatory requests and send INFORM to planner.

        Fetches market_data, sentiment, and regulatory via market_tool; assembles
        reply_content and sends INFORM to reply_to (Planner).

        Args:
            message: The received ACL message; content may include fund, symbol, query.
        """
        if not self.mcp_client:
            return
        content = message.content or {}
        fund = (
            content.get("fund")
            or content.get("symbol")
            or content.get("query")
            or "AAPL"
        )
        conversation_id = getattr(message, "conversation_id", "") or ""
        trace(
            10,
            "websearcher_request_received",
            in_={"conversation_id": conversation_id, "fund": fund},
            out="ok",
            next_="fetch market, sentiment, regulatory",
        )
        if self.conversation_manager and conversation_id:
            self.conversation_manager.append_flow(
                conversation_id,
                {
                    "step": "websearcher_start",
                    "message": f'**Web Searcher** received request: fund="{fund}" (from your query). Fetching market data, news, and sentiment.',
                    "detail": {"symbol_or_fund": fund},
                },
            )
        market = self.fetch_market_data(fund)
        sentiment = self.fetch_sentiment(fund)
        regulatory = self.fetch_regulatory(fund)
        reply_content: dict[str, Any] = {
            "market_data": market,
            "sentiment": sentiment,
            "regulatory": regulatory,
        }
        # Optional LLM summary for the planner
        if self._llm_client is not None:
            from llm.prompts import WEBSEARCHER_SYSTEM, get_websearcher_user_content

            query = content.get("query") or fund
            user_content = get_websearcher_user_content(str(query)[:500], reply_content)
            summary = self._llm_client.complete(WEBSEARCHER_SYSTEM, user_content)
            reply_content = dict(reply_content)
            reply_content["summary"] = summary
        reply_to = getattr(message, "reply_to", None) or message.sender
        reply = ACLMessage(
            performative=Performative.INFORM,
            sender=self.name,
            receiver=reply_to,
            content=reply_content,
            conversation_id=message.conversation_id,
            reply_to=message.sender,
        )
        self.bus.send(reply)
        trace(
            10,
            "websearcher_inform_sent",
            in_={"conversation_id": conversation_id},
            out="sent",
            next_="planner receives",
        )
        if self.conversation_manager and conversation_id:
            self.conversation_manager.append_flow(
                conversation_id,
                {
                    "step": "websearcher_done",
                    "message": "**Web Searcher** has returned market data, sentiment, and regulatory news.",
                    "detail": {},
                },
            )

    def fetch_market_data(self, fund: str) -> dict:
        """
        Retrieve live market metrics via MCP market_tool.

        Args:
            fund: Fund or symbol identifier.

        Returns:
            Market data payload; must include 'timestamp'.
        """
        if not self.mcp_client:
            return {"error": "No MCP client", "timestamp": ""}
        result = self.mcp_client.call_tool(
            "market_tool.get_fundamentals_yf",
            {"ticker": fund, "symbol": fund},
        )
        if isinstance(result, dict) and "error" not in result:
            result.setdefault("timestamp", result.get("timestamp", ""))
        return (
            result
            if isinstance(result, dict)
            else {"content": str(result), "timestamp": ""}
        )

    def fetch_sentiment(self, symbol_or_fund: str) -> dict:
        """
        Retrieve social/regulatory sentiment via MCP (e.g. Tavily).

        Args:
            symbol_or_fund: Symbol or fund identifier.

        Returns:
            Sentiment payload; must include 'timestamp'.
        """
        if not self.mcp_client:
            return {"error": "No MCP client", "timestamp": ""}
        result = self.mcp_client.call_tool(
            "market_tool.get_news_yf",
            {"symbol": symbol_or_fund, "limit": 3},
        )
        if isinstance(result, dict) and "error" not in result:
            result.setdefault("timestamp", result.get("timestamp", ""))
        return (
            result
            if isinstance(result, dict)
            else {"content": str(result), "timestamp": ""}
        )

    def fetch_regulatory(self, fund: str) -> dict:
        """
        Retrieve regulatory disclosures for a fund.

        Args:
            fund: Fund identifier.

        Returns:
            Regulatory data; must include 'timestamp'.
        """
        if not self.mcp_client:
            return {"error": "No MCP client", "timestamp": ""}
        # Stub: use global news as placeholder for regulatory
        result = self.mcp_client.call_tool(
            "market_tool.get_global_news_yf",
            {"as_of_date": "", "limit": 2},
        )
        if isinstance(result, dict) and "error" not in result:
            result.setdefault("timestamp", result.get("timestamp", ""))
        return (
            result
            if isinstance(result, dict)
            else {"content": str(result), "timestamp": ""}
        )
