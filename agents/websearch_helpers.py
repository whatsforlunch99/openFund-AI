"""WebSearcher pure helpers: by_tool routing, Yahoo summary, news intent, price parsing."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Optional

from util.agent_heuristics import get_websearcher_heuristics


def query_implies_news_intent(query: str) -> bool:
    """True when the user likely wants headlines/sentiment (not pure price/history)."""
    q = (query or "").lower()
    if not q.strip():
        return False
    hints = (
        "news",
        "headline",
        "article",
        "story",
        "sentiment",
        "rumor",
        "rumour",
        "sec filing",
        "filing",
        "earnings",
        "regulatory",
        "regulation",
        "macro",
        "breaking",
        "outlook",
        "forecast",
    )
    return any(h in q for h in hints)


def alpha_vantage_cooldown_message() -> str | None:
    """If AV is in rate-limit cooldown, return skip message for any AV-backed market_tool call."""
    try:
        from openfund_mcp.tools.market import routing as mt

        return mt._av_rate_limit_error("market_tool.get_news")
    except Exception:
        return None


def prefer_yahoo_price_first(
    symbol_resolution: dict[str, Any] | None, symbol: str
) -> bool:
    """US-style equities: prefer Yahoo chart price before Stooq when merging quotes."""
    if isinstance(symbol_resolution, dict) and symbol_resolution.get("status") == "resolved":
        L0 = (symbol_resolution.get("listings") or [None])[0]
        if isinstance(L0, dict):
            st = (L0.get("symbol_type") or "").strip().lower()
            if st == "equities":
                return True
    sym = (symbol or "").strip().upper()
    if 1 <= len(sym) <= 5 and sym.isalpha():
        return True
    return False


def get_known_index_symbols() -> frozenset[str]:
    """Index symbols (not ETFs); ETFdb may skip these."""
    return get_websearcher_heuristics().known_index_symbols


def websearch_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def by_tool_should_call(by_tool: dict[str, Any] | None, tool_id: str) -> bool:
    """If planner sent symbol_resolution.by_tool, honor skip; missing entry means call (legacy)."""
    if not by_tool or not isinstance(by_tool, dict):
        return True
    entry = by_tool.get(tool_id)
    if entry is None:
        return True
    if not isinstance(entry, dict):
        return True
    return entry.get("action") != "skip"


def by_tool_symbol(by_tool: dict[str, Any] | None, tool_id: str, default_symbol: str) -> str:
    """Symbol string for MCP payload when action is call."""
    if not by_tool or not isinstance(by_tool, dict):
        return default_symbol
    entry = by_tool.get(tool_id)
    if isinstance(entry, dict) and entry.get("action") == "call":
        sym = entry.get("symbol")
        if isinstance(sym, str) and sym.strip():
            return sym.strip()
    return default_symbol


def ticker_base(sym: str) -> str:
    """Compare tickers loosely: same root before exchange suffix (e.g. 000002.SZ vs 000002)."""
    s = (sym or "").strip().upper()
    if "." in s:
        return s.split(".", 1)[0]
    return s


def pin_matches_iteration(pinned: str, iteration: str) -> bool:
    """True if planner-pinned symbol refers to the same security as the parallel-loop symbol."""
    p = (pinned or "").strip().upper()
    i = (iteration or "").strip().upper()
    if not i:
        return True
    if p == i:
        return True
    return ticker_base(p) == ticker_base(i) and bool(ticker_base(i))


def by_tool_symbol_for_iteration(
    by_tool: dict[str, Any] | None, tool_id: str, iteration_symbol: str
) -> str:
    """Use by_tool's symbol only when it matches this iteration; else use iteration."""
    it = (iteration_symbol or "").strip()
    pinned = by_tool_symbol(by_tool, tool_id, it)
    if pin_matches_iteration(pinned, it):
        return pinned
    return it


def extract_price_from_text(text: str) -> Optional[float]:
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


def summarize_yahoo_fundamental(yahoo_res: Any) -> dict[str, Any]:
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
