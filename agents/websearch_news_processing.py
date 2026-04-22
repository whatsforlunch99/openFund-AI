"""Websearch news normalization and market fetchers."""

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from difflib import SequenceMatcher
from typing import TYPE_CHECKING, Any

from agents.websearch_constants import AUTHORITATIVE_ALLOWLIST, SOURCE_REGISTRY
from agents.websearch_helpers import (
    alpha_vantage_cooldown_message,
    by_tool_should_call,
    by_tool_symbol_for_iteration,
    prefer_yahoo_price_first,
    summarize_yahoo_fundamental,
    websearch_now_iso,
)
from util.agent_heuristics import get_websearcher_heuristics

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class WebSearchNewsProcessingMixin:
    """Split part for readability."""

    def _content_to_news_items(self, content: str, source: str) -> list[dict]:
        """Convert market_tool content to news items. Tries JSON feed; else first line as title."""
        items: list[dict] = []
        if not content or not isinstance(content, str):
            return items

        # Prefer structured feed parsing when provider payload is JSON.
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
                        items.append(
                            {
                                "title": title or "(No title)",
                                "source": src,
                                "date": date_str,
                                "url": url,
                                "summary": summary,
                            }
                        )
                return items
        except (json.JSONDecodeError, TypeError):
            pass

        # Fall back to a single best-effort headline from plain text.
        first = content.strip().split("\n")[0].strip()[:300] if content else ""
        if first:
            items.append(
                {
                    "title": first,
                    "source": source,
                    "date": None,
                    "url": "",
                    "summary": first[:500],
                }
            )
        return items

    def _normalize_and_merge_news(
        self,
        rss_items: list,
        sentiment_items: list,
        regulatory_items: list,
        query_terms: dict[str, str],
    ) -> list[dict]:
        """Normalize, score, dedupe, and apply fallback thresholds."""
        ranked_sources = self._registry_top10()
        rank_by_domain = {s["domain"]: s for s in ranked_sources}
        seen_urls: set[str] = set()
        seen_titles: set[str] = set()
        seen_title_texts: list[str] = []
        out: list[dict] = []

        def source_meta(domain: str) -> dict[str, Any]:
            src = rank_by_domain.get(domain) or {}
            return {
                "source_rank": src.get("source_rank", 999),
                "fetch_mode": src.get("fetch_mode", "rss"),
            }

        def add(item: dict) -> None:
            raw_url = (item.get("link") or item.get("url") or "").strip()
            canon = self._canonical_url(raw_url)
            title = (item.get("title") or "").strip() or "(No title)"
            title_fp = self._title_fingerprint(title)
            title_norm = self._normalize_title_for_similarity(title)
            domain = self._extract_domain(raw_url)
            source_domain = self._domain_from_source_name(str(item.get("source") or ""))
            if source_domain and (not domain or not self._allowlist_pass(domain)):
                domain = source_domain
            near_dup = any(
                SequenceMatcher(None, title_norm, prev).ratio() >= 0.93
                for prev in seen_title_texts
            )
            if canon and canon in seen_urls or title_fp in seen_titles or near_dup:
                return

            # Blend source trust, recency, and query match into one score.
            allow = self._allowlist_pass(domain)
            m = source_meta(domain)
            authority_score = 1.0 if allow else 0.0
            recency = self._recency_score(
                item.get("date") or item.get("published") or ""
            )
            match = self._match_score(title, query_terms)
            score = 0.5 * authority_score + 0.3 * recency + 0.2 * match
            if canon:
                seen_urls.add(canon)
            seen_titles.add(title_fp)
            seen_title_texts.append(title_norm)
            out.append(
                {
                    "title": title,
                    "source": (item.get("source") or domain or "Unknown").strip(),
                    "published": self._published_to_date(
                        item.get("date") or item.get("published")
                    ),
                    "url": raw_url,
                    "summary": (item.get("summary") or "").strip()[:500],
                    "domain": domain,
                    "allowlist_pass": allow,
                    "authority_tier": "primary" if allow else "secondary",
                    "source_rank": m["source_rank"],
                    "fetch_mode": m["fetch_mode"],
                    "score": round(score, 4),
                }
            )

        for it in rss_items:
            if isinstance(it, dict):
                add(it)
        for it in sentiment_items + regulatory_items:
            if isinstance(it, dict):
                add(it)

        def _published_ord(value: str) -> int:
            try:
                return datetime.strptime(value or "", "%Y-%m-%d").toordinal()
            except ValueError:
                return -1

        out.sort(
            key=lambda x: (
                -x["score"],
                -_published_ord(x.get("published") or ""),
                (x.get("source") or "").lower(),
            )
        )

        # Keep mostly authoritative items; only backfill limited secondary coverage.
        primary = [x for x in out if x["allowlist_pass"]]
        if len(primary) >= 3:
            return primary[:30]
        secondary = [x for x in out if not x["allowlist_pass"] and x["score"] >= 0.6][
            :2
        ]
        merged = (primary + secondary)[:30]
        if len(merged) < 2:
            return []
        return merged

    def _build_news_with_citations(
        self, items: list[dict]
    ) -> tuple[list[dict], dict[str, str], list[dict]]:
        """Assign NEWS1..NEWSn and build citations map."""
        news: list[dict] = []
        citations: dict[str, str] = {}
        citation_rows: list[dict] = []
        cap = 3 if len(items) >= 3 else len(items)
        for i, it in enumerate(items):
            cid = f"NEWS{i + 1}"
            rec = dict(it)
            rec["id"] = cid
            news.append(rec)
            if rec.get("url") and len(citations) < cap:
                citations[cid] = rec["url"]
                citation_rows.append(
                    {
                        "title": rec.get("title") or "",
                        "source": rec.get("source") or "",
                        "url": rec["url"],
                    }
                )
        return (news, citations, citation_rows)

    def _llm_news_fallback(
        self, query: str, symbol: str
    ) -> tuple[list[dict], dict[str, str], list[dict]]:
        """When all news APIs fail, call LLM for news. Returns (news_list, citations) with source=llm."""
        from llm.prompts import WEBSEARCHER_NEWS_FALLBACK_SYSTEM

        user_content = f"Query: {query}\nSymbol/topic: {symbol}"
        out = (
            self._llm_client.complete(WEBSEARCHER_NEWS_FALLBACK_SYSTEM, user_content)
            or ""
        )
        items: list[dict] = []

        # Parse one synthetic item per usable output line.
        for line in out.strip().split("\n"):
            line = line.strip()
            if not line or len(line) < 10:
                continue
            if "|" in line:
                parts = line.split("|", 1)
                title = (parts[0].strip() or "")[:300]
                summary = (parts[1].strip() if len(parts) > 1 else "")[:500]
            else:
                title = line[:300]
                summary = line[:500]
            if title:
                items.append(
                    {
                        "title": title,
                        "source": "llm",
                        "date": websearch_now_iso()[:10],
                        "url": "",
                        "summary": summary,
                    }
                )
        return self._build_news_with_citations(items[:10])

    def _fetch_all_sources_for_symbol(
        self,
        symbol: str,
        by_tool: dict[str, Any] | None = None,
        include_etfdb: bool = True,
        symbol_resolution: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Fetch all data sources in parallel: Yahoo (price + optional fundamentals), Stooq, etfdb, market_tool."""
        stooq_res: dict[str, Any] = {}
        yahoo_res: dict[str, Any] = {}
        etfdb_res: dict[str, Any] = {}
        market_data: dict[str, Any] = {}
        sentiment: dict[str, Any] = {}
        regulatory: dict[str, Any] = {}
        if not self.mcp_client:
            return {
                "stooq": {},
                "yahoo": {},
                "etfdb": {},
                "market_data": market_data,
                "sentiment": sentiment,
                "regulatory": regulatory,
            }

        # Build per-provider tasks with tool-specific symbol routing.
        av_cool = alpha_vantage_cooldown_message()
        reg = self.mcp_client.get_registered_tool_names() or []
        call = self.mcp_client.call_tool
        tasks: list[tuple[str, str, dict]] = []
        stooq_sym = by_tool_symbol_for_iteration(
            by_tool, "stooq_tool.get_price", symbol
        )
        yahoo_sym_price = by_tool_symbol_for_iteration(
            by_tool, "yahoo_finance_tool.get_price", symbol
        )
        yahoo_sym_fund = by_tool_symbol_for_iteration(
            by_tool, "yahoo_finance_tool.get_fundamental", symbol
        )
        etf_sym = by_tool_symbol_for_iteration(
            by_tool, "etfdb_tool.get_fund_data", symbol
        )
        mkt_f_sym = by_tool_symbol_for_iteration(
            by_tool, "market_tool.get_fundamentals", symbol
        )
        mkt_n_sym = by_tool_symbol_for_iteration(
            by_tool, "market_tool.get_news", symbol
        )
        has_yahoo_price = "yahoo_finance_tool.get_price" in reg and by_tool_should_call(
            by_tool, "yahoo_finance_tool.get_price"
        )
        has_yahoo_fund = (
            "yahoo_finance_tool.get_fundamental" in reg
            and by_tool_should_call(by_tool, "yahoo_finance_tool.get_fundamental")
        )
        if has_yahoo_price:
            tasks.append(
                ("yahoo", "yahoo_finance_tool.get_price", {"symbol": yahoo_sym_price})
            )
        elif has_yahoo_fund:
            tasks.append(
                (
                    "yahoo",
                    "yahoo_finance_tool.get_fundamental",
                    {"symbol": yahoo_sym_fund},
                )
            )
        if has_yahoo_price and has_yahoo_fund:
            tasks.append(
                (
                    "yahoo_fundamental",
                    "yahoo_finance_tool.get_fundamental",
                    {"symbol": yahoo_sym_fund},
                )
            )
        if "stooq_tool.get_price" in reg and by_tool_should_call(
            by_tool, "stooq_tool.get_price"
        ):
            stooq_entry = ("stooq", "stooq_tool.get_price", {"symbol": stooq_sym})
            if prefer_yahoo_price_first(symbol_resolution, symbol):
                tasks.append(stooq_entry)
            else:
                tasks.insert(0, stooq_entry)
        if (
            include_etfdb
            and "etfdb_tool.get_fund_data" in reg
            and (symbol not in get_websearcher_heuristics().known_index_symbols)
            and by_tool_should_call(by_tool, "etfdb_tool.get_fund_data")
        ):
            tasks.append(("etfdb", "etfdb_tool.get_fund_data", {"symbol": etf_sym}))
        if (
            not av_cool
            and "market_tool.get_fundamentals" in reg
            and by_tool_should_call(by_tool, "market_tool.get_fundamentals")
        ):
            tasks.append(
                (
                    "market",
                    "market_tool.get_fundamentals",
                    {"ticker": mkt_f_sym, "symbol": mkt_f_sym},
                )
            )
        today = date.today().isoformat()
        start = (date.today() - timedelta(days=7)).isoformat()
        if (
            not av_cool
            and "market_tool.get_news" in reg
            and by_tool_should_call(by_tool, "market_tool.get_news")
        ):
            tasks.append(
                (
                    "sentiment",
                    "market_tool.get_news",
                    {
                        "symbol": mkt_n_sym,
                        "start_date": start,
                        "end_date": today,
                        "limit": 5,
                    },
                )
            )
        if (
            not av_cool
            and "market_tool.get_global_news" in reg
            and by_tool_should_call(by_tool, "market_tool.get_global_news")
        ):
            tasks.append(
                (
                    "regulatory",
                    "market_tool.get_global_news",
                    {"as_of_date": today, "look_back_days": 7, "limit": 5},
                )
            )
        results: dict[str, Any] = {}

        # Execute data providers concurrently and split market/news side channels.
        with ThreadPoolExecutor(max_workers=max(6, len(tasks))) as ex:
            futures = {
                ex.submit(call, tool, payload): key for key, tool, payload in tasks
            }
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

        # Merge Yahoo price and Yahoo fundamental payloads into one record.
        yahoo_res = results.get("yahoo", {})
        yahoo_extra = results.get("yahoo_fundamental")
        if (
            isinstance(yahoo_extra, dict)
            and yahoo_extra
            and ("error" not in yahoo_extra)
        ):
            base = dict(yahoo_res) if isinstance(yahoo_res, dict) else {}
            for k, v in yahoo_extra.items():
                if k == "error" or v in (None, "", []):
                    continue
                cur = base.get(k)
                if cur in (None, "", []):
                    base[k] = v
            yahoo_res = base
        stooq_res = results.get("stooq", {})
        etfdb_res = results.get("etfdb", {})
        stooq_ok = (
            stooq_res
            and "error" not in stooq_res
            and (
                stooq_res.get("price") is not None or stooq_res.get("close") is not None
            )
        )
        yahoo_ok = (
            yahoo_res
            and "error" not in yahoo_res
            and bool(
                (yahoo_res.get("price") or yahoo_res.get("close"))
                or yahoo_res.get("expense_ratio") is not None
                or yahoo_res.get("aum") is not None
                or (yahoo_res.get("holdings_top10") or yahoo_res.get("sector_exposure"))
            )
        )
        logger.info(
            "agent.websearcher.parallel symbol=%s stooq=%s yahoo=%s etfdb=%s",
            symbol,
            "ok" if stooq_ok else "error:" + str(stooq_res.get("error", "?"))[:80],
            "ok" if yahoo_ok else "error:" + str(yahoo_res.get("error", "?"))[:80],
            "ok" if etfdb_res and "error" not in etfdb_res else "fail",
        )
        logger.info(
            "agent.websearcher.yahoo symbol=%s yahoo=%s",
            symbol,
            summarize_yahoo_fundamental(yahoo_res),
        )
        return {
            "stooq": stooq_res,
            "yahoo": yahoo_res,
            "etfdb": etfdb_res,
            "market_data": market_data,
            "sentiment": sentiment,
            "regulatory": regulatory,
        }
