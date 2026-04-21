"""Websearch pipeline assembly and contracts."""

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Optional

from agents.websearch_helpers import (
    websearch_now_iso,
)
from util.websearch_persistence import persist_websearch_news

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

AUTHORITATIVE_ALLOWLIST = {
    "reuters.com",
    "bloomberg.com",
    "wsj.com",
    "ft.com",
    "cnbc.com",
    "barrons.com",
    "marketwatch.com",
    "sec.gov",
    "federalreserve.gov",
    "ecb.europa.eu",
    "bankofengland.co.uk",
    "bis.org",
    "imf.org",
    "worldbank.org",
    "oecd.org",
    "bls.gov",
    "bea.gov",
    "treasury.gov",
    "nasdaq.com",
    "nyse.com",
    "cboe.com",
    "ice.com",
    "cmegroup.com",
    "spglobal.com",
    "moodys.com",
    "fitchratings.com",
    "finra.org",
    "investing.com",
    "fxstreet.com",
    "coindesk.com",
    "cointelegraph.com",
    "theblock.co",
    "ic3.gov",
    "dataplus.sec.gov",
    "edgar.sec.gov",
}

SOURCE_REGISTRY = [
    {
        "name": "Reuters",
        "domain": "reuters.com",
        "fetch_mode": "rss",
        "coverage": 1.0,
        "reliability": 1.0,
        "relevance": 0.95,
        "efficiency": 0.95,
        "crawl_url": "https://www.reuters.com/world/",
    },
    {
        "name": "Bloomberg",
        "domain": "bloomberg.com",
        "fetch_mode": "rss",
        "coverage": 0.98,
        "reliability": 0.98,
        "relevance": 0.93,
        "efficiency": 0.9,
        "crawl_url": "https://www.bloomberg.com/markets",
    },
    {
        "name": "WSJ",
        "domain": "wsj.com",
        "fetch_mode": "rss",
        "coverage": 0.92,
        "reliability": 0.97,
        "relevance": 0.9,
        "efficiency": 0.88,
        "crawl_url": "https://www.wsj.com/news/markets",
    },
    {
        "name": "Financial Times",
        "domain": "ft.com",
        "fetch_mode": "rss",
        "coverage": 0.9,
        "reliability": 0.97,
        "relevance": 0.89,
        "efficiency": 0.88,
        "crawl_url": "https://www.ft.com/markets",
    },
    {
        "name": "CNBC",
        "domain": "cnbc.com",
        "fetch_mode": "rss",
        "coverage": 0.89,
        "reliability": 0.92,
        "relevance": 0.9,
        "efficiency": 0.91,
        "crawl_url": "https://www.cnbc.com/world/?region=world",
    },
    {
        "name": "SEC",
        "domain": "sec.gov",
        "fetch_mode": "api",
        "coverage": 0.72,
        "reliability": 1.0,
        "relevance": 0.85,
        "efficiency": 0.83,
    },
    {
        "name": "Federal Reserve",
        "domain": "federalreserve.gov",
        "fetch_mode": "api",
        "coverage": 0.7,
        "reliability": 1.0,
        "relevance": 0.83,
        "efficiency": 0.82,
    },
    {
        "name": "BLS",
        "domain": "bls.gov",
        "fetch_mode": "api",
        "coverage": 0.66,
        "reliability": 1.0,
        "relevance": 0.8,
        "efficiency": 0.81,
    },
    {
        "name": "CoinDesk",
        "domain": "coindesk.com",
        "fetch_mode": "rss",
        "coverage": 0.76,
        "reliability": 0.9,
        "relevance": 0.86,
        "efficiency": 0.9,
    },
    {
        "name": "The Block",
        "domain": "theblock.co",
        "fetch_mode": "playwright",
        "coverage": 0.72,
        "reliability": 0.89,
        "relevance": 0.84,
        "efficiency": 0.6,
    },
]


class WebSearchPipelineMixin:
    """Split part for readability."""

    def _normalise_to_schema(
        self,
        symbol: str,
        name: str,
        asset_class: Any,
        static: dict,
        stooq: dict,
        etfdb: dict,
        yahoo: Optional[dict] = None,
        prefer_yahoo_for_price: bool = False,
    ) -> dict[str, Any]:
        """Build standard output schema from merged source results. Includes stooq and yahoo when available."""
        source: dict[str, str] = {}
        if static:
            source["static"] = "FinanceDatabase"

        # Pick a primary price source while retaining provenance metadata.
        stooq_ok = stooq and "error" not in stooq
        yahoo_ok = yahoo and "error" not in yahoo
        yahoo_has_price = yahoo_ok and (
            (yahoo or {}).get("price") is not None
            or (yahoo or {}).get("close") is not None
        )
        if prefer_yahoo_for_price and yahoo_has_price:
            price_data = yahoo or {}
            source["price"] = "yahoo"
            if stooq_ok:
                source["price_stooq"] = "stooq"
        elif stooq_ok:
            price_data = stooq
            source["price"] = "stooq"
        elif yahoo_ok:
            price_data = yahoo or {}
            if yahoo_has_price:
                source["price"] = "yahoo"
        else:
            price_data = {}
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

        # Coerce numeric fields defensively; keep None when parsing fails.
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
            "timestamp": websearch_now_iso(),
        }
        # Preserve source timestamps so freshness does not depend on local processing time.
        price_timestamp = None
        for candidate in (
            (price_data or {}).get("timestamp"),
            (stooq or {}).get("timestamp"),
            (yahoo or {}).get("timestamp"),
        ):
            if isinstance(candidate, str) and candidate.strip():
                price_timestamp = candidate.strip()
                break
        fundamentals_timestamp = None
        for candidate in (
            (etfdb or {}).get("timestamp"),
            (yahoo or {}).get("timestamp"),
        ):
            if isinstance(candidate, str) and candidate.strip():
                fundamentals_timestamp = candidate.strip()
                break
        if price_timestamp:
            out["price_timestamp"] = price_timestamp
        if fundamentals_timestamp:
            out["fundamentals_timestamp"] = fundamentals_timestamp
        if price_yahoo is not None:
            out["price_yahoo"] = price_yahoo
        if yahoo_raw is not None:
            out["yahoo_fundamentals_raw"] = yahoo_raw
        return out

    def _augment_websearch_contract(
        self, reply_content: dict[str, Any]
    ) -> dict[str, Any]:
        """Attach freshness/source-conflict metadata for planner contract."""
        out = dict(reply_content)
        nf = out.get("normalized_fund")
        rows = nf if isinstance(nf, list) else []
        now_utc = datetime.now(UTC)

        def _parse_iso(ts: Any) -> Optional[datetime]:
            if not isinstance(ts, str) or not ts.strip():
                return None
            raw = ts.strip().replace("Z", "+00:00")
            try:
                dt = datetime.fromisoformat(raw)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=UTC)
                return dt.astimezone(UTC)
            except ValueError:
                return None

        price_is_fresh = False
        fundamentals_is_fresh = False
        # Compute freshness from source timestamps, not local assembly timestamp.
        for rec in rows:
            if not isinstance(rec, dict):
                continue
            price_dt = _parse_iso(rec.get("price_timestamp"))
            if price_dt is not None:
                price_age_min = (now_utc - price_dt).total_seconds() / 60.0
                price_is_fresh = price_is_fresh or (price_age_min <= 15.0)
            fundamentals_dt = _parse_iso(rec.get("fundamentals_timestamp"))
            if fundamentals_dt is not None:
                fundamentals_age_min = (now_utc - fundamentals_dt).total_seconds() / 60.0
                fundamentals_is_fresh = fundamentals_is_fresh or (
                    fundamentals_age_min <= 90.0 * 24.0 * 60.0
                )
        out["freshness"] = {
            "price_is_fresh": price_is_fresh,
            "fundamentals_is_fresh": fundamentals_is_fresh,
        }

        # Bubble up conflict decisions so planner can cite source arbitration.
        source_conflicts: list[dict[str, Any]] = []
        for rec in rows:
            if not isinstance(rec, dict):
                continue
            conflict = rec.get("conflict_resolution")
            if not isinstance(conflict, dict):
                continue
            source_conflicts.append(
                {
                    "symbol": rec.get("symbol"),
                    "chosen_source": conflict.get("chosen_source"),
                    "reason": conflict.get("reason"),
                }
            )
        out["source_conflicts"] = source_conflicts
        return out

    def _run_parallel_flow(self, content: dict) -> dict[str, Any]:
        """Query all sources in parallel: Financial Data + News Search. Merge and return reply_content."""
        sr = content.get("symbol_resolution")
        by_tool: dict[str, Any] | None = None
        if isinstance(sr, dict) and int(sr.get("schema_version", 0)) >= 1:
            bt = sr.get("by_tool")
            by_tool = bt if isinstance(bt, dict) else None
        symbols, static_matches = self._resolve_symbols(content)
        raw_query = (
            content.get("query")
            or content.get("fund")
            or content.get("symbol")
            or "AAPL"
        )
        query = raw_query.strip() if isinstance(raw_query, str) else str(raw_query).strip()
        include_etfdb = True

        # Apply planner symbol-resolution hints before launching downstream calls.
        if (
            isinstance(sr, dict)
            and sr.get("status") == "resolved"
            and isinstance(sr.get("listings"), list)
            and sr["listings"]
        ):
            first = sr["listings"][0]
            if isinstance(first, dict):
                st = (first.get("symbol_type") or "").strip().lower()
                if st == "equities":
                    include_etfdb = False
                if by_tool:
                    primary_sym = first.get("symbol_yahoo") or first.get(
                        "symbol_compact"
                    )
                    if primary_sym:
                        ps = str(primary_sym).strip()
                        symbols = [ps] + [s for s in symbols if s.upper() != ps.upper()]
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
        financial_result: dict[str, Any] = {}
        news_data: tuple[list[dict], list[dict], list[dict]] = ([], [], [])

        def do_financial() -> dict[str, Any]:
            all_results: dict[str, dict] = {}
            with ThreadPoolExecutor(max_workers=4) as ex:
                futures = {
                    ex.submit(
                        self._fetch_all_sources_for_symbol,
                        s,
                        by_tool,
                        include_etfdb,
                        sr if isinstance(sr, dict) else None,
                    ): s
                    for s in symbols[:3]
                }
                for fut in as_completed(futures):
                    sym = futures[fut]
                    try:
                        all_results[sym] = fut.result()
                    except Exception as e:
                        logger.warning("parallel fetch failed for %s: %s", sym, e)
                        all_results[sym] = {
                            "stooq": {},
                            "yahoo": {},
                            "etfdb": {},
                            "market_data": {},
                            "sentiment": {},
                            "regulatory": {},
                        }
            return self._merge_financial_results(
                all_results,
                symbols,
                static_by_sym,
                sr if isinstance(sr, dict) else None,
            )

        def do_news() -> tuple[list[dict], list[dict], list[dict]]:
            return self._fetch_news_sources(str(query)[:200], symbol, days, by_tool)

        with ThreadPoolExecutor(max_workers=2) as ex:
            fut_fin = ex.submit(do_financial)
            fut_news = ex.submit(do_news)
            try:
                financial_result = fut_fin.result()
            except Exception as e:
                logger.warning("financial fetch failed: %s", e)
                financial_result = {
                    "normalized_fund": [],
                    "market_data": {"timestamp": websearch_now_iso()},
                    "sentiment": {"timestamp": websearch_now_iso()},
                    "regulatory": {"timestamp": websearch_now_iso()},
                }
            try:
                news_data = fut_news.result()
            except Exception as e:
                logger.debug("news fetch failed: %s", e)

        # Build query terms once for ranking/coverage scoring.
        query_terms = {
            "ticker": symbol,
            "fund_name": str(content.get("fund") or ""),
            "issuer": str(content.get("issuer") or ""),
            "query_terms": [
                w.lower() for w in re.findall("[A-Za-z]{3,}", str(query))[:10]
            ],
        }
        merged_items = self._normalize_and_merge_news(
            news_data[0], news_data[1], news_data[2], query_terms
        )
        news_list, citations, citation_rows = self._build_news_with_citations(
            merged_items
        )
        llm_news_fallback_used = False

        # Use LLM-generated news only when retrieval produced no usable items.
        if not news_list and self._llm_client:
            llm_news, llm_citations, llm_rows = self._llm_news_fallback(
                str(query)[:200], symbol
            )
            if llm_news:
                news_list = llm_news
                citations = llm_citations
                citation_rows = llm_rows
                llm_news_fallback_used = True
                logger.info(
                    "agent.websearcher.news_llm_fallback symbol=%s news_count=%s",
                    symbol,
                    len(news_list),
                )
        logger.info(
            "agent.websearcher.news news_count=%s citations_count=%s",
            len(news_list),
            len(citations),
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
        financial_result["news_items"] = news_list
        financial_result["citation_items"] = citation_rows
        financial_result["news_digest"] = self._build_digest(news_list)
        financial_result["news_timestamp"] = websearch_now_iso()
        if news_list:
            try:
                persist_result = persist_websearch_news(
                    news_items=news_list,
                    symbols_mentioned=symbols[:3],
                    search_timestamp=financial_result["news_timestamp"],
                )
                milvus_res = persist_result.get("milvus")
                if isinstance(milvus_res, dict) and milvus_res.get("status") == "error":
                    logger.warning(
                        "websearch persistence milvus upsert failed: %s",
                        milvus_res.get("error", "unknown"),
                    )
            except Exception as e:
                logger.debug("websearch persistence failed: %s", e)

        # Mark synthetic/low-confidence news so downstream components can caveat it.
        if llm_news_fallback_used or (
            news_list
            and (not citations)
            and any(
                isinstance(it, dict) and (it.get("source") or "").lower() == "llm"
                for it in news_list
            )
        ):
            financial_result["news_confidence"] = "low"
            financial_result["news_synthetic"] = True
        return financial_result
