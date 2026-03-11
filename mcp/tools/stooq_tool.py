"""P2 real-time price fetcher via stooq.com.

Fetches latest and historical OHLCV from stooq CSV endpoint.
Symbol format: use .US suffix for US stocks/ETFs (e.g. SPY.US, VTI.US).
"""

from __future__ import annotations

import csv
import logging
from datetime import datetime, timezone
from io import StringIO
from typing import Any

import requests

logger = logging.getLogger(__name__)

_STOOQ_BASE = "https://stooq.com/q/d/l/"
_HTTP_TIMEOUT = float(__import__("os").environ.get("MCP_HTTP_TIMEOUT_SECONDS", "8"))


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ensure_us_suffix(symbol: str) -> str:
    """Ensure symbol has .US suffix for US market."""
    s = (symbol or "").strip().upper()
    if not s:
        return "SPY.US"
    if "." not in s:
        return f"{s}.US"
    return s


def get_price(payload: dict) -> dict:
    """Fetch latest price for a symbol from stooq.

    Payload:
        symbol (str): Ticker (e.g. SPY, VTI). .US is appended if missing.

    Returns:
        {
            "symbol": str,
            "price": float,
            "close": float,
            "open": float?,
            "high": float?,
            "low": float?,
            "volume": int?,
            "date": str,
            "timestamp": str,
            "source": "stooq"
        }
        Or {"error": str, "timestamp": str} on failure.
    """
    symbol = (payload.get("symbol") or payload.get("ticker") or "").strip()
    if not symbol:
        return {"error": "Missing required 'symbol'", "timestamp": _now_iso()}

    sym_stooq = _ensure_us_suffix(symbol)
    url = f"{_STOOQ_BASE}?s={sym_stooq}&i=d"

    try:
        resp = requests.get(url, timeout=max(1.0, _HTTP_TIMEOUT))
        resp.raise_for_status()
        text = resp.text
    except Exception as e:
        logger.exception("stooq get_price failed")
        return {"error": str(e), "timestamp": _now_iso()}

    # Parse CSV: Date,Open,High,Low,Close,Volume
    reader = csv.DictReader(StringIO(text))
    rows = list(reader)
    if not rows:
        return {
            "error": f"No data for {sym_stooq}",
            "timestamp": _now_iso(),
        }

    # First row is latest (stooq returns descending by date)
    latest = rows[0]
    try:
        close = float(latest.get("Close", latest.get("close", 0)) or 0)
        price = close
        open_ = latest.get("Open") or latest.get("open")
        high = latest.get("High") or latest.get("high")
        low = latest.get("Low") or latest.get("low")
        vol = latest.get("Volume") or latest.get("volume")
        date_val = latest.get("Date") or latest.get("date", "")

        out: dict[str, Any] = {
            "symbol": sym_stooq,
            "price": price,
            "close": close,
            "date": date_val,
            "timestamp": _now_iso(),
            "source": "stooq",
        }
        if open_ is not None:
            try:
                out["open"] = float(open_)
            except (TypeError, ValueError):
                pass
        if high is not None:
            try:
                out["high"] = float(high)
            except (TypeError, ValueError):
                pass
        if low is not None:
            try:
                out["low"] = float(low)
            except (TypeError, ValueError):
                pass
        if vol is not None:
            try:
                out["volume"] = int(float(vol))
            except (TypeError, ValueError):
                pass
        return out
    except (TypeError, ValueError, KeyError) as e:
        return {"error": f"Parse error: {e}", "timestamp": _now_iso()}
