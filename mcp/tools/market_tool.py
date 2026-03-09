"""Market and web search via Tavily (MCP tool).

Also provides company fundamentals, financials, insider transactions, and news (Alpha Vantage, Finnhub).
Contains vendor config, Alpha Vantage HTTP/rate-limit/CSV helpers, _av/_finnhub implementations, and _route_*.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from io import StringIO
from typing import Optional

import pandas as pd
import requests
from dateutil.relativedelta import relativedelta

logger = logging.getLogger(__name__)


# --- Vendor config ---


def get_market_vendor() -> str:
    """Return 'alpha_vantage' or 'finnhub'. Default alpha_vantage; invalid/unset -> alpha_vantage."""
    v = (os.getenv("MCP_MARKET_VENDOR") or "alpha_vantage").strip().lower()
    return v if v in ("alpha_vantage", "finnhub") else "alpha_vantage"


def get_indicator_vendor() -> str:
    """Return 'alpha_vantage'. Default alpha_vantage; invalid/unset -> alpha_vantage."""
    v = (os.getenv("MCP_INDICATOR_VENDOR") or "alpha_vantage").strip().lower()
    return v if v == "alpha_vantage" else "alpha_vantage"


def get_data_cache_dir() -> str | None:
    """Return MCP_DATA_CACHE_DIR if set, else None (no cache)."""
    return os.getenv("MCP_DATA_CACHE_DIR") or None


# --- Alpha Vantage common ---

API_BASE_URL = "https://www.alphavantage.co/query"
_HTTP_TIMEOUT_SECONDS = float(os.getenv("MCP_HTTP_TIMEOUT_SECONDS", "8"))
_AV_RATE_LIMIT_COOLDOWN_SECONDS = int(
    os.getenv("ALPHA_VANTAGE_RATE_LIMIT_COOLDOWN_SECONDS", "1800")
)
_AV_RATE_LIMITED_UNTIL = 0.0
_AV_RATE_LIMIT_REASON = ""


def get_api_key() -> str:
    """Retrieve the API key for Alpha Vantage from environment variables."""
    api_key = os.getenv("ALPHA_VANTAGE_API_KEY")
    if not api_key:
        raise ValueError("ALPHA_VANTAGE_API_KEY environment variable is not set.")
    return api_key


def _has_alpha_vantage_key() -> bool:
    """Return True if ALPHA_VANTAGE_API_KEY is set."""
    return bool((os.getenv("ALPHA_VANTAGE_API_KEY") or "").strip())


# --- Finnhub ---

FINNHUB_BASE = "https://finnhub.io/api/v1"


def get_finnhub_api_key() -> str:
    """Return Finnhub API key from env. Raises if not set."""
    key = (os.getenv("FINNHUB_API_KEY") or "").strip()
    if not key:
        raise ValueError("FINNHUB_API_KEY environment variable is not set.")
    return key


def _has_finnhub_key() -> bool:
    return bool((os.getenv("FINNHUB_API_KEY") or "").strip())


def format_datetime_for_api(date_input: str | datetime) -> str:
    """Convert date to YYYYMMDDTHHMM format required by Alpha Vantage API."""
    if isinstance(date_input, str):
        if len(date_input) == 13 and "T" in date_input:
            return date_input
        try:
            dt = datetime.strptime(date_input, "%Y-%m-%d")
            return dt.strftime("%Y%m%dT0000")
        except ValueError:
            try:
                dt = datetime.strptime(date_input, "%Y-%m-%d %H:%M")
                return dt.strftime("%Y%m%dT%H%M")
            except ValueError:
                raise ValueError(f"Unsupported date format: {date_input}") from None
    if isinstance(date_input, datetime):
        return date_input.strftime("%Y%m%dT%H%M")
    raise ValueError(f"Date must be string or datetime, got {type(date_input)}")


class AlphaVantageRateLimitError(Exception):
    """Raised when Alpha Vantage API rate limit is exceeded."""


def _mark_av_rate_limited(reason: str) -> None:
    """Mark Alpha Vantage as rate limited for a cooldown period."""
    global _AV_RATE_LIMITED_UNTIL, _AV_RATE_LIMIT_REASON
    _AV_RATE_LIMITED_UNTIL = max(
        _AV_RATE_LIMITED_UNTIL,
        time.time() + max(1, _AV_RATE_LIMIT_COOLDOWN_SECONDS),
    )
    _AV_RATE_LIMIT_REASON = (reason or "Alpha Vantage rate limit hit").strip()


def _av_rate_limit_error(tool_name: str) -> str | None:
    """Return a skip error when AV is still in cooldown; otherwise None."""
    if time.time() >= _AV_RATE_LIMITED_UNTIL:
        return None
    remaining = int(max(1, _AV_RATE_LIMITED_UNTIL - time.time()))
    return (
        f"{tool_name} skipped: Alpha Vantage rate limit cooldown active "
        f"({remaining}s remaining). Last reason: {_AV_RATE_LIMIT_REASON}"
    )


def _make_api_request(function_name: str, params: dict) -> str:
    """Make API request and return response text. Raises AlphaVantageRateLimitError on rate limit."""
    api_params = params.copy()
    api_params.update(
        {
            "function": function_name,
            "apikey": get_api_key(),
        }
    )
    response = requests.get(
        API_BASE_URL,
        params=api_params,
        timeout=max(1.0, _HTTP_TIMEOUT_SECONDS),
    )
    response.raise_for_status()
    response_text = response.text

    try:
        response_json = json.loads(response_text)
        if "Information" in response_json:
            info_message = response_json["Information"]
            if (
                "rate limit" in info_message.lower()
                or "api key" in info_message.lower()
                or "call frequency" in info_message.lower()
                or "premium" in info_message.lower()
            ):
                _mark_av_rate_limited(info_message)
                raise AlphaVantageRateLimitError(
                    f"Alpha Vantage rate limit exceeded: {info_message}"
                )
    except json.JSONDecodeError:
        pass

    return response_text


def _filter_csv_by_date_range(csv_data: str, start_date: str, end_date: str) -> str:
    """Filter CSV to rows within the given date range."""
    if not csv_data or not csv_data.strip():
        return csv_data
    try:
        df = pd.read_csv(StringIO(csv_data))
        date_col = df.columns[0]
        df[date_col] = pd.to_datetime(df[date_col])
        start_dt = pd.to_datetime(start_date)
        end_dt = pd.to_datetime(end_date)
        filtered_df = df[(df[date_col] >= start_dt) & (df[date_col] <= end_dt)]
        return filtered_df.to_csv(index=False)
    except Exception as e:
        logger.warning("Failed to filter CSV by date range: %s", e)
        return csv_data


def _alpha_vantage_information_message(raw: str) -> str | None:
    """Return Alpha Vantage 'Information' message when present in a JSON response body."""
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    info = parsed.get("Information")
    return info if isinstance(info, str) and info.strip() else None


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- Stubs (Tavily / Yahoo) ---


def fetch(_fund_or_symbol: str) -> dict:
    """
    Fetch market data for a fund or symbol (Yahoo and/or Tavily).

    Args:
        fund_or_symbol: Fund or ticker symbol.

    Returns:
        Market data dict; must include 'timestamp'. Config: TAVILY_API_KEY, YAHOO_BASE_URL.
    """
    raise NotImplementedError


def fetch_bulk(_symbols: list[str]) -> dict:
    """
    Fetch market data for multiple symbols.

    Args:
        symbols: List of symbols.

    Returns:
        Dict keyed by symbol; each value must include 'timestamp'.
    """
    raise NotImplementedError


def search_web(query: str) -> list[dict]:
    """
    Web search via Tavily (e.g. regulatory, sentiment).

    Args:
        query: Search query.

    Returns:
        List of results; each must include 'timestamp'.
    """
    raise NotImplementedError


# --- Alpha Vantage implementations ---


def _av_stock_csv(symbol: str, start_date: str, end_date: str) -> str:
    """Return daily OHLCV (adjusted) CSV from Alpha Vantage, filtered to date range."""

    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    today = datetime.now()
    days_from_today_to_start = (today - start_dt).days
    outputsize = "compact" if days_from_today_to_start < 100 else "full"
    params = {
        "symbol": symbol,
        "outputsize": outputsize,
        "datatype": "csv",
    }
    response = _make_api_request("TIME_SERIES_DAILY_ADJUSTED", params)
    return _filter_csv_by_date_range(response, start_date, end_date)


def get_stock_data_av(symbol: str, start_date: str, end_date: str) -> dict:
    """
    Historical OHLCV for a symbol (Alpha Vantage).

    Returns:
        {"content": str, "timestamp": str} or {"error": str}.
    """
    try:
        out = _av_stock_csv(symbol, start_date, end_date)
        info = _alpha_vantage_information_message(out)
        if info:
            return _wrap_content(f"Market data unavailable for {symbol}: {info}")
        return _wrap_content(out)
    except AlphaVantageRateLimitError:
        raise
    except Exception as e:
        logger.exception("get_stock_data_av failed")
        return {"error": str(e)}


def get_fundamentals_av(symbol: str) -> dict:
    """Company overview/fundamentals (Alpha Vantage)."""
    try:
        out = _make_api_request("OVERVIEW", {"symbol": symbol})
        info = _alpha_vantage_information_message(out)
        if info:
            return _wrap_content(f"Fundamentals unavailable for {symbol}: {info}")
        return _wrap_content(out)
    except AlphaVantageRateLimitError:
        raise
    except Exception as e:
        logger.exception("get_fundamentals_av failed")
        return {"error": str(e)}


def get_fundamentals_finnhub(symbol: str) -> dict:
    """Company profile + basic metrics (Finnhub)."""
    try:
        symbol = (symbol or "").strip().upper()
        if not symbol:
            return {"error": "Missing required 'symbol'"}
        key = get_finnhub_api_key()
        profile_resp = requests.get(
            f"{FINNHUB_BASE}/stock/profile2",
            params={"symbol": symbol, "token": key},
            timeout=max(1.0, _HTTP_TIMEOUT_SECONDS),
        )
        profile_resp.raise_for_status()
        metric_resp = requests.get(
            f"{FINNHUB_BASE}/stock/metric",
            params={"symbol": symbol, "metric": "all", "token": key},
            timeout=max(1.0, _HTTP_TIMEOUT_SECONDS),
        )
        metric_resp.raise_for_status()
        payload = {
            "symbol": symbol,
            "profile": profile_resp.json(),
            "metric": metric_resp.json(),
        }
        return _wrap_content(json.dumps(payload))
    except ValueError as e:
        return {"error": str(e)}
    except Exception as e:
        logger.exception("get_fundamentals_finnhub failed")
        return {"error": str(e)}


def get_stock_data_finnhub(symbol: str, start_date: str, end_date: str) -> dict:
    """
    Historical OHLCV for a symbol (Finnhub stock/candle). Uses FINNHUB_API_KEY.
    Free tier may return 403 for candles; quote and profile2 work on free tier.
    """
    try:
        symbol = (symbol or "").strip().upper()
        if not symbol:
            return {"error": "Missing required 'symbol'"}
        if not start_date or not end_date:
            return {"error": "Missing required 'start_date' or 'end_date'"}
        key = get_finnhub_api_key()
        from_ts = int(
            datetime.strptime(start_date.strip()[:10], "%Y-%m-%d").timestamp()
        )
        to_ts = int(datetime.strptime(end_date.strip()[:10], "%Y-%m-%d").timestamp())
        r = requests.get(
            f"{FINNHUB_BASE}/stock/candle",
            params={
                "symbol": symbol,
                "resolution": "D",
                "from": from_ts,
                "to": to_ts,
                "token": key,
            },
            timeout=max(1.0, _HTTP_TIMEOUT_SECONDS),
        )
        if r.status_code == 403:
            return {
                "content": "Finnhub historical candles returned 403 (forbidden). "
                "Stock candles may require a paid plan on Finnhub. "
                "Use MCP_MARKET_VENDOR=alpha_vantage for historical data.",
                "timestamp": _now_iso(),
            }
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, dict) or data.get("s") != "ok" or not data.get("t"):
            return {
                "content": f"No data found for {symbol} between {start_date} and {end_date}",
                "timestamp": _now_iso(),
            }
        t = data["t"]
        o = data.get("o", [])
        h = data.get("h", [])
        l_ = data.get("l", [])
        c = data.get("c", [])
        v = data.get("v", [])
        rows = []
        for i in range(len(t)):
            ts = t[i]
            dt = datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d")
            rows.append(
                f"{dt},{o[i] if i < len(o) else ''},{h[i] if i < len(h) else ''},"
                f"{l_[i] if i < len(l_) else ''},{c[i] if i < len(c) else ''},{v[i] if i < len(v) else ''}"
            )
        header = (
            f"# Stock data for {symbol} from {start_date} to {end_date}\n"
            f"# Total records: {len(rows)}\n# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            "Date,Open,High,Low,Close,Volume\n"
        )
        return _wrap_content(header + "\n".join(rows))
    except ValueError as e:
        return {"error": str(e)}
    except Exception as e:
        logger.exception("get_stock_data_finnhub failed")
        return {"error": str(e)}


def get_balance_sheet_av(
    symbol: str, freq: str = "quarterly", _curr_date: Optional[str] = None
) -> dict:
    """Balance sheet (Alpha Vantage). Passes report=annual|quarterly when freq is set. Returns {"content": str, "timestamp": str} or {"error": str}."""
    try:
        params: dict = {"symbol": symbol}
        if (freq or "").lower() in ("annual", "quarterly"):
            params["report"] = freq.lower()
        out = _make_api_request("BALANCE_SHEET", params)
        return _wrap_content(out)
    except AlphaVantageRateLimitError:
        raise
    except Exception as e:
        logger.exception("get_balance_sheet_av failed")
        return {"error": str(e)}


def get_cashflow_av(
    symbol: str, freq: str = "quarterly", _curr_date: Optional[str] = None
) -> dict:
    """Cash flow (Alpha Vantage). Passes report=annual|quarterly when freq is set. Returns {"content": str, "timestamp": str} or {"error": str}."""
    try:
        params: dict = {"symbol": symbol}
        if (freq or "").lower() in ("annual", "quarterly"):
            params["report"] = freq.lower()
        out = _make_api_request("CASH_FLOW", params)
        return _wrap_content(out)
    except AlphaVantageRateLimitError:
        raise
    except Exception as e:
        logger.exception("get_cashflow_av failed")
        return {"error": str(e)}


def get_income_statement_av(
    symbol: str, freq: str = "quarterly", _curr_date: Optional[str] = None
) -> dict:
    """Income statement (Alpha Vantage). Passes report=annual|quarterly when freq is set. Returns {"content": str, "timestamp": str} or {"error": str}."""
    try:
        params: dict = {"symbol": symbol}
        if (freq or "").lower() in ("annual", "quarterly"):
            params["report"] = freq.lower()
        out = _make_api_request("INCOME_STATEMENT", params)
        return _wrap_content(out)
    except AlphaVantageRateLimitError:
        raise
    except Exception as e:
        logger.exception("get_income_statement_av failed")
        return {"error": str(e)}


def get_news_av(symbol: str, start_date: str, end_date: str) -> dict:
    """Ticker news and sentiment (Alpha Vantage NEWS_SENTIMENT). Returns {"content": str, "timestamp": str} or {"error": str}."""
    try:
        params = {
            "tickers": symbol,
            "time_from": format_datetime_for_api(start_date),
            "time_to": format_datetime_for_api(end_date),
        }
        out = _make_api_request("NEWS_SENTIMENT", params)
        return _wrap_content(out)
    except AlphaVantageRateLimitError:
        raise
    except Exception as e:
        logger.exception("get_news_av failed")
        return {"error": str(e)}


def get_global_news_av(
    as_of_date: str, look_back_days: int = 7, limit: int = 50
) -> dict:
    """Global/macro news (Alpha Vantage NEWS_SENTIMENT). Returns {"content": str, "timestamp": str} or {"error": str}."""
    try:
        curr_dt = datetime.strptime(as_of_date, "%Y-%m-%d")
        start_dt = curr_dt - timedelta(days=look_back_days)
        start_date = start_dt.strftime("%Y-%m-%d")
        params = {
            "topics": "financial_markets,economy_macro,economy_monetary",
            "time_from": format_datetime_for_api(start_date),
            "time_to": format_datetime_for_api(as_of_date),
            "limit": str(limit),
        }
        out = _make_api_request("NEWS_SENTIMENT", params)
        return _wrap_content(out)
    except AlphaVantageRateLimitError:
        raise
    except Exception as e:
        logger.exception("get_global_news_av failed")
        return {"error": str(e)}


def get_insider_transactions_av(symbol: str) -> dict:
    """Insider transactions (Alpha Vantage). Returns {"content": str, "timestamp": str} or {"error": str}."""
    try:
        out = _make_api_request("INSIDER_TRANSACTIONS", {"symbol": symbol})
        return _wrap_content(out)
    except AlphaVantageRateLimitError:
        raise
    except Exception as e:
        logger.exception("get_insider_transactions_av failed")
        return {"error": str(e)}


# --- Vendor routing (alpha_vantage | finnhub) ---


def _wrap_content(s: str) -> dict:
    """Wrap string content in MCP result dict."""
    return {"content": s, "timestamp": _now_iso()}


def _route_stock_data(symbol: str, start_date: str, end_date: str) -> dict:
    """Route get_stock_data to configured vendor (alpha_vantage or finnhub)."""
    if get_market_vendor() == "finnhub" and _has_finnhub_key():
        return get_stock_data_finnhub(symbol, start_date, end_date)
    blocked = _av_rate_limit_error("market_tool.get_stock_data")
    if blocked:
        return {"error": blocked}
    try:
        return get_stock_data_av(symbol, start_date, end_date)
    except AlphaVantageRateLimitError as e:
        _mark_av_rate_limited(str(e))
        return {"error": f"Market data unavailable: {e}"}
    except Exception as e:
        logger.debug("Alpha Vantage stock data failed: %s", e)
        return {"error": f"Market data unavailable: {e}"}


def _route_fundamentals(symbol: str) -> dict:
    """Route get_fundamentals to configured vendor."""
    if get_market_vendor() == "finnhub" and _has_finnhub_key():
        return get_fundamentals_finnhub(symbol)
    blocked = _av_rate_limit_error("market_tool.get_fundamentals")
    if blocked:
        return {"error": blocked}
    try:
        return get_fundamentals_av(symbol)
    except AlphaVantageRateLimitError as e:
        _mark_av_rate_limited(str(e))
        return {"error": f"Fundamentals unavailable: {e}"}
    except Exception as e:
        logger.debug("Alpha Vantage fundamentals failed: %s", e)
        return {"error": f"Fundamentals unavailable: {e}"}


def _route_balance_sheet(symbol: str, freq: str) -> dict:
    """Route get_balance_sheet to configured vendor."""
    blocked = _av_rate_limit_error("market_tool.get_balance_sheet")
    if blocked:
        return {"error": blocked}
    try:
        return get_balance_sheet_av(symbol, freq)
    except AlphaVantageRateLimitError as e:
        _mark_av_rate_limited(str(e))
        return {"error": f"Balance sheet unavailable: {e}"}
    except Exception as e:
        logger.debug("Alpha Vantage balance sheet failed: %s", e)
        return {"error": f"Balance sheet unavailable: {e}"}


def _route_cashflow(symbol: str, freq: str) -> dict:
    """Route get_cashflow to configured vendor."""
    blocked = _av_rate_limit_error("market_tool.get_cashflow")
    if blocked:
        return {"error": blocked}
    try:
        return get_cashflow_av(symbol, freq)
    except AlphaVantageRateLimitError as e:
        _mark_av_rate_limited(str(e))
        return {"error": f"Cash flow unavailable: {e}"}
    except Exception as e:
        logger.debug("Alpha Vantage cashflow failed: %s", e)
        return {"error": f"Cash flow unavailable: {e}"}


def _route_income_statement(symbol: str, freq: str) -> dict:
    """Route get_income_statement to configured vendor."""
    blocked = _av_rate_limit_error("market_tool.get_income_statement")
    if blocked:
        return {"error": blocked}
    try:
        return get_income_statement_av(symbol, freq)
    except AlphaVantageRateLimitError as e:
        _mark_av_rate_limited(str(e))
        return {"error": f"Income statement unavailable: {e}"}
    except Exception as e:
        logger.debug("Alpha Vantage income statement failed: %s", e)
        return {"error": f"Income statement unavailable: {e}"}


def _route_news(
    symbol: str,
    limit: Optional[int],
    start_date: Optional[str],
    end_date: Optional[str],
) -> dict:
    """Route get_news to configured vendor. AV uses start/end."""
    if get_market_vendor() != "alpha_vantage" or not start_date or not end_date:
        return {"error": "News requires MCP_MARKET_VENDOR=alpha_vantage and start_date/end_date."}
    blocked = _av_rate_limit_error("market_tool.get_news")
    if blocked:
        return {"error": blocked}
    try:
        return get_news_av(symbol, start_date, end_date)
    except AlphaVantageRateLimitError as e:
        _mark_av_rate_limited(str(e))
        return {"error": f"News unavailable: {e}"}
    except Exception as e:
        logger.debug("Alpha Vantage news failed: %s", e)
        return {"error": f"News unavailable: {e}"}


def _route_global_news(as_of_date: str, look_back_days: int, limit: int) -> dict:
    """Route get_global_news to configured vendor."""
    blocked = _av_rate_limit_error("market_tool.get_global_news")
    if blocked:
        return {"error": blocked}
    try:
        return get_global_news_av(as_of_date, look_back_days, limit or 50)
    except AlphaVantageRateLimitError as e:
        _mark_av_rate_limited(str(e))
        return {"error": f"Global news unavailable: {e}"}
    except Exception as e:
        logger.debug("Alpha Vantage global news failed: %s", e)
        return {"error": f"Global news unavailable: {e}"}


def _route_insider_transactions(symbol: str) -> dict:
    """Route get_insider_transactions to configured vendor."""
    blocked = _av_rate_limit_error("market_tool.get_insider_transactions")
    if blocked:
        return {"error": blocked}
    try:
        return get_insider_transactions_av(symbol)
    except AlphaVantageRateLimitError as e:
        _mark_av_rate_limited(str(e))
        return {"error": f"Insider transactions unavailable: {e}"}
    except Exception as e:
        logger.debug("Alpha Vantage insider transactions failed: %s", e)
        return {"error": f"Insider transactions unavailable: {e}"}


# MCP registration: (name, func_name, required_keys, arg_specs, result_key).
# Use (param, [key1, key2], default, None) for symbol/ticker alias.
TOOL_SPECS: list[tuple[str, str, list[str], list, str | None]] = [
    ("market_tool.get_fundamentals", "_route_fundamentals", [], [("symbol", ["symbol", "ticker"], "", None)], None),
    ("market_tool.get_stock_data", "_route_stock_data", [], [("symbol", ["symbol", "ticker"], "", None), ("start_date", ["start_date"], "", None), ("end_date", ["end_date"], "", None)], None),
    ("market_tool.get_balance_sheet", "_route_balance_sheet", [], [("ticker", ["ticker", "symbol"], "", None), ("freq", ["freq"], "quarterly", None)], None),
    ("market_tool.get_cashflow", "_route_cashflow", [], [("ticker", ["ticker", "symbol"], "", None), ("freq", ["freq"], "quarterly", None)], None),
    ("market_tool.get_income_statement", "_route_income_statement", [], [("ticker", ["ticker", "symbol"], "", None), ("freq", ["freq"], "quarterly", None)], None),
    ("market_tool.get_news", "_route_news", [], [
        ("symbol", ["symbol", "ticker"], "", None),
        ("limit", ["limit", "count"], None, None),
        ("start_date", ["start_date"], None, None),
        ("end_date", ["end_date"], None, None),
    ], None),
    ("market_tool.get_global_news", "_route_global_news", [], [
        ("as_of_date", ["as_of_date", "curr_date"], "", None),
        ("look_back_days", ["look_back_days"], 7, int),
        ("limit", ["limit"], 10, int),
    ], None),
    ("market_tool.get_insider_transactions", "_route_insider_transactions", [], [("ticker", ["ticker", "symbol"], "", None)], None),
]
