"""Web Searcher agent: real-time market and regulatory data via MCP (Tavily, Yahoo)."""

import logging
from typing import TYPE_CHECKING, Any, Optional

from a2a.acl_message import ACLMessage, Performative
from a2a.message_bus import MessageBus
from agents.base_agent import BaseAgent
from util.trace_log import trace
from util import interaction_log

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

        When llm_client is set: use LLM (prompt + tool descriptions) to select tools and
        parameters, execute via call_tool, then send INFORM with timestamp. If select_tools
        returns empty or fails, fall back to fetch_market_data/fetch_sentiment/fetch_regulatory.
        When llm_client is None: use content-based dispatch only.

        Args:
            message: The received ACL message; content may include fund, symbol, query (decomposed from planner).
        """
        if not self.mcp_client:
            return
        content = message.content or {}
        fund = content.get("fund") or content.get("symbol") or content.get("query") or "AAPL"
        conversation_id = getattr(message, "conversation_id", "") or ""
        if not isinstance(conversation_id, str):
            conversation_id = str(conversation_id) if conversation_id else ""
        interaction_log.set_conversation_id(conversation_id)
        interaction_log.log_call(
            "agents.websearch_agent.WebSearcherAgent.handle_message",
            params={
                "performative": getattr(message.performative, "value", str(message.performative)),
                "sender": message.sender,
                "content_keys": list(content.keys()) if content else [],
                "conversation_id": conversation_id,
            },
        )
        query = content.get("query") or fund

        # When LLM is available, try tool selection first; fall back to content-based dispatch if empty/fail
        if self._llm_client is not None:
            from llm.prompts import WEBSEARCHER_TOOL_SELECTION
            from llm.tool_descriptions import (
                WEBSEARCHER_ALLOWED_TOOL_NAMES,
                filter_tool_calls_to_allowed,
                get_websearcher_tool_descriptions,
                normalize_tool_calls,
            )

            tool_descriptions = get_websearcher_tool_descriptions()
            user_content = f"Sub-query from planner: {query}"
            tool_calls = self._llm_client.select_tools(
                WEBSEARCHER_TOOL_SELECTION, user_content, tool_descriptions
            )
            # Discard any tool the LLM returned that is not in this agent's allowed pool
            tool_calls = filter_tool_calls_to_allowed(tool_calls, WEBSEARCHER_ALLOWED_TOOL_NAMES)
            tool_calls = normalize_tool_calls(tool_calls)
            if tool_calls:
                reply_content = self._execute_tool_calls_web(tool_calls)
                if reply_content:
                    if self._llm_client is not None:
                        from llm.prompts import WEBSEARCHER_SYSTEM, get_websearcher_user_content
                        user_content_summary = get_websearcher_user_content(str(query)[:500], reply_content)
                        summary = self._llm_client.complete(WEBSEARCHER_SYSTEM, user_content_summary)
                        reply_content = dict(reply_content)
                        reply_content["summary"] = summary
                    self._ensure_timestamp(reply_content)
                    self._send_inform_web(message, reply_content, conversation_id)
                    interaction_log.log_call(
                        "agents.websearch_agent.WebSearcherAgent.handle_message",
                        result={"INFORM": "sent to planner", "via": "LLM tool selection"},
                    )
                    return
        # Fallback: content-based dispatch
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
        interaction_log.log_call(
            "agents.websearch_agent.WebSearcherAgent.handle_message",
            result={"INFORM": "sent to planner"},
        )
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

    def _execute_tool_calls_web(self, tool_calls: list) -> Optional[dict[str, Any]]:
        """Execute tool calls and merge into market_data, sentiment, regulatory. Returns None if no calls."""
        if not tool_calls:
            return None
        market_data = None
        sentiment = None
        regulatory = None
        for tc in tool_calls:
            tool = tc.get("tool", "")
            payload = tc.get("payload") or {}
            if not isinstance(tool, str) or not tool.strip():
                continue
            result = self.mcp_client.call_tool(tool, payload)
            if isinstance(result, dict) and "error" not in result:
                result.setdefault("timestamp", result.get("timestamp", ""))
            if "get_fundamentals" in tool or "get_stock_data" in tool or "get_balance_sheet" in tool or "get_income_statement" in tool or "get_insider" in tool or "get_ticker" in tool or "get_stock_analytics" in tool:
                market_data = result if isinstance(result, dict) else {"content": str(result), "timestamp": ""}
            elif "get_news" in tool and "global" not in tool.lower():
                sentiment = result if isinstance(result, dict) else {"content": str(result), "timestamp": ""}
            elif "get_global_news" in tool or "regulatory" in tool.lower():
                regulatory = result if isinstance(result, dict) else {"content": str(result), "timestamp": ""}
        out: dict[str, Any] = {
            "market_data": market_data or {"timestamp": ""},
            "sentiment": sentiment or {"timestamp": ""},
            "regulatory": regulatory or {"timestamp": ""},
        }
        return out

    def _ensure_timestamp(self, reply_content: dict[str, Any]) -> None:
        """Ensure top-level or nested content has timestamp."""
        for k in ("market_data", "sentiment", "regulatory"):
            v = reply_content.get(k)
            if isinstance(v, dict) and "timestamp" not in v:
                v["timestamp"] = ""

    def _send_inform_web(self, message: ACLMessage, reply_content: dict[str, Any], conversation_id: str) -> None:
        """Send INFORM to reply_to and append flow event."""
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
        interaction_log.log_call(
            "agents.websearch_agent.WebSearcherAgent.handle_message",
            result={"INFORM": "sent to planner"},
        )
        trace(10, "websearcher_inform_sent", in_={"conversation_id": conversation_id}, out="sent", next_="planner receives")
        if self.conversation_manager and conversation_id:
            self.conversation_manager.append_flow(
                conversation_id,
                {"step": "websearcher_done", "message": "**Web Searcher** has returned market data, sentiment, and regulatory news.", "detail": {}},
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
            "market_tool.get_fundamentals",
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
            "market_tool.get_news",
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
            "market_tool.get_global_news",
            {"as_of_date": "", "limit": 2},
        )
        if isinstance(result, dict) and "error" not in result:
            result.setdefault("timestamp", result.get("timestamp", ""))
        return (
            result
            if isinstance(result, dict)
            else {"content": str(result), "timestamp": ""}
        )
