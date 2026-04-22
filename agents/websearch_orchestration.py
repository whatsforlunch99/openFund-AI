"""Websearch message orchestration and public fetch APIs."""

import logging
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

from a2a.acl_message import ACLMessage, Performative
from agents.websearch_constants import AUTHORITATIVE_ALLOWLIST, SOURCE_REGISTRY
from agents.websearch_helpers import prefer_yahoo_price_first, websearch_now_iso
from util import interaction_log

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class WebSearchOrchestrationMixin:
    """Split part for readability."""

    def _merge_financial_results(
        self,
        all_results: dict[str, dict],
        symbols: list[str],
        static_by_sym: dict[str, dict],
        symbol_resolution: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Merge per-symbol results into normalized_fund + market_data/sentiment/regulatory."""
        normalized: list[dict] = []
        market_data: dict[str, Any] = {}
        sentiment: dict[str, Any] = {}
        regulatory: dict[str, Any] = {}

        # Keep first available side-channel payloads while normalizing all symbols.
        for sym in symbols[:3]:
            data = all_results.get(sym, {})
            st = static_by_sym.get(sym, {})
            rec = self._normalise_to_schema(
                symbol=sym,
                name=st.get("name", ""),
                asset_class=st.get("asset_class"),
                static=st,
                stooq=data.get("stooq", {}),
                etfdb=data.get("etfdb", {}),
                yahoo=data.get("yahoo"),
                prefer_yahoo_for_price=prefer_yahoo_price_first(symbol_resolution, sym),
            )
            normalized.append(rec)
            if not market_data and data.get("market_data"):
                market_data = data["market_data"]
            if not sentiment and data.get("sentiment"):
                sentiment = data["sentiment"]
            if not regulatory and data.get("regulatory"):
                regulatory = data["regulatory"]
        market_data = market_data or {"timestamp": websearch_now_iso()}
        sentiment = sentiment or {"timestamp": websearch_now_iso()}
        regulatory = regulatory or {"timestamp": websearch_now_iso()}
        return {
            "normalized_fund": normalized,
            "market_data": market_data,
            "sentiment": sentiment,
            "regulatory": regulatory,
        }

    def handle_message(self, message: ACLMessage) -> None:
        """Process REQUEST from Planner: run Financial Data Search and News Search in parallel, merge, send INFORM.

        Always uses _run_parallel_flow (all sources in parallel). When llm_client is set: LLM summary,
        price conflict resolution, and all-tools-fail / news fallback may call the LLM.

        Args:
            message: REQUEST with content: query, optional fund/symbol (decomposed from planner).
        """
        if not self.mcp_client:
            return
        content = message.content or {}
        raw_fund = (
            content.get("fund")
            or content.get("symbol")
            or content.get("query")
            or "AAPL"
        )
        fund = self._normalize_symbol(str(raw_fund))
        conversation_id = getattr(message, "conversation_id", "") or ""
        if not isinstance(conversation_id, str):
            conversation_id = str(conversation_id) if conversation_id else ""
        interaction_log.set_conversation_id(conversation_id)
        interaction_log.log_call(
            "agents.websearch_agent.WebSearcherAgent.handle_message",
            params={
                "performative": getattr(
                    message.performative, "value", str(message.performative)
                ),
                "sender": message.sender,
                "content_keys": list(content.keys()) if content else [],
                "conversation_id": conversation_id,
            },
        )
        if message.performative == Performative.REQUEST:
            logger.info("--- WebSearcher ---")
            logger.info("agent.websearcher.start")

        # Record a user-visible flow event before heavy retrieval starts.
        query = content.get("query") or fund
        if self.conversation_manager and conversation_id:
            self.conversation_manager.append_flow(
                conversation_id,
                {
                    "step": "websearcher_start",
                    "message": f'**Web Searcher** received request: fund="{fund}". Querying all sources in parallel.',
                    "detail": {"symbol_or_fund": fund},
                },
            )
        reply_content = self._run_parallel_flow(content)

        # Fall back to LLM data synthesis only when all providers failed.
        if self._llm_client and self._all_tools_failed(reply_content):
            query = content.get("query") or fund
            primary = (reply_content.get("normalized_fund") or [{}])[0]
            symbol = primary.get("symbol", fund) if isinstance(primary, dict) else fund
            reply_content = self._llm_data_search_fallback(str(query)[:500], symbol)
            logger.info("agent.websearcher.llm_fallback symbol=%s", symbol)
        if self._llm_client:
            nf = reply_content.get("normalized_fund") or []

            # Resolve cross-source price conflicts before generating summary text.
            for rec in nf if isinstance(nf, list) else []:
                if not isinstance(rec, dict) or not self._has_price_conflict(rec):
                    continue
                symbol = rec.get("symbol") or "?"
                pr = rec.get("price")
                py = rec.get("price_yahoo")
                if pr is not None and py is not None:
                    try:
                        res = self._resolve_conflict_with_llm(
                            symbol, float(pr), float(py)
                        )
                        rec["price"] = res["chosen_value"]
                        rec["source"] = dict(rec.get("source") or {})
                        rec["source"]["price"] = res["chosen_source"]
                        rec["conflict_resolution"] = {
                            "chosen_source": res["chosen_source"],
                            "chosen_value": res["chosen_value"],
                            "reason": res["reason"],
                        }
                        logger.info(
                            "agent.websearcher.conflict_resolved symbol=%s chosen=%s",
                            symbol,
                            res["chosen_source"],
                        )
                    except (TypeError, ValueError) as e:
                        logger.debug("Conflict resolution failed for %s: %s", symbol, e)
        fallback = self._fallback_summary_from_normalized(
            reply_content.get("normalized_fund")
        )
        reply_content = dict(reply_content)

        # Prefer deterministic fallback summary when LLM summary is missing/noisy.
        if reply_content.get("llm_fallback"):
            nf = reply_content.get("normalized_fund") or []
            first = nf[0] if nf and isinstance(nf[0], dict) else {}
            reply_content["summary"] = first.get("llm_fallback_content", fallback)
        elif self._llm_client is not None:
            from llm.prompts import WEBSEARCHER_SYSTEM, get_websearcher_user_content

            query = content.get("query") or fund
            user_content = get_websearcher_user_content(str(query)[:500], reply_content)
            summary = self._llm_client.complete(WEBSEARCHER_SYSTEM, user_content)
            if (
                not summary
                or summary == user_content
                or (len(summary) > 3000 and "query:" in summary[:100])
            ):
                summary = fallback
            reply_content["summary"] = summary or fallback
        else:
            reply_content["summary"] = fallback
        if isinstance(reply_content, dict):
            reply_content = self._augment_websearch_contract(reply_content)

        # Report coarse status for monitoring without changing response contract.
        has_errors = any(
            isinstance(reply_content.get(k), dict) and reply_content.get(k).get("error")
            for k in ("market_data", "sentiment", "regulatory")
            if reply_content.get(k)
        )
        status = "limited_data" if has_errors else "success"
        logger.info("agent.websearcher.done status=%s", status)
        reply_to = getattr(message, "reply_to", None) or message.sender
        reply_content["query"] = content.get("query") or ""
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
            "market_tool.get_fundamentals", {"ticker": fund, "symbol": fund}
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
        end_date = date.today().isoformat()
        start_date = (date.today() - timedelta(days=7)).isoformat()
        result = self.mcp_client.call_tool(
            "market_tool.get_news",
            {
                "symbol": self._normalize_symbol(symbol_or_fund),
                "limit": 3,
                "start_date": start_date,
                "end_date": end_date,
            },
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
        as_of = date.today().isoformat()
        result = self.mcp_client.call_tool(
            "market_tool.get_global_news",
            {"as_of_date": as_of, "look_back_days": 7, "limit": 2},
        )
        if isinstance(result, dict) and "error" not in result:
            result.setdefault("timestamp", result.get("timestamp", ""))
        return (
            result
            if isinstance(result, dict)
            else {"content": str(result), "timestamp": ""}
        )
