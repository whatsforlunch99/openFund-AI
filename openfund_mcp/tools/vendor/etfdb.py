"""P3 ETF fundamentals fetcher via ETFdb.com.

Fetches expense ratio, AUM, holdings from ETFdb HTML pages.
ETFdb may return 403; agent falls back to other sources (P1, P2, market_tool).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

import requests

logger = logging.getLogger(__name__)

_ETFDB_BASE = "https://etfdb.com/etf/"
_HTTP_TIMEOUT = float(__import__("os").environ.get("MCP_HTTP_TIMEOUT_SECONDS", "10"))
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Referer": "https://etfdb.com/",
    "DNT": "1",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_expense_ratio(html: str) -> float | None:
    """Extract expense ratio from HTML (e.g. 0.03% -> 0.0003)."""
    # Common patterns: "0.03%" or "Expense Ratio</dt><dd>0.03%"
    m = re.search(r"expense\s*ratio[:\s]*</?[^>]*>?\s*(\d+\.?\d*)%", html, re.I)
    if m:
        try:
            return float(m.group(1)) / 100.0
        except (TypeError, ValueError):
            pass
    m = re.search(r"(\d+\.?\d*)\s*%\s*</dd>", html)
    if m:
        try:
            return float(m.group(1)) / 100.0
        except (TypeError, ValueError):
            pass
    return None


def _parse_aum(html: str) -> float | None:
    """Extract AUM in dollars (e.g. $350B -> 350e9)."""
    # Patterns: $350.5 Billion, $350B, $1.2 Trillion
    m = re.search(
        r"\$\s*([\d,]+\.?\d*)\s*(B|Billion|T|Trillion|M|Million)",
        html.replace(",", ""),
        re.I,
    )
    if m:
        try:
            val = float(m.group(1).replace(",", ""))
            unit = (m.group(2) or "").upper()[0]
            if unit == "T":
                return val * 1e12
            if unit == "B":
                return val * 1e9
            return val * 1e6
        except (TypeError, ValueError):
            pass
    return None


def _parse_holdings_top(html: str, limit: int = 10) -> list[dict]:
    """Extract top holdings (symbol, weight) from HTML."""
    out = []
    # Look for holding rows in tables
    pat = re.compile(
        r'<[^>]+>(?:<[^>]+>)?([A-Z]{1,5})?(?:</[^>]+>)*\s*</[^>]+>\s*'
        r'(?:<[^>]+>)*\s*(\d+\.?\d*)\s*%',
        re.I,
    )
    for m in pat.finditer(html):
        sym = (m.group(1) or "").strip()
        w = m.group(2)
        if sym and w and len(out) < limit:
            try:
                out.append({"symbol": sym, "weight_pct": float(w)})
            except (TypeError, ValueError):
                pass
    return out


def get_fund_data(payload: dict) -> dict:
    """Fetch ETF fundamentals from ETFdb.

    Payload:
        symbol (str): Ticker (e.g. SPY, VTI).

    Returns:
        {
            "symbol": str,
            "expense_ratio": float?,
            "aum": float?,
            "holdings_top10": [{"symbol": str, "weight_pct": float}, ...],
            "sector_exposure": dict?,
            "timestamp": str,
            "source": "ETFdb"
        }
        Or {"error": str, "timestamp": str} on failure.
    """
    symbol = (payload.get("symbol") or payload.get("ticker") or "").strip().upper()
    if not symbol:
        return {"error": "Missing required 'symbol'", "timestamp": _now_iso()}

    url = f"{_ETFDB_BASE}{symbol}/"

    try:
        session = requests.Session()
        session.headers.update(_HEADERS)
        resp = session.get(url, timeout=max(1.0, _HTTP_TIMEOUT))
        resp.raise_for_status()
        html = resp.text
        expense = _parse_expense_ratio(html)
        aum = _parse_aum(html)
        holdings = _parse_holdings_top(html, 10)
        return {
            "symbol": symbol,
            "expense_ratio": expense,
            "aum": aum,
            "holdings_top10": holdings,
            "sector_exposure": {},
            "timestamp": _now_iso(),
            "source": "ETFdb",
        }
    except Exception as e:
        logger.warning("ETFdb failed for %s: %s", symbol, e)
        return {
            "symbol": symbol,
            "error": str(e),
            "timestamp": _now_iso(),
        }
