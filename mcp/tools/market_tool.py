"""Market and web search via Tavily (MCP tool).

Also provides company fundamentals, financials, insider transactions, and news (Alpha Vantage, Finnhub).
Contains vendor config, Alpha Vantage HTTP/rate-limit/CSV helpers, _av/_finnhub implementations, and _route_*.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta
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


def _make_api_request(function_name: str, params: dict) -> str:
    """Make API request and return response text. Raises AlphaVantageRateLimitError on rate limit."""
    api_params = params.copy()
    api_params.update(
        {
            "function": function_name,
            "apikey": get_api_key(),
        }
    )
    response = requests.get(API_BASE_URL, params=api_params, timeout=30)
    response.raise_for_status()
    response_text = response.text

    try:
        response_json = json.loads(response_text)
        if "Information" in response_json:
            info_message = response_json["Information"]
            if (
                "rate limit" in info_message.lower()
                or "api key" in info_message.lower()
            ):
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


def _now_iso() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


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
        return _wrap_content(out)
    except AlphaVantageRateLimitError:
        raise
    except Exception as e:
        logger.exception("get_stock_data_av failed")
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
            timeout=30,
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


def get_fundamentals_finnhub(symbol: str) -> dict:
    """Company profile from Finnhub profile2. Returns {"content": str, "timestamp": str} or {"error": str}."""
    try:
        symbol = (symbol or "").strip().upper()
        if not symbol:
            return {"error": "Missing required 'symbol'"}
        key = get_finnhub_api_key()
        r = requests.get(
            f"{FINNHUB_BASE}/stock/profile2",
            params={"symbol": symbol, "token": key},
            timeout=30,
        )
        r.raise_for_status()
        p = r.json()
        if not p or not isinstance(p, dict):
            return {
                "content": f"No fundamentals found for {symbol}",
                "timestamp": _now_iso(),
            }
        lines = [
            f"Name: {p.get('name', '')}",
            f"Ticker: {p.get('ticker', '')}",
            f"Country: {p.get('country', '')}",
            f"Currency: {p.get('currency', '')}",
            f"Exchange: {p.get('exchange', '')}",
            f"Industry: {p.get('finnhubIndustry', '')}",
            f"IPO: {p.get('ipo', '')}",
            f"Market Cap: {p.get('marketCapitalization', '')}",
            f"Web: {p.get('weburl', '')}",
        ]
        header = f"# Company profile for {symbol}\n# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        return _wrap_content(header + "\n".join(lines))
    except ValueError as e:
        return {"error": str(e)}
    except Exception as e:
        logger.exception("get_fundamentals_finnhub failed")
        return {"error": str(e)}


def get_fundamentals_av(symbol: str) -> dict:
    """Company overview (Alpha Vantage OVERVIEW). Returns {"content": str, "timestamp": str} or {"error": str}."""
    try:
        out = _make_api_request("OVERVIEW", {"symbol": symbol})
        return _wrap_content(out)
    except AlphaVantageRateLimitError:
        raise
    except Exception as e:
        logger.exception("get_fundamentals_av failed")
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
    try:
        return get_stock_data_av(symbol, start_date, end_date)
    except Exception as e:
        logger.debug("Alpha Vantage stock data failed: %s", e)
        return {"error": f"Market data unavailable: {e}"}


def _parse_stock_data_content_to_df(content: str) -> pd.DataFrame:
    """Parse stock data CSV (with optional # comment lines) into DataFrame with DatetimeIndex and OHLCV columns."""
    lines = [
        line
        for line in content.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    if not lines:
        return pd.DataFrame()
    raw = "\n".join(lines)
    df = pd.read_csv(StringIO(raw))
    date_col = df.columns[0]
    df[date_col] = pd.to_datetime(df[date_col])
    df = df.set_index(date_col)
    # Normalize to Open, High, Low, Close, Volume (AV may use lowercase / "adjusted close")
    col_lower = {c.strip().lower(): c for c in df.columns}
    result = pd.DataFrame(index=df.index)
    for std_name, keys in [
        ("Open", ["open"]),
        ("High", ["high"]),
        ("Low", ["low"]),
        ("Close", ["close", "adjusted close", "adj close"]),
        ("Volume", ["volume"]),
    ]:
        for k in keys:
            if k in col_lower:
                result[std_name] = df[col_lower[k]]
                break
    result.index.name = "Date"
    return result


def get_stock_analytics(symbol: str, start_date: str, end_date: str) -> dict:
    """
    Segment OHLCV into up to 15 periods and return per-segment stats (Dify Yahoo Analytics equivalent).
    Uses _route_stock_data; for Finnhub 403 on candles returns the same clear message.
    Returns {"content": str (JSON with "analytics" list), "timestamp": str} or {"error": str}.
    """
    try:
        symbol = (symbol or "").strip().upper()
        if not symbol:
            return {"error": "Missing required 'symbol'"}
        if not start_date or not end_date:
            return {"error": "Missing required 'start_date' or 'end_date'"}
        result = _route_stock_data(symbol, start_date, end_date)
        if "error" in result:
            return result
        content = result.get("content", "")
        if not content or "No data found" in content or "403" in content:
            return {
                "content": content
                or f"No data found for {symbol} in the specified date range",
                "timestamp": _now_iso(),
            }
        df = _parse_stock_data_content_to_df(content)
        if df.empty or len(df) < 1:
            return {
                "content": f"No data found for symbol {symbol} in the specified date range",
                "timestamp": _now_iso(),
            }
        for col in ["Open", "High", "Low", "Close", "Volume"]:
            if col not in df.columns:
                return {
                    "error": f"Missing required column {col} in stock data",
                    "timestamp": _now_iso(),
                }
        max_segments = min(15, len(df))
        rows_per_segment = len(df) // (max_segments or 1)
        summary_data: list[dict] = []
        for i in range(max_segments):
            start_idx = i * rows_per_segment
            end_idx = (i + 1) * rows_per_segment if i < max_segments - 1 else len(df)
            segment = df.iloc[start_idx:end_idx]
            if segment.empty:
                continue
            seg_open = segment["Open"]
            seg_high = segment["High"]
            seg_low = segment["Low"]
            seg_close = segment["Close"]
            seg_vol = segment["Volume"]
            segment_summary = {
                "Start Date": segment.index[0].strftime("%Y-%m-%d"),
                "End Date": segment.index[-1].strftime("%Y-%m-%d"),
                "Average Close": float(seg_close.mean()),
                "Average Volume": float(seg_vol.mean()),
                "Average Open": float(seg_open.mean()),
                "Average High": float(seg_high.mean()),
                "Average Low": float(seg_low.mean()),
                "Max Close": float(seg_close.max()),
                "Min Close": float(seg_close.min()),
                "Max Volume": float(seg_vol.max()),
                "Min Volume": float(seg_vol.min()),
                "Max Open": float(seg_open.max()),
                "Min Open": float(seg_open.min()),
                "Max High": float(seg_high.max()),
                "Min High": float(seg_high.min()),
                "Min Low": float(seg_low.min()),
                "Max Low": float(seg_low.max()),
            }
            summary_data.append(segment_summary)
        return _wrap_content(json.dumps({"analytics": summary_data}, default=str))
    except Exception as e:
        logger.exception("get_stock_analytics failed")
        return {"error": str(e)}


def _route_fundamentals(symbol: str) -> dict:
    """Route get_fundamentals to configured vendor."""
    if get_market_vendor() == "finnhub" and _has_finnhub_key():
        return get_fundamentals_finnhub(symbol)
    try:
        return get_fundamentals_av(symbol)
    except Exception as e:
        logger.debug("Alpha Vantage fundamentals failed: %s", e)
        return {"error": f"Fundamentals unavailable: {e}"}


def _route_balance_sheet(symbol: str, freq: str) -> dict:
    """Route get_balance_sheet to configured vendor."""
    try:
        return get_balance_sheet_av(symbol, freq)
    except Exception as e:
        logger.debug("Alpha Vantage balance sheet failed: %s", e)
        return {"error": f"Balance sheet unavailable: {e}"}


def _route_cashflow(symbol: str, freq: str) -> dict:
    """Route get_cashflow to configured vendor."""
    try:
        return get_cashflow_av(symbol, freq)
    except Exception as e:
        logger.debug("Alpha Vantage cashflow failed: %s", e)
        return {"error": f"Cash flow unavailable: {e}"}


def _route_income_statement(symbol: str, freq: str) -> dict:
    """Route get_income_statement to configured vendor."""
    try:
        return get_income_statement_av(symbol, freq)
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
    try:
        return get_news_av(symbol, start_date, end_date)
    except Exception as e:
        logger.debug("Alpha Vantage news failed: %s", e)
        return {"error": f"News unavailable: {e}"}


def _route_global_news(as_of_date: str, look_back_days: int, limit: int) -> dict:
    """Route get_global_news to configured vendor."""
    try:
        return get_global_news_av(as_of_date, look_back_days, limit or 50)
    except Exception as e:
        logger.debug("Alpha Vantage global news failed: %s", e)
        return {"error": f"Global news unavailable: {e}"}


def _route_insider_transactions(symbol: str) -> dict:
    """Route get_insider_transactions to configured vendor."""
    try:
        return get_insider_transactions_av(symbol)
    except Exception as e:
        logger.debug("Alpha Vantage insider transactions failed: %s", e)
        return {"error": f"Insider transactions unavailable: {e}"}


# --- Dify Yahoo–compatible: Ticker info (raw JSON) ---


def get_ticker_info_av(symbol: str) -> dict:
    """Raw company overview as JSON (Alpha Vantage OVERVIEW). Dify-compatible shape."""
    try:
        symbol = (symbol or "").strip().upper()
        if not symbol:
            return {"error": "Missing required 'symbol'"}
        out = _make_api_request("OVERVIEW", {"symbol": symbol})
        data = json.loads(out) if out.strip() else {}
        return _wrap_content(json.dumps(data, default=str))
    except AlphaVantageRateLimitError:
        raise
    except Exception as e:
        logger.exception("get_ticker_info_av failed")
        return {"error": str(e)}


def get_ticker_info_finnhub(symbol: str) -> dict:
    """Company profile as JSON (Finnhub profile2). Dify-compatible flat structure."""
    try:
        symbol = (symbol or "").strip().upper()
        if not symbol:
            return {"error": "Missing required 'symbol'"}
        key = get_finnhub_api_key()
        r = requests.get(
            f"{FINNHUB_BASE}/stock/profile2",
            params={"symbol": symbol, "token": key},
            timeout=30,
        )
        r.raise_for_status()
        p = r.json()
        if not p or not isinstance(p, dict):
            return _wrap_content(json.dumps({}))
        return _wrap_content(json.dumps(p, default=str))
    except ValueError as e:
        return {"error": str(e)}
    except Exception as e:
        logger.exception("get_ticker_info_finnhub failed")
        return {"error": str(e)}


def _route_ticker_info(symbol: str) -> dict:
    """Route get_ticker_info to configured vendor (alpha_vantage or finnhub)."""
    if get_market_vendor() == "finnhub" and _has_finnhub_key():
        return get_ticker_info_finnhub(symbol)
    try:
        return get_ticker_info_av(symbol)
    except Exception as e:
        logger.debug("Alpha Vantage ticker info failed: %s", e)
        return {"error": f"Ticker info unavailable: {e}"}


def get_ticker_info(symbol: str) -> dict:
    """
    Ticker/company info as JSON (Dify Yahoo Ticker equivalent).
    Uses MCP_MARKET_VENDOR (alpha_vantage, finnhub). get_fundamentals
    returns human-readable text; this returns raw info dict as JSON string in content.
    """
    return _route_ticker_info(symbol)
