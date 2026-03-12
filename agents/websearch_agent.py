"""Web Searcher agent: real-time market and fund data via MCP.

Queries all data sources in parallel (FinanceDatabase, Stooq, Yahoo, ETFdb,
market_tool, news_tool) per docs/websearcher-design.md and docs/news-searcher-design.md.
Outputs normalized_fund, market_data/sentiment/regulatory, and news/citations.
"""

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Optional

from a2a.acl_message import ACLMessage, Performative
from a2a.message_bus import MessageBus
from agents.base_agent import BaseAgent
from util import interaction_log

if TYPE_CHECKING:
    from llm.base import LLMClient

logger = logging.getLogger(__name__)

# Uppercase words that match [A-Z]{1,5} but are not tickers (English question words, etc.).
# If the planner passes fund="WHAT" from "What is the price of SPY?", we must not query WHAT.US.
_TICKER_BLOCKLIST = frozenset({
    "WHAT", "WHEN", "WHERE", "WHICH", "WHO", "WHOM", "WHOSE", "WHY", "HOW",
    "IS", "ARE", "WAS", "WERE", "BE", "BEEN", "BEING", "HAVE", "HAS", "HAD", "DO", "DOES", "DID",
    "THE", "A", "AN", "AND", "OR", "BUT", "IF", "THEN", "ELSE", "FOR", "TO", "OF", "IN", "ON", "AT",
    "BY", "FROM", "AS", "INTO", "THROUGH", "DURING", "BEFORE", "AFTER", "ABOVE", "BELOW",
    "NOT", "NO", "YES", "ALL", "ANY", "BOTH", "EACH", "FEW", "MORE", "MOST", "OTHER", "SOME", "SUCH",
    "ONLY", "OWN", "SAME", "SO", "THAN", "TOO", "VERY", "CAN", "WILL", "JUST", "SHOULD", "NOW",
    "THERE", "HERE", "THIS", "THAT", "THESE", "THOSE", "WITH", "WITHOUT", "ABOUT", "AGAINST",
    "CURRENT", "RECENT", "LATEST", "PRICE", "NEWS", "STOCK", "FUND", "ETF", "DATA", "INFO",
})


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _extract_price_from_text(text: str) -> Optional[float]:
    """Try to extract a numeric price (e.g. $123.45 or 123.45) from text."""
    if not text or not isinstance(text, str):
        return None
    m = re.search(r"\$?\s*(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)|\$?\s*(\d+\.\d{2})\b", text)
    if not m:
        return None
    raw = (m.group(1) or m.group(2) or "").replace(",", "")
    try:
        return float(raw)
    except ValueError:
        return None


def _summarize_yahoo_fundamental(yahoo_res: Any) -> dict[str, Any]:
    """Build a log-friendly summary of Yahoo result without huge raw payloads."""
    if not isinstance(yahoo_res, dict):
        return {"type": type(yahoo_res).__name__}
    if "error" in yahoo_res:
        return {"error": str(yahoo_res.get("error"))[:500], "timestamp": yahoo_res.get("timestamp")}

    raw = yahoo_res.get("raw")
    raw_modules = []
    if isinstance(raw, dict):
        raw_modules = list(raw.keys())

    holdings_preview = []
    holdings = yahoo_res.get("holdings_top10")
    if isinstance(holdings, list):
        for h in holdings[:3]:
            if isinstance(h, dict):
                holdings_preview.append(
                    {
                        "symbol": h.get("symbol"),
                        "name": h.get("name"),
                        "weight": h.get("weight"),
                    }
                )

    sector_preview = {}
    sector = yahoo_res.get("sector_exposure")
    if isinstance(sector, dict):
        # take first few keys deterministically (sorted)
        for k in sorted(sector.keys())[:5]:
            try:
                sector_preview[str(k)] = float(sector[k]) if sector[k] is not None else None
            except (TypeError, ValueError):
                sector_preview[str(k)] = sector[k]

    return {
        "symbol": yahoo_res.get("symbol"),
        "name": yahoo_res.get("name"),
        "currency": yahoo_res.get("currency"),
        "price": yahoo_res.get("price"),
        "close": yahoo_res.get("close"),
        "expense_ratio": yahoo_res.get("expense_ratio"),
        "aum": yahoo_res.get("aum"),
        "sector_exposure_top": sector_preview,
        "holdings_top_preview": holdings_preview,
        "raw_modules": raw_modules,
        "timestamp": yahoo_res.get("timestamp"),
        "source": yahoo_res.get("source"),
    }


class WebSearcherAgent(BaseAgent):
    """
    Fetches real-time market and fund information.

    Queries all sources in parallel: fund_catalog, stooq, Yahoo, ETFdb,
    market_tool; merges all results and returns to Planner.
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

    def _normalize_symbol(self, raw: str) -> str:
        """Best-effort ticker extraction for free-form planner query text."""
        text = (raw or "").strip()
        if not text:
            return "AAPL"
        upper = text.upper()
        # Prefer known multi-letter tickers mentioned in text (avoid WHAT, IS, etc.).
        for sym in ("SPY", "QQQ", "IWM", "DIA", "VTI", "VOO", "NVDA", "AAPL", "MSFT", "GOOGL", "TSLA", "AMZN", "META"):
            if re.search(r"\b" + re.escape(sym) + r"\b", upper):
                return sym
        # Explicit uppercase tokens 1-5 chars — skip English/stopwords that look like tickers.
        tokens = re.findall(r"\b[A-Z]{1,5}\b", upper)
        for t in tokens:
            if t not in _TICKER_BLOCKLIST:
                return t
        known = {
            "nvidia": "NVDA",
            "apple": "AAPL",
            "tesla": "TSLA",
            "microsoft": "MSFT",
            "google": "GOOGL",
            "alphabet": "GOOGL",
            "vanguard": "VTI",
            "spy": "SPY",
            "sp500": "SPY",
        }
        lower = text.lower()
        for key, sym in known.items():
            if key in lower:
                return sym
        return "AAPL"

    def _resolve_symbols(self, content: dict) -> tuple[list[str], list[dict]]:
        """Resolve symbol(s) from REQUEST content. Returns (symbols, static_matches).

        If fund/symbol looks like a ticker (1-5 chars), use it.
        Else call fund_catalog_tool.search(query); if matches, use first symbol(s).
        Fallback: _normalize_symbol heuristics.
        """
        query = (content.get("query") or "").strip()
        fund = (content.get("fund") or content.get("symbol") or "").strip()
        fund_upper = fund.upper().split(".")[0] if fund else ""
        # Explicit ticker only if not a blocklisted word (e.g. WHAT from "What is the price of SPY?")
        if (
            fund
            and re.match(r"^[A-Z]{1,5}(\.[A-Z]{2})?$", fund.upper())
            and fund_upper not in _TICKER_BLOCKLIST
        ):
            return [fund_upper], []
        # Blocklisted or empty fund: try catalog + query first
        if fund_upper in _TICKER_BLOCKLIST:
            fund = ""

        # Try fund_catalog
        if self.mcp_client and query:
            try:
                reg = self.mcp_client.get_registered_tool_names() or []
                if "fund_catalog_tool.search" in reg:
                    r = self.mcp_client.call_tool(
                        "fund_catalog_tool.search",
                        {"query": query, "limit": 5},
                    )
                    matches = (r or {}).get("matches") or []
                    if matches:
                        syms = [m["symbol"] for m in matches if m.get("symbol")]
                        return syms[:3], matches
            except Exception:
                pass

        # Fallback heuristic
        raw = query or fund or "AAPL"
        return [self._normalize_symbol(raw)], []

    def _has_price_conflict(self, rec: dict) -> bool:
        """True if stooq and yahoo both have price and differ by >1%."""
        pr = rec.get("price")
        py = rec.get("price_yahoo")
        if pr is None or py is None:
            return False
        try:
            a, b = float(pr), float(py)
            if a <= 0 or b <= 0:
                return False
            rel_diff = abs(a - b) / min(a, b)
            return rel_diff > 0.01
        except (TypeError, ValueError):
            return False

    def _resolve_conflict_with_llm(self, symbol: str, price_stooq: float, price_yahoo: float) -> dict[str, Any]:
        """Ask LLM which source is more credible; return chosen_source, chosen_value, reason."""
        import json

        from llm.prompts import WEBSEARCHER_CONFLICT_RESOLUTION_SYSTEM

        conflict = {
            "symbol": symbol,
            "stooq": {"price": price_stooq, "source": "stooq"},
            "yahoo": {"price": price_yahoo, "source": "yahoo"},
        }
        user_content = f"Conflicting data:\n{json.dumps(conflict, indent=2)}"
        out = self._llm_client.complete(WEBSEARCHER_CONFLICT_RESOLUTION_SYSTEM, user_content) or ""
        chosen_source = "stooq"
        chosen_value = price_stooq
        reason = "LLM parse failed; defaulting to stooq."
        for line in out.strip().split("\n"):
            line = line.strip().upper()
            if line.startswith("CHOSEN:"):
                if "YAHOO" in line:
                    chosen_source = "yahoo"
                    chosen_value = price_yahoo
                else:
                    chosen_source = "stooq"
                    chosen_value = price_stooq
            elif line.startswith("VALUE:"):
                try:
                    v = float(line.split(":", 1)[1].strip().replace(",", ""))
                    chosen_value = v
                except (ValueError, IndexError):
                    pass
            elif line.startswith("REASON:"):
                reason = line.split(":", 1)[1].strip() if ":" in line else ""
        return {
            "chosen_source": chosen_source,
            "chosen_value": chosen_value,
            "reason": reason,
        }

    def _all_tools_failed(self, reply_content: dict) -> bool:
        """True when no tool returned usable data: no price in normalized_fund and no useful market/sentiment/regulatory."""
        nf = reply_content.get("normalized_fund") or []
        for rec in nf if isinstance(nf, list) else []:
            if isinstance(rec, dict) and (rec.get("price") is not None or rec.get("price_yahoo") is not None or rec.get("llm_fallback_content")):
                return False
        for k in ("market_data", "sentiment", "regulatory"):
            v = reply_content.get(k)
            if isinstance(v, dict) and not v.get("error"):
                c = v.get("content") or ""
                if isinstance(c, str) and len(c.strip()) > 20:
                    return False
        return True

    def _llm_data_search_fallback(self, query: str, symbol: str) -> dict[str, Any]:
        """Call LLM to provide data when all tools failed. Returns reply_content shape with source=llm."""
        from llm.prompts import WEBSEARCHER_LLM_FALLBACK_SYSTEM

        user_content = f"Query: {query}\nSymbol/topic: {symbol}"
        out = self._llm_client.complete(WEBSEARCHER_LLM_FALLBACK_SYSTEM, user_content) or ""
        price = _extract_price_from_text(out)
        rec = {
            "symbol": symbol,
            "name": symbol,
            "asset_class": "Equity",
            "expense_ratio": None,
            "aum": None,
            "price": price,
            "sector_exposure": {},
            "holdings_top10": [],
            "source": {"primary": "llm", "price": "llm"},
            "timestamp": _now_iso(),
            "llm_fallback": True,
            "llm_fallback_content": out[:2000] if out else "",
        }
        return {
            "normalized_fund": [rec],
            "market_data": {"timestamp": _now_iso()},
            "sentiment": {"timestamp": _now_iso()},
            "regulatory": {"timestamp": _now_iso()},
            "news": [],
            "citations": {},
            "llm_fallback": True,
        }

    def _fallback_summary_from_normalized(self, nf: Any) -> str:
        """Build concise summary from normalized_fund when LLM summary fails."""
        if not isinstance(nf, list) or not nf:
            return "No fund data from stooq or Yahoo."
        parts = []
        for rec in nf:
            if rec.get("llm_fallback") and rec.get("llm_fallback_content"):
                parts.append(f"{rec.get('symbol', '?')}: [LLM fallback] {rec['llm_fallback_content'][:500]}")
                continue
            if not isinstance(rec, dict):
                continue
            sym = rec.get("symbol") or "?"
            pr = rec.get("price")
            py = rec.get("price_yahoo")
            if pr is not None:
                try:
                    parts.append(f"{sym}: ${float(pr):.2f} (stooq)" if py is None else f"{sym}: ${float(pr):.2f} (stooq), Yahoo ${float(py):.2f}")
                except (TypeError, ValueError):
                    parts.append(f"{sym}: price unavailable")
            elif py is not None:
                try:
                    parts.append(f"{sym}: ${float(py):.2f} (Yahoo)")
                except (TypeError, ValueError):
                    parts.append(f"{sym}: price unavailable")
            else:
                parts.append(f"{sym}: no price (stooq and Yahoo failed)")
        return "; ".join(parts) if parts else "No price data."

    def _fetch_news_sources(
        self, query: str, symbol: str, days: int = 7
    ) -> tuple[list[dict], list[dict], list[dict]]:
        """Fetch news in parallel: RSS, market_tool.get_news, market_tool.get_global_news.
        Returns (rss_items, sentiment_items, regulatory_items) as raw item lists.
        """
        rss_items: list[dict] = []
        sentiment_items: list[dict] = []
        regulatory_items: list[dict] = []
        if not self.mcp_client:
            return (rss_items, sentiment_items, regulatory_items)
        reg = self.mcp_client.get_registered_tool_names() or []
        call = self.mcp_client.call_tool
        tasks: list[tuple[str, str, dict]] = []
        if "news_tool.search_rss" in reg:
            tasks.append(("rss", "news_tool.search_rss", {"query": query, "days": days}))
        if "news_tool.search_yahoo_rss" in reg:
            tasks.append(("rss_yahoo", "news_tool.search_yahoo_rss", {"limit": 15}))
        if "news_tool.search_gdelt" in reg:
            tasks.append(("rss_gdelt", "news_tool.search_gdelt", {"query": query, "limit": 10}))
        today = date.today().isoformat()
        start = (date.today() - timedelta(days=days)).isoformat()
        if "market_tool.get_news" in reg:
            tasks.append(
                ("sentiment", "market_tool.get_news", {"symbol": symbol, "start_date": start, "end_date": today, "limit": 5})
            )
        if "market_tool.get_global_news" in reg:
            tasks.append(
                ("regulatory", "market_tool.get_global_news", {"as_of_date": today, "look_back_days": days, "limit": 5})
            )
        if not tasks:
            return (rss_items, sentiment_items, regulatory_items)
        results: dict[str, Any] = {}
        with ThreadPoolExecutor(max_workers=len(tasks)) as ex:
            futures = {ex.submit(call, tool, payload): key for key, tool, payload in tasks}
            for fut in as_completed(futures):
                key = futures[fut]
                try:
                    r = fut.result() or {}
                    if isinstance(r, dict) and "error" not in r:
                        results[key] = r
                except Exception as e:
                    logger.debug("news fetch %s failed: %s", key, e)
        for key in ("rss", "rss_yahoo", "rss_gdelt"):
            if key in results and "items" in results[key]:
                rss_items.extend(results[key]["items"] or [])
        if "sentiment" in results:
            sentiment_items = self._content_to_news_items(
                results["sentiment"].get("content") or "", "market_tool"
            )
        if "regulatory" in results:
            regulatory_items = self._content_to_news_items(
                results["regulatory"].get("content") or "", "market_tool_global"
            )
        logger.info(
            "agent.websearcher.news_sources rss_count=%s sentiment_count=%s regulatory_count=%s",
            len(rss_items), len(sentiment_items), len(regulatory_items),
        )
        return (rss_items, sentiment_items, regulatory_items)

    def _content_to_news_items(self, content: str, source: str) -> list[dict]:
        """Convert market_tool content to news items. Tries JSON feed; else first line as title."""
        items: list[dict] = []
        if not content or not isinstance(content, str):
            return items
        # Try Alpha Vantage NEWS_SENTIMENT JSON
        try:
            data = json.loads(content)
            feed = data.get("feed") if isinstance(data, dict) else None
            if isinstance(feed, list):
                for entry in feed[:15]:
                    if not isinstance(entry, dict):
                        continue
                    title = (entry.get("title") or "").strip()
                    url = (entry.get("url") or "").strip()
                    summary = (entry.get("summary") or "").strip()[:500]
                    pub = entry.get("time_published") or entry.get("published")
                    date_str = None
                    if pub:
                        if isinstance(pub, str) and len(pub) >= 8:
                            date_str = f"{pub[:4]}-{pub[4:6]}-{pub[6:8]}"
                        else:
                            date_str = str(pub)[:10]
                    src = (entry.get("source") or source).strip()
                    if isinstance(src, dict):
                        src = src.get("name") or source
                    if title or url:
                        items.append({"title": title or "(No title)", "source": src, "date": date_str, "url": url, "summary": summary})
                return items
        except (json.JSONDecodeError, TypeError):
            pass
        # Fallback: first line as single item
        first = content.strip().split("\n")[0].strip()[:300] if content else ""
        if first:
            items.append({"title": first, "source": source, "date": None, "url": "", "summary": first[:500]})
        return items

    def _normalize_and_merge_news(
        self, rss_items: list, sentiment_items: list, regulatory_items: list
    ) -> list[dict]:
        """Convert all raw items to standard schema {title, source, date, url, summary}. Dedupe by URL."""
        seen_urls: set[str] = set()
        out: list[dict] = []

        def add(item: dict) -> None:
            url = (item.get("link") or item.get("url") or "").strip()
            if url and url in seen_urls:
                return
            if url:
                seen_urls.add(url)
            rec = {
                "title": (item.get("title") or "").strip() or "(No title)",
                "source": (item.get("source") or "Unknown").strip(),
                "date": item.get("date") or item.get("published") or "",
                "url": url,
                "summary": (item.get("summary") or "").strip()[:500],
            }
            out.append(rec)

        for it in rss_items:
            if isinstance(it, dict):
                link = it.get("link") or it.get("url") or ""
                add({
                    "title": it.get("title"),
                    "source": it.get("source"),
                    "date": it.get("date") or it.get("published"),
                    "url": link,
                    "link": link,
                    "summary": it.get("summary") or it.get("title"),
                })
        for it in sentiment_items + regulatory_items:
            if isinstance(it, dict):
                add(it)
        # Sort by date desc (empty date last)
        def _sort_key(x: dict) -> tuple:
            d = x.get("date") or ""
            return (0 if d else 1, d)

        out.sort(key=_sort_key, reverse=True)
        return out[:30]

    def _build_news_with_citations(self, items: list[dict]) -> tuple[list[dict], dict[str, str]]:
        """Assign NEWS1..NEWSn and build citations map."""
        news: list[dict] = []
        citations: dict[str, str] = {}
        for i, it in enumerate(items):
            cid = f"NEWS{i + 1}"
            rec = dict(it)
            rec["id"] = cid
            news.append(rec)
            if rec.get("url"):
                citations[cid] = rec["url"]
        return (news, citations)

    def _llm_news_fallback(self, query: str, symbol: str) -> tuple[list[dict], dict[str, str]]:
        """When all news APIs fail, call LLM for news. Returns (news_list, citations) with source=llm."""
        from llm.prompts import WEBSEARCHER_NEWS_FALLBACK_SYSTEM

        user_content = f"Query: {query}\nSymbol/topic: {symbol}"
        out = self._llm_client.complete(WEBSEARCHER_NEWS_FALLBACK_SYSTEM, user_content) or ""
        items: list[dict] = []
        for line in out.strip().split("\n"):
            line = line.strip()
            if not line or len(line) < 10:
                continue
            # Parse "HEADLINE | summary" or treat whole line as title
            if "|" in line:
                parts = line.split("|", 1)
                title = (parts[0].strip() or "")[:300]
                summary = (parts[1].strip() if len(parts) > 1 else "")[:500]
            else:
                title = line[:300]
                summary = line[:500]
            if title:
                items.append({
                    "title": title,
                    "source": "llm",
                    "date": _now_iso()[:10],
                    "url": "",
                    "summary": summary,
                })
        return self._build_news_with_citations(items[:10])

    def _fetch_all_sources_for_symbol(self, symbol: str) -> dict[str, Any]:
        """Fetch all data sources in parallel: stooq, yahoo, etfdb, market_tool (fundamentals, news, global_news)."""
        stooq_res: dict[str, Any] = {}
        yahoo_res: dict[str, Any] = {}
        etfdb_res: dict[str, Any] = {}
        market_data: dict[str, Any] = {}
        sentiment: dict[str, Any] = {}
        regulatory: dict[str, Any] = {}
        if not self.mcp_client:
            return {"stooq": {}, "yahoo": {}, "etfdb": {}, "market_data": market_data, "sentiment": sentiment, "regulatory": regulatory}

        reg = self.mcp_client.get_registered_tool_names() or []
        call = self.mcp_client.call_tool
        tasks: list[tuple[str, str, dict]] = []
        if "stooq_tool.get_price" in reg:
            tasks.append(("stooq", "stooq_tool.get_price", {"symbol": symbol}))
        yahoo_tool = "yahoo_finance_tool.get_fundamental" if "yahoo_finance_tool.get_fundamental" in reg else "yahoo_finance_tool.get_price"
        if yahoo_tool in reg:
            tasks.append(("yahoo", yahoo_tool, {"symbol": symbol}))
        if "etfdb_tool.get_fund_data" in reg:
            tasks.append(("etfdb", "etfdb_tool.get_fund_data", {"symbol": symbol}))
        if "market_tool.get_fundamentals" in reg:
            tasks.append(("market", "market_tool.get_fundamentals", {"ticker": symbol, "symbol": symbol}))
        # market_tool news paths require dates for Alpha Vantage; empty payload caused
        # "time data '' does not match format" for get_global_news in logs.
        today = date.today().isoformat()
        start = (date.today() - timedelta(days=7)).isoformat()
        if "market_tool.get_news" in reg:
            tasks.append(
                (
                    "sentiment",
                    "market_tool.get_news",
                    {"symbol": symbol, "start_date": start, "end_date": today, "limit": 5},
                )
            )
        if "market_tool.get_global_news" in reg:
            tasks.append(
                (
                    "regulatory",
                    "market_tool.get_global_news",
                    {"as_of_date": today, "look_back_days": 7, "limit": 5},
                )
            )

        results: dict[str, Any] = {}
        with ThreadPoolExecutor(max_workers=max(6, len(tasks))) as ex:
            futures = {ex.submit(call, tool, payload): key for key, tool, payload in tasks}
            for fut in as_completed(futures):
                key = futures[fut]
                try:
                    r = fut.result() or {}
                    r = r if isinstance(r, dict) else {}
                    if key == "market":
                        market_data = r
                    elif key == "sentiment":
                        sentiment = r
                    elif key == "regulatory":
                        regulatory = r
                    else:
                        results[key] = r
                except Exception as e:
                    logger.warning("fetch %s failed for %s: %s", key, symbol, e)
                    err = {"error": str(e)}
                    if key == "market":
                        market_data = err
                    elif key == "sentiment":
                        sentiment = err
                    elif key == "regulatory":
                        regulatory = err
                    else:
                        results[key] = err

        stooq_res = results.get("stooq", {})
        yahoo_res = results.get("yahoo", {})
        etfdb_res = results.get("etfdb", {})
        stooq_ok = stooq_res and "error" not in stooq_res and (stooq_res.get("price") is not None or stooq_res.get("close") is not None)
        yahoo_ok = yahoo_res and "error" not in yahoo_res and bool(
            (yahoo_res.get("price") or yahoo_res.get("close"))
            or yahoo_res.get("expense_ratio") is not None
            or yahoo_res.get("aum") is not None
            or (yahoo_res.get("holdings_top10") or yahoo_res.get("sector_exposure"))
        )
        logger.info(
            "agent.websearcher.parallel symbol=%s stooq=%s yahoo=%s etfdb=%s",
            symbol,
            "ok" if stooq_ok else ("error:" + str(stooq_res.get("error", "?"))[:80]),
            "ok" if yahoo_ok else ("error:" + str(yahoo_res.get("error", "?"))[:80]),
            "ok" if (etfdb_res and "error" not in etfdb_res) else "fail",
        )
        logger.info(
            "agent.websearcher.yahoo symbol=%s yahoo=%s",
            symbol, _summarize_yahoo_fundamental(yahoo_res),
        )

        return {
            "stooq": stooq_res,
            "yahoo": yahoo_res,
            "etfdb": etfdb_res,
            "market_data": market_data,
            "sentiment": sentiment,
            "regulatory": regulatory,
        }

    def _normalise_to_schema(
        self,
        symbol: str,
        name: str,
        asset_class: Any,
        static: dict,
        stooq: dict,
        etfdb: dict,
        yahoo: Optional[dict] = None,
    ) -> dict[str, Any]:
        """Build standard output schema from merged source results. Includes stooq and yahoo when available."""
        source: dict[str, str] = {}
        if static:
            source["static"] = "FinanceDatabase"
        stooq_ok = stooq and "error" not in stooq
        yahoo_ok = yahoo and "error" not in yahoo
        price_data = stooq if stooq_ok else (yahoo or {}) if yahoo_ok else {}
        if stooq_ok:
            source["price"] = "stooq"
        if yahoo_ok:
            source["price_yahoo"] = "yahoo"
        if etfdb and "error" not in etfdb:
            source["fundamentals"] = "ETFdb"
        if yahoo_ok and (
            (yahoo or {}).get("expense_ratio") is not None
            or (yahoo or {}).get("aum") is not None
            or (yahoo or {}).get("holdings_top10")
            or (yahoo or {}).get("sector_exposure")
            or (yahoo or {}).get("raw")
        ):
            source["fundamentals_yahoo"] = "yahoo"

        price = None
        if price_data:
            price = price_data.get("price") or price_data.get("close")
        try:
            price = float(price) if price is not None else None
        except (TypeError, ValueError):
            price = None

        price_yahoo = None
        if yahoo_ok:
            py = (yahoo or {}).get("price") or (yahoo or {}).get("close")
            try:
                price_yahoo = float(py) if py is not None else None
            except (TypeError, ValueError):
                pass

        expense_ratio = None
        if etfdb and "error" not in etfdb:
            expense_ratio = etfdb.get("expense_ratio")
        elif yahoo_ok:
            expense_ratio = (yahoo or {}).get("expense_ratio")
        try:
            expense_ratio = float(expense_ratio) if expense_ratio is not None else None
        except (TypeError, ValueError):
            expense_ratio = None

        aum = None
        if etfdb and "error" not in etfdb:
            aum = etfdb.get("aum")
        elif yahoo_ok:
            aum = (yahoo or {}).get("aum")
        try:
            aum = float(aum) if aum is not None else None
        except (TypeError, ValueError):
            aum = None

        holdings = []
        if etfdb and "error" not in etfdb:
            holdings = (etfdb.get("holdings_top10") or [])[:10]
        elif yahoo_ok:
            holdings = ((yahoo or {}).get("holdings_top10") or [])[:10]

        sector_exposure = {}
        if etfdb and "error" not in etfdb and etfdb.get("sector_exposure"):
            sector_exposure = dict(etfdb["sector_exposure"])
        elif yahoo_ok and (yahoo or {}).get("sector_exposure"):
            try:
                sector_exposure = dict((yahoo or {}).get("sector_exposure") or {})
            except Exception:
                sector_exposure = {}

        yahoo_raw = None
        if yahoo_ok and (yahoo or {}).get("raw"):
            yahoo_raw = (yahoo or {}).get("raw")

        # Prefer richer name from Yahoo when static catalog name is missing
        final_name = name or ((yahoo or {}).get("name") if yahoo_ok else "") or symbol

        out = {
            "symbol": symbol,
            "name": final_name,
            "asset_class": asset_class or "Equity",
            "expense_ratio": expense_ratio,
            "aum": aum,
            "price": price,
            "sector_exposure": sector_exposure,
            "holdings_top10": holdings,
            "source": source,
            "timestamp": _now_iso(),
        }
        if price_yahoo is not None:
            out["price_yahoo"] = price_yahoo
        if yahoo_raw is not None:
            # Provide richer Yahoo fundamental modules to Planner without changing top-level reply schema
            out["yahoo_fundamentals_raw"] = yahoo_raw
        return out

    def _run_parallel_flow(self, content: dict) -> dict[str, Any]:
        """Query all sources in parallel: Financial Data + News Search. Merge and return reply_content."""
        symbols, static_matches = self._resolve_symbols(content)
        query = (content.get("query") or content.get("fund") or content.get("symbol") or "AAPL").strip()
        symbol = symbols[0] if symbols else "AAPL"
        days = 7
        try:
            d = content.get("days") or content.get("look_back_days")
            if d is not None:
                days = max(1, min(30, int(d)))
        except (TypeError, ValueError):
            pass

        static_by_sym: dict[str, dict] = {}
        for m in static_matches:
            sym = (m.get("symbol") or "").strip()
            if sym:
                static_by_sym[sym] = m

        # Run Financial Data Search and News Search in parallel
        financial_result: dict[str, Any] = {}
        news_data: tuple[list[dict], list[dict], list[dict]] = ([], [], [])

        def do_financial() -> dict[str, Any]:
            all_results: dict[str, dict] = {}
            with ThreadPoolExecutor(max_workers=4) as ex:
                futures = {ex.submit(self._fetch_all_sources_for_symbol, s): s for s in symbols[:3]}
                for fut in as_completed(futures):
                    sym = futures[fut]
                    try:
                        all_results[sym] = fut.result()
                    except Exception as e:
                        logger.warning("parallel fetch failed for %s: %s", sym, e)
                        all_results[sym] = {"stooq": {}, "yahoo": {}, "etfdb": {}, "market_data": {}, "sentiment": {}, "regulatory": {}}
            return self._merge_financial_results(all_results, symbols, static_by_sym)

        def do_news() -> tuple[list[dict], list[dict], list[dict]]:
            return self._fetch_news_sources(str(query)[:200], symbol, days)

        with ThreadPoolExecutor(max_workers=2) as ex:
            fut_fin = ex.submit(do_financial)
            fut_news = ex.submit(do_news)
            try:
                financial_result = fut_fin.result()
            except Exception as e:
                logger.warning("financial fetch failed: %s", e)
                financial_result = {
                    "normalized_fund": [],
                    "market_data": {"timestamp": _now_iso()},
                    "sentiment": {"timestamp": _now_iso()},
                    "regulatory": {"timestamp": _now_iso()},
                }
            try:
                news_data = fut_news.result()
            except Exception as e:
                logger.debug("news fetch failed: %s", e)

        # Build news + citations
        merged_items = self._normalize_and_merge_news(
            news_data[0], news_data[1], news_data[2]
        )
        news_list, citations = self._build_news_with_citations(merged_items)

        # News fallback: when all news APIs returned nothing, call LLM
        if not news_list and self._llm_client:
            llm_news, llm_citations = self._llm_news_fallback(
                str(query)[:200], symbol
            )
            if llm_news:
                news_list = llm_news
                citations = llm_citations
                logger.info(
                    "agent.websearcher.news_llm_fallback symbol=%s news_count=%s",
                    symbol, len(news_list),
                )

        logger.info(
            "agent.websearcher.news news_count=%s citations_count=%s",
            len(news_list), len(citations),
        )
        if news_list:
            sample = news_list[0]
            logger.info(
                "agent.websearcher.news_sample title=%s source=%s url=%s",
                (sample.get("title") or "")[:120],
                sample.get("source") or "Unknown",
                sample.get("url") or "",
            )
        financial_result["news"] = news_list
        financial_result["citations"] = citations
        financial_result["news_timestamp"] = _now_iso()
        return financial_result

    def _merge_financial_results(
        self,
        all_results: dict[str, dict],
        symbols: list[str],
        static_by_sym: dict[str, dict],
    ) -> dict[str, Any]:
        """Merge per-symbol results into normalized_fund + market_data/sentiment/regulatory."""
        normalized: list[dict] = []
        market_data: dict[str, Any] = {}
        sentiment: dict[str, Any] = {}
        regulatory: dict[str, Any] = {}
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
            )
            normalized.append(rec)
            if not market_data and data.get("market_data"):
                market_data = data["market_data"]
            if not sentiment and data.get("sentiment"):
                sentiment = data["sentiment"]
            if not regulatory and data.get("regulatory"):
                regulatory = data["regulatory"]

        market_data = market_data or {"timestamp": _now_iso()}
        sentiment = sentiment or {"timestamp": _now_iso()}
        regulatory = regulatory or {"timestamp": _now_iso()}
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
        raw_fund = content.get("fund") or content.get("symbol") or content.get("query") or "AAPL"
        fund = self._normalize_symbol(str(raw_fund))
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
        if message.performative == Performative.REQUEST:
            logger.info("--- WebSearcher ---")
            logger.info("agent.websearcher.start")
        query = content.get("query") or fund

        # Parallel flow: query all sources (fund_catalog, stooq, Yahoo, ETFdb, market_tool) in parallel
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

        # All-tools-fail fallback: when no tool returned usable data, call LLM for data search
        if self._llm_client and self._all_tools_failed(reply_content):
            query = content.get("query") or fund
            primary = (reply_content.get("normalized_fund") or [{}])[0]
            symbol = primary.get("symbol", fund) if isinstance(primary, dict) else fund
            reply_content = self._llm_data_search_fallback(str(query)[:500], symbol)
            logger.info("agent.websearcher.llm_fallback symbol=%s", symbol)

        # Fact conflict resolution: when stooq and yahoo disagree on price, LLM picks more credible
        if self._llm_client:
            nf = reply_content.get("normalized_fund") or []
            for rec in nf if isinstance(nf, list) else []:
                if not isinstance(rec, dict) or not self._has_price_conflict(rec):
                    continue
                symbol = rec.get("symbol") or "?"
                pr = rec.get("price")
                py = rec.get("price_yahoo")
                if pr is not None and py is not None:
                    try:
                        res = self._resolve_conflict_with_llm(symbol, float(pr), float(py))
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
                            symbol, res["chosen_source"],
                        )
                    except (TypeError, ValueError) as e:
                        logger.debug("Conflict resolution failed for %s: %s", symbol, e)

        # Optional LLM summary for the planner; fallback when LLM fails (e.g. Connection error)
        fallback = self._fallback_summary_from_normalized(reply_content.get("normalized_fund"))
        reply_content = dict(reply_content)
        if reply_content.get("llm_fallback"):
            nf = reply_content.get("normalized_fund") or []
            first = nf[0] if nf and isinstance(nf[0], dict) else {}
            reply_content["summary"] = first.get("llm_fallback_content", fallback)
        elif self._llm_client is not None:
            from llm.prompts import WEBSEARCHER_SYSTEM, get_websearcher_user_content

            query = content.get("query") or fund
            user_content = get_websearcher_user_content(str(query)[:500], reply_content)
            summary = self._llm_client.complete(WEBSEARCHER_SYSTEM, user_content)
            if not summary or summary == user_content or (len(summary) > 3000 and "query:" in summary[:100]):
                summary = fallback
            reply_content["summary"] = summary or fallback
        else:
            reply_content["summary"] = fallback
        has_errors = any(
            isinstance(reply_content.get(k), dict) and reply_content.get(k).get("error")
            for k in ("market_data", "sentiment", "regulatory")
            if reply_content.get(k)
        )
        status = "limited_data" if has_errors else "success"
        logger.info("agent.websearcher.done status=%s", status)
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
        # Stub: use global news as placeholder for regulatory
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
