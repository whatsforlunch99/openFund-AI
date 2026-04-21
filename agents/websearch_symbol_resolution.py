"""Websearch symbol resolution and fallback helpers."""

import json
import logging
import re
from typing import TYPE_CHECKING, Any

from a2a.message_bus import MessageBus
from agents.websearch_helpers import (
    extract_price_from_text,
    websearch_now_iso,
)
from util.agent_heuristics import get_websearcher_heuristics
from util.symbol_query_extract import (
    extract_symbol_from_query,
    merge_catalog_symbols_for_query,
)
from util.symbol_resolution_deterministic import apply_ticker_aliases

if TYPE_CHECKING:
    from llm.base import LLMClient

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


class WebSearchSymbolResolutionMixin:
    """Split part for readability."""

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
        return extract_symbol_from_query(raw)

    def _resolve_symbols(self, content: dict) -> tuple[list[str], list[dict]]:
        """Resolve symbol(s) from REQUEST content. Returns (symbols, static_matches).

        If fund/symbol looks like a ticker (1-5 chars), use it.
        If planner symbol_resolution is resolved, use listing symbols (skip fund_catalog).
        Else call fund_catalog_tool.search(query); if matches, use first symbol(s).
        Fallback: _normalize_symbol heuristics.
        """
        sr = content.get("symbol_resolution")
        if isinstance(sr, dict) and sr.get("status") == "resolved":
            lst = sr.get("listings") or []
            syms: list[str] = []
            seen: set[str] = set()
            for listing in lst[:5]:
                if not isinstance(listing, dict):
                    continue
                s = listing.get("symbol_yahoo") or listing.get("symbol_compact")
                if isinstance(s, str) and s.strip():
                    u = apply_ticker_aliases(s.strip().upper())
                    if u not in seen:
                        seen.add(u)
                        syms.append(u)
            if syms:
                return (syms[:3], [])
        query = (content.get("query") or "").strip()
        fund = (content.get("fund") or content.get("symbol") or "").strip()
        fund_upper = fund.upper().split(".")[0] if fund else ""
        bl = get_websearcher_heuristics().ticker_blocklist
        if (
            fund
            and re.match("^[A-Z]{1,5}(\\.[A-Z]{2})?$", fund.upper())
            and (fund_upper not in bl)
        ):
            return ([fund_upper], [])
        if fund_upper in bl:
            fund = ""
        if self.mcp_client and query:
            try:
                reg = self.mcp_client.get_registered_tool_names() or []
                if "fund_catalog_tool.search" in reg:
                    r = self.mcp_client.call_tool(
                        "fund_catalog_tool.search", {"query": query, "limit": 5}
                    )
                    matches = (r or {}).get("matches") or []
                    if matches:
                        syms = [m["symbol"] for m in matches if m.get("symbol")]
                        syms = merge_catalog_symbols_for_query(syms, query)
                        return (syms[:3], matches)
            except Exception:
                pass
        raw = query or fund or get_websearcher_heuristics().default_fallback_symbol
        return ([self._normalize_symbol(raw)], [])

    def _has_price_conflict(self, rec: dict) -> bool:
        """True if stooq and yahoo both have price and differ by >1%."""
        pr = rec.get("price")
        py = rec.get("price_yahoo")
        if pr is None or py is None:
            return False
        try:
            a, b = (float(pr), float(py))
            if a <= 0 or b <= 0:
                return False
            rel_diff = abs(a - b) / min(a, b)
            return rel_diff > 0.01
        except (TypeError, ValueError):
            return False

    def _resolve_conflict_with_llm(
        self, symbol: str, price_stooq: float, price_yahoo: float
    ) -> dict[str, Any]:
        """Ask LLM which source is more credible; return chosen_source, chosen_value, reason."""
        from llm.prompts import WEBSEARCHER_CONFLICT_RESOLUTION_SYSTEM

        conflict = {
            "symbol": symbol,
            "stooq": {"price": price_stooq, "source": "stooq"},
            "yahoo": {"price": price_yahoo, "source": "yahoo"},
        }
        user_content = f"Conflicting data:\n{json.dumps(conflict, indent=2)}"
        out = (
            self._llm_client.complete(
                WEBSEARCHER_CONFLICT_RESOLUTION_SYSTEM, user_content
            )
            or ""
        )
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
            if isinstance(rec, dict) and (
                rec.get("price") is not None
                or rec.get("price_yahoo") is not None
                or rec.get("llm_fallback_content")
            ):
                return False
        for k in ("market_data", "sentiment", "regulatory"):
            v = reply_content.get(k)
            if isinstance(v, dict) and (not v.get("error")):
                c = v.get("content") or ""
                if isinstance(c, str) and c.strip():
                    return False
        return True

    def _llm_data_search_fallback(self, query: str, symbol: str) -> dict[str, Any]:
        """Call LLM to provide data when all tools failed. Returns reply_content shape with source=llm."""
        from llm.prompts import WEBSEARCHER_LLM_FALLBACK_SYSTEM

        user_content = f"Query: {query}\nSymbol/topic: {symbol}"
        out = (
            self._llm_client.complete(WEBSEARCHER_LLM_FALLBACK_SYSTEM, user_content)
            or ""
        )
        price = extract_price_from_text(out)
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
            "timestamp": websearch_now_iso(),
            "llm_fallback": True,
            "llm_fallback_content": out[:2000] if out else "",
        }
        return {
            "normalized_fund": [rec],
            "market_data": {"timestamp": websearch_now_iso()},
            "sentiment": {"timestamp": websearch_now_iso()},
            "regulatory": {"timestamp": websearch_now_iso()},
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
                parts.append(
                    f"{rec.get('symbol', '?')}: [LLM fallback] {rec['llm_fallback_content'][:500]}"
                )
                continue
            if not isinstance(rec, dict):
                continue
            sym = rec.get("symbol") or "?"
            pr = rec.get("price")
            py = rec.get("price_yahoo")
            src = rec.get("source") if isinstance(rec.get("source"), dict) else {}
            price_src = (
                (src.get("price") or "quote").strip()
                if isinstance(src, dict)
                else "quote"
            )
            if pr is not None:
                try:
                    line = f"{sym}: ${float(pr):.2f} ({price_src})"
                    if py is not None:
                        try:
                            if abs(float(pr) - float(py)) > 0.0001:
                                line += f", Yahoo ${float(py):.2f}"
                        except (TypeError, ValueError):
                            line += f", Yahoo ${float(py):.2f}"
                    parts.append(line)
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
