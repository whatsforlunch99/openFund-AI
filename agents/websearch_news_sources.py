"""Websearch source fetching and ranking helpers."""

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, date, datetime, timedelta
from hashlib import sha1
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse, urlunparse

from agents.websearch_constants import AUTHORITATIVE_ALLOWLIST, SOURCE_REGISTRY
from agents.websearch_helpers import (
    alpha_vantage_cooldown_message,
    by_tool_should_call,
    by_tool_symbol,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class WebSearchNewsSourceMixin:
    """Split part for readability."""

    def _fetch_news_sources(
        self,
        query: str,
        symbol: str,
        days: int = 7,
        by_tool: dict[str, Any] | None = None,
    ) -> tuple[list[dict], list[dict], list[dict]]:
        """Fetch news in parallel: RSS, market_tool.get_news, market_tool.get_global_news.
        Returns (rss_items, sentiment_items, regulatory_items) as raw item lists.
        """
        rss_items: list[dict] = []
        sentiment_items: list[dict] = []
        regulatory_items: list[dict] = []
        if not self.mcp_client:
            return (rss_items, sentiment_items, regulatory_items)

        # Build candidate tasks from registry + optional market APIs.
        want_news = True
        av_cool = alpha_vantage_cooldown_message()
        reg = self.mcp_client.get_registered_tool_names() or []
        call = self.mcp_client.call_tool
        tasks: list[tuple[str, str, dict]] = []
        news_sym = by_tool_symbol(by_tool, "market_tool.get_news", symbol)
        if want_news:
            for src in self._registry_top10():
                domain = src.get("domain") or ""
                fetch_mode = src.get("fetch_mode") or "rss"
                domain_query = f"{query} site:{domain}".strip()
                if (
                    fetch_mode == "playwright"
                    and "news_tool.search_playwright" in reg
                    and by_tool_should_call(by_tool, "news_tool.search_playwright")
                ):
                    tasks.append(
                        (
                            "playwright_" + domain,
                            "news_tool.search_playwright",
                            {"query": query, "domain": domain},
                        )
                    )
                elif (
                    fetch_mode == "api"
                    and "news_tool.search_gdelt" in reg
                    and by_tool_should_call(by_tool, "news_tool.search_gdelt")
                ):
                    tasks.append(
                        (
                            "gdelt_" + domain,
                            "news_tool.search_gdelt",
                            {"query": domain_query, "limit": 8},
                        )
                    )
                elif "news_tool.search_rss" in reg and by_tool_should_call(
                    by_tool, "news_tool.search_rss"
                ):
                    tasks.append(
                        (
                            "rss_" + domain,
                            "news_tool.search_rss",
                            {"query": domain_query, "days": days},
                        )
                    )
        today = date.today().isoformat()
        start = (date.today() - timedelta(days=days)).isoformat()
        if (
            want_news
            and (not av_cool)
            and ("market_tool.get_news" in reg)
            and by_tool_should_call(by_tool, "market_tool.get_news")
        ):
            tasks.append(
                (
                    "sentiment",
                    "market_tool.get_news",
                    {
                        "symbol": news_sym,
                        "start_date": start,
                        "end_date": today,
                        "limit": 5,
                    },
                )
            )
        if (
            want_news
            and (not av_cool)
            and ("market_tool.get_global_news" in reg)
            and by_tool_should_call(by_tool, "market_tool.get_global_news")
        ):
            tasks.append(
                (
                    "regulatory",
                    "market_tool.get_global_news",
                    {"as_of_date": today, "look_back_days": days, "limit": 5},
                )
            )
        if not tasks:
            return (rss_items, sentiment_items, regulatory_items)
        results: dict[str, Any] = {}

        # Keep outbound fan-out bounded to reduce burst load on providers.
        with ThreadPoolExecutor(max_workers=min(len(tasks), 6)) as ex:
            futures = {
                ex.submit(call, tool, payload): key for key, tool, payload in tasks
            }
            for fut in as_completed(futures):
                key = futures[fut]
                try:
                    r = fut.result() or {}
                    if isinstance(r, dict) and "error" not in r:
                        results[key] = r
                except Exception as e:
                    logger.debug("news fetch %s failed: %s", key, e)

        # Merge heterogeneous source buckets into a single rss_items pool.
        for key, value in results.items():
            if (
                key.startswith("rss_") or key.startswith("gdelt_")
            ) and "items" in value:
                rss_items.extend(value["items"] or [])
        for key, value in results.items():
            if key.startswith("playwright_") and "items" in value:
                rss_items.extend(value["items"] or [])

        # If coverage is still thin, crawl top domains directly as fallback.
        if (
            len(rss_items) < 2
            and "news_tool.search_playwright" in reg
            and by_tool_should_call(by_tool, "news_tool.search_playwright")
        ):
            for src in self._registry_top10()[:5]:
                crawl_url = (src.get("crawl_url") or "").strip()
                domain = (src.get("domain") or "").strip()
                if not crawl_url or not domain:
                    continue
                try:
                    r = (
                        call(
                            "news_tool.search_playwright",
                            {"url": crawl_url, "domain": domain, "query": query},
                        )
                        or {}
                    )
                    if isinstance(r, dict) and "items" in r:
                        rss_items.extend(r.get("items") or [])
                except Exception as e:
                    logger.debug("news crawl fallback %s failed: %s", domain, e)

        # Convert market API payloads into the same news-item shape.
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
            len(rss_items),
            len(sentiment_items),
            len(regulatory_items),
        )
        return (rss_items, sentiment_items, regulatory_items)

    def _registry_top10(self) -> list[dict[str, Any]]:
        # Rank candidate sources by weighted quality + deterministic tiebreaker.
        ranked = sorted(
            SOURCE_REGISTRY,
            key=lambda s: (
                -(
                    0.35 * s["coverage"]
                    + 0.35 * s["reliability"]
                    + 0.2 * s["relevance"]
                    + 0.1 * s["efficiency"]
                ),
                s["domain"],
            ),
        )
        out: list[dict[str, Any]] = []
        for idx, item in enumerate(ranked[:10], start=1):
            rec = dict(item)
            rec["source_rank"] = idx
            out.append(rec)
        return out

    def _extract_domain(self, url: str) -> str:
        if not isinstance(url, str) or not url.strip():
            return ""
        try:
            host = (urlparse(url).netloc or "").lower()
            if host.startswith("www."):
                host = host[4:]
            return host
        except Exception:
            return ""

    def _domain_from_source_name(self, source_name: str) -> str:
        text = (source_name or "").strip().lower()
        if not text:
            return ""
        mapping = {
            "reuters": "reuters.com",
            "bloomberg": "bloomberg.com",
            "wsj": "wsj.com",
            "wall street journal": "wsj.com",
            "financial times": "ft.com",
            "ft": "ft.com",
            "cnbc": "cnbc.com",
            "marketwatch": "marketwatch.com",
            "barrons": "barrons.com",
            "federal reserve": "federalreserve.gov",
            "u.s. securities and exchange commission": "sec.gov",
            "bureau of labor statistics": "bls.gov",
            "coindesk": "coindesk.com",
            "the block": "theblock.co",
            "yahoo finance": "finance.yahoo.com",
        }
        for key, domain in mapping.items():
            if key in text:
                return domain
        return ""

    def _canonical_url(self, url: str) -> str:
        if not isinstance(url, str) or not url.strip():
            return ""
        try:
            p = urlparse(url.strip())
            return urlunparse(
                (p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/"), "", "", "")
            )
        except Exception:
            return url.strip()

    def _title_fingerprint(self, title: str) -> str:
        base = re.sub("\\s+", " ", (title or "").strip().lower())
        base = re.sub("[^a-z0-9 ]+", "", base)
        return sha1(base.encode("utf-8")).hexdigest()

    def _normalize_title_for_similarity(self, title: str) -> str:
        base = re.sub("\\s+", " ", (title or "").strip().lower())
        return re.sub("[^a-z0-9 ]+", "", base)

    def _published_to_date(self, raw: Any) -> str:
        text = str(raw or "").strip()
        if not text:
            return ""
        if len(text) >= 10 and text[4] == "-" and (text[7] == "-"):
            return text[:10]
        if len(text) >= 8 and text[:8].isdigit():
            return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
        return text[:10]

    def _recency_score(self, published: str) -> float:
        d = self._published_to_date(published)
        if not d:
            return 0.0
        try:
            dt = datetime.strptime(d, "%Y-%m-%d").date()
        except ValueError:
            return 0.0
        delta = (datetime.now(UTC).date() - dt).days
        if delta <= 0:
            return 1.0
        if delta <= 2:
            return 0.7
        if delta <= 7:
            return 0.4
        return 0.0

    def _match_score(self, title: str, terms: dict[str, str]) -> float:
        t = (title or "").lower()
        ticker = (terms.get("ticker") or "").lower()
        fund = (terms.get("fund_name") or "").lower()
        issuer = (terms.get("issuer") or "").lower()
        query_terms = terms.get("query_terms") or []
        if ticker and ticker in t:
            return 1.0
        if fund and fund in t:
            return 0.7
        if issuer and issuer in t:
            return 0.4
        if any(q and q in t for q in query_terms):
            return 0.2
        return 0.0

    def _allowlist_pass(self, domain: str) -> bool:
        if not domain:
            return False
        return any(
            domain == d or domain.endswith(f".{d}") for d in AUTHORITATIVE_ALLOWLIST
        )

    def _build_digest(self, items: list[dict[str, Any]]) -> str:
        if len(items) < 2:
            return "No authoritative news found in the last 7 days for the specified assets."
        top = items[:3]
        loc = (
            ", ".join(sorted({i.get("domain") or "global" for i in top}))
            or "global markets"
        )
        combined_text = " ".join(
            f"{it.get('title', '')} {it.get('summary', '')}".lower() for it in top
        )
        lines = [
            f"Recent coverage shows a market-relevant development around {top[0].get('title', 'the queried assets')}."
        ]

        # Derive simple coverage flags to keep digest wording deterministic.
        has_where = any((it.get("domain") or "").strip() for it in top)
        has_how = any(
            k in combined_text
            for k in (
                "because",
                "after",
                "due to",
                "driven by",
                "triggered",
                "following",
            )
        )
        has_impact = any(
            k in combined_text
            for k in (
                "impact",
                "inflow",
                "outflow",
                "price",
                "volatility",
                "yield",
                "spread",
            )
        )
        if has_where:
            lines.append(f"The activity is reported across {loc}.")
        else:
            lines.append(
                "Unclear from current sources where this development is concentrated."
            )
        if has_how:
            lines.append(
                "Reports describe how the move unfolded through policy, liquidity, or positioning channels."
            )
        else:
            lines.append("Unclear from current sources how the development unfolded.")
        if has_impact:
            lines.append(
                "Reported consequences include measurable repricing and sentiment shifts across related assets."
            )
        else:
            lines.append(
                "Unclear from current sources what the immediate market impact is."
            )
        lines.extend(
            [
                "Cross-asset spillovers appear in sentiment-sensitive and rate-sensitive segments.",
                "Near-term implications are higher event sensitivity and faster reaction to new official releases.",
            ]
        )
        has_driver = any(
            any(
                k in (it.get("title", "") + " " + it.get("summary", "")).lower()
                for k in (
                    "supply chain",
                    "disaster",
                    "geopolitical",
                    "regulatory",
                    "cpi",
                    "jobs",
                    "commodity",
                    "sector",
                )
            )
            for it in top
        )
        if has_driver:
            lines.append(
                "Performance-impact drivers such as regulatory, macro, or sector catalysts are explicitly present in current reporting."
            )
        else:
            lines.append("Unclear from current sources how/where/impact occurred.")
        while len(lines) < 6:
            lines.append(
                "Additional confirmation from primary sources is likely to refine the picture."
            )
        return " ".join(lines[:10])
