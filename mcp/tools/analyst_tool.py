"""Quantitative analysis via custom Analyst API and local statistical tools (MCP tool).

Contains get_indicators_yf, get_indicators_av, stockstats-based extended indicators, run_analysis stub, and _route_indicators.
Vendor config for indicators (get_indicator_vendor, get_data_cache_dir) imported from market_tool.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime

import pandas as pd
import yfinance as yf
from dateutil.relativedelta import relativedelta

from mcp.tools.market_tool import (
    AlphaVantageRateLimitError,
    _make_api_request,
    _now_iso,
    get_data_cache_dir,
    get_indicator_vendor,
)

logger = logging.getLogger(__name__)


# --- Stockstats extended indicators (optional dependency: stockstats) ---

STOCKSTATS_INDICATORS = frozenset(
    {
        "close_50_sma",
        "close_200_sma",
        "close_10_ema",
        "macd",
        "macds",
        "macdh",
        "rsi",
        "boll",
        "boll_ub",
        "boll_lb",
        "atr",
        "vwma",
        "mfi",
    }
)

INDICATOR_DESCRIPTIONS = {
    "close_50_sma": "50 SMA: A medium-term trend indicator. Usage: Identify trend direction and serve as dynamic support/resistance. Tips: It lags price; combine with faster indicators for timely signals.",
    "close_200_sma": "200 SMA: A long-term trend benchmark. Usage: Confirm overall market trend and identify golden/death cross setups. Tips: It reacts slowly; best for strategic trend confirmation rather than frequent trading entries.",
    "close_10_ema": "10 EMA: A responsive short-term average. Usage: Capture quick shifts in momentum and potential entry points. Tips: Prone to noise in choppy markets; use alongside longer averages for filtering false signals.",
    "macd": "MACD: Computes momentum via differences of EMAs. Usage: Look for crossovers and divergence as signals of trend changes. Tips: Confirm with other indicators in low-volatility or sideways markets.",
    "macds": "MACD Signal: An EMA smoothing of the MACD line. Usage: Use crossovers with the MACD line to trigger trades. Tips: Should be part of a broader strategy to avoid false positives.",
    "macdh": "MACD Histogram: Shows the gap between the MACD line and its signal. Usage: Visualize momentum strength and spot divergence early. Tips: Can be volatile; complement with additional filters in fast-moving markets.",
    "rsi": "RSI: Measures momentum to flag overbought/oversold conditions. Usage: Apply 70/30 thresholds and watch for divergence to signal reversals. Tips: In strong trends, RSI may remain extreme; always cross-check with trend analysis.",
    "boll": "Bollinger Middle: A 20 SMA serving as the basis for Bollinger Bands. Usage: Acts as a dynamic benchmark for price movement. Tips: Combine with the upper and lower bands to effectively spot breakouts or reversals.",
    "boll_ub": "Bollinger Upper Band: Typically 2 standard deviations above the middle line. Usage: Signals potential overbought conditions and breakout zones. Tips: Confirm signals with other tools; prices may ride the band in strong trends.",
    "boll_lb": "Bollinger Lower Band: Typically 2 standard deviations below the middle line. Usage: Indicates potential oversold conditions. Tips: Use additional analysis to avoid false reversal signals.",
    "atr": "ATR: Averages true range to measure volatility. Usage: Set stop-loss levels and adjust position sizes based on current market volatility. Tips: It's a reactive measure, so use it as part of a broader risk management strategy.",
    "vwma": "VWMA: A moving average weighted by volume. Usage: Confirm trends by integrating price action with volume data. Tips: Watch for skewed results from volume spikes; use in combination with other volume analyses.",
    "mfi": "MFI: The Money Flow Index is a momentum indicator that uses both price and volume to measure buying and selling pressure. Usage: Identify overbought (>80) or oversold (<20) conditions and confirm the strength of trends or reversals. Tips: Use alongside RSI or MACD to confirm signals; divergence between price and MFI can indicate potential reversals.",
}


def get_indicators_stockstats_window(
    symbol: str,
    indicator: str,
    as_of_date: str,
    look_back_days: int,
) -> dict:
    """
    Compute one indicator over a lookback window using stockstats + yfinance.
    Returns {"content": str, "timestamp": str} or {"error": str}.
    """
    try:
        from stockstats import wrap
    except ImportError:
        return {"error": "stockstats package not installed"}

    if indicator not in STOCKSTATS_INDICATORS:
        return {
            "error": f"Indicator '{indicator}' not in stockstats set. Choose from: {sorted(STOCKSTATS_INDICATORS)}",
        }

    symbol = (symbol or "").strip().upper()
    if not symbol:
        return {"error": "Missing required 'symbol'"}
    if not as_of_date:
        return {"error": "Missing required 'as_of_date'"}
    look_back_days = int(look_back_days)

    cache_dir = get_data_cache_dir()

    end_dt = pd.to_datetime(as_of_date)
    start_dt = end_dt - pd.DateOffset(days=look_back_days + 200)
    start_str = start_dt.strftime("%Y-%m-%d")
    end_str = end_dt.strftime("%Y-%m-%d")

    data = None
    if cache_dir:
        os.makedirs(cache_dir, exist_ok=True)
        data_file = os.path.join(
            cache_dir,
            f"{symbol}-YFin-data-{start_str}-{end_str}.csv",
        )
        if os.path.exists(data_file):
            try:
                data = pd.read_csv(data_file)
                data["Date"] = pd.to_datetime(data["Date"])
            except Exception as e:
                logger.debug("Cache read failed: %s", e)
    if data is None:
        data = yf.download(
            symbol,
            start=start_str,
            end=end_str,
            progress=False,
            auto_adjust=True,
        )
        if data.empty:
            return {"content": f"No data for {symbol}", "timestamp": _now_iso()}
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)
        data = data.reset_index()
        if cache_dir:
            try:
                data.to_csv(
                    os.path.join(
                        cache_dir, f"{symbol}-YFin-data-{start_str}-{end_str}.csv"
                    ),
                    index=False,
                )
            except Exception as e:
                logger.debug("Cache write failed: %s", e)

    date_col = "Date" if "Date" in data.columns else data.columns[0]
    df = wrap(data)
    df["Date"] = pd.to_datetime(df[date_col]).dt.strftime("%Y-%m-%d")
    df[indicator]  # trigger calculation

    before = end_dt - pd.DateOffset(days=look_back_days)
    start_lim = before.strftime("%Y-%m-%d")
    mask = (df["Date"] >= start_lim) & (df["Date"] <= as_of_date)
    subset = df.loc[mask, ["Date", indicator]].dropna(subset=[indicator])
    lines = [f"{row['Date']}: {row[indicator]}" for _, row in subset.iterrows()]
    lines.reverse()
    content = (
        f"## {indicator} values for {symbol} (look back from {as_of_date}):\n\n"
        + "\n".join(lines)
        + "\n\n"
        + INDICATOR_DESCRIPTIONS.get(indicator, "")
    )
    return {"content": content, "timestamp": _now_iso()}


def run_analysis(payload: dict) -> dict:
    """
    POST to custom Analyst API (e.g. Sharpe, max_drawdown, Monte Carlo).

    Payload and response schema are defined by the custom API.

    Args:
        payload: Request body (e.g. returns, horizon, n_sims). Must be passed in; no defaults.

    Returns:
        Response dict (e.g. metrics, distribution). Config: ANALYST_API_URL, optional ANALYST_API_KEY.
    """
    raise NotImplementedError


def get_indicators_yf(
    symbol: str, indicator: str, as_of_date: str, look_back_days: int
) -> dict:
    """
    Technical indicators (e.g. SMA) computed from OHLCV (yfinance).

    Args:
        symbol: Stock or fund symbol (e.g. AAPL).
        indicator: One of sma_50, sma_200, close_50_sma, close_200_sma.
        as_of_date: Reference date for lookback, yyyy-mm-dd.
        look_back_days: Number of days to look back.

    Returns:
        {"content": str, "timestamp": str} or {"error": str}.
    """
    try:
        symbol = (symbol or "").strip().upper()
        if not symbol:
            return {"error": "Missing required 'symbol'"}
        indicator = (indicator or "").strip().lower()
        if not as_of_date:
            return {"error": "Missing required 'as_of_date'"}
        if look_back_days is None:
            return {"error": "Missing required 'look_back_days'"}
        look_back_days = int(look_back_days)

        allowed = ("sma_50", "sma_200", "close_50_sma", "close_200_sma")
        if indicator not in allowed:
            # Try stockstats extended set when available
            if indicator in STOCKSTATS_INDICATORS:
                return get_indicators_stockstats_window(
                    symbol, indicator, as_of_date, look_back_days
                )
            return {
                "error": f"Indicator '{indicator}' not supported. Choose from: {list(allowed)} (or install stockstats for more).",
            }

        window = 50 if "50" in indicator else 200
        end_dt = pd.to_datetime(as_of_date)
        start_dt = end_dt - pd.DateOffset(days=look_back_days + window)
        start_str = start_dt.strftime("%Y-%m-%d")
        end_str = end_dt.strftime("%Y-%m-%d")

        data = yf.download(
            symbol,
            start=start_str,
            end=end_str,
            progress=False,
            auto_adjust=True,
        )
        if data.empty or len(data) < window:
            return {
                "content": f"Insufficient data for {indicator} on {symbol}",
                "timestamp": _now_iso(),
            }

        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)
        data = data.reset_index()
        date_col = "Date" if "Date" in data.columns else data.columns[0]
        data["_date"] = pd.to_datetime(data[date_col]).dt.strftime("%Y-%m-%d")
        close = data["Close"] if "Close" in data.columns else data["Adj Close"]
        sma = close.rolling(window=window).mean()
        data["_sma"] = sma.values

        start_str_lim = (end_dt - pd.DateOffset(days=look_back_days)).strftime(
            "%Y-%m-%d"
        )
        mask = (data["_date"] >= start_str_lim) & (data["_date"] <= as_of_date)
        subset = data.loc[mask, ["_date", "_sma"]].dropna(subset=["_sma"])
        lines = [f"{row['_date']}: {row['_sma']}" for _, row in subset.iterrows()]
        lines.reverse()
        content = (
            f"## {indicator} values for {symbol} (look back from {as_of_date}):\n\n"
            + "\n".join(lines)
        )
        return {"content": content, "timestamp": _now_iso()}
    except Exception as e:
        logger.exception("get_indicators_yf failed")
        return {"error": str(e)}


# --- Alpha Vantage indicators (get_indicators_av) ---

_AV_SUPPORTED_INDICATORS = {
    "close_50_sma": ("50 SMA", "close"),
    "close_200_sma": ("200 SMA", "close"),
    "close_10_ema": ("10 EMA", "close"),
    "macd": ("MACD", "close"),
    "macds": ("MACD Signal", "close"),
    "macdh": ("MACD Histogram", "close"),
    "rsi": ("RSI", "close"),
    "boll": ("Bollinger Middle", "close"),
    "boll_ub": ("Bollinger Upper Band", "close"),
    "boll_lb": ("Bollinger Lower Band", "close"),
    "atr": ("ATR", None),
    "vwma": ("VWMA", "close"),
}

_AV_INDICATOR_DESCRIPTIONS = {
    "close_50_sma": "50 SMA: A medium-term trend indicator. Usage: Identify trend direction and serve as dynamic support/resistance. Tips: It lags price; combine with faster indicators for timely signals.",
    "close_200_sma": "200 SMA: A long-term trend benchmark. Usage: Confirm overall market trend and identify golden/death cross setups. Tips: It reacts slowly; best for strategic trend confirmation rather than frequent trading entries.",
    "close_10_ema": "10 EMA: A responsive short-term average. Usage: Capture quick shifts in momentum and potential entry points. Tips: Prone to noise in choppy markets; use alongside longer averages for filtering false signals.",
    "macd": "MACD: Computes momentum via differences of EMAs. Usage: Look for crossovers and divergence as signals of trend changes. Tips: Confirm with other indicators in low-volatility or sideways markets.",
    "macds": "MACD Signal: An EMA smoothing of the MACD line. Usage: Use crossovers with the MACD line to trigger trades. Tips: Should be part of a broader strategy to avoid false positives.",
    "macdh": "MACD Histogram: Shows the gap between the MACD line and its signal. Usage: Visualize momentum strength and spot divergence early. Tips: Can be volatile; complement with additional filters in fast-moving markets.",
    "rsi": "RSI: Measures momentum to flag overbought/oversold conditions. Usage: Apply 70/30 thresholds and watch for divergence to signal reversals. Tips: In strong trends, RSI may remain extreme; always cross-check with trend analysis.",
    "boll": "Bollinger Middle: A 20 SMA serving as the basis for Bollinger Bands. Usage: Acts as a dynamic benchmark for price movement. Tips: Combine with the upper and lower bands to effectively spot breakouts or reversals.",
    "boll_ub": "Bollinger Upper Band: Typically 2 standard deviations above the middle line. Usage: Signals potential overbought conditions and breakout zones. Tips: Confirm signals with other tools; prices may ride the band in strong trends.",
    "boll_lb": "Bollinger Lower Band: Typically 2 standard deviations below the middle line. Usage: Indicates potential oversold conditions. Tips: Use additional analysis to avoid false reversal signals.",
    "atr": "ATR: Averages true range to measure volatility. Usage: Set stop-loss levels and adjust position sizes based on current market volatility. Tips: It's a reactive measure, so use it as part of a broader risk management strategy.",
    "vwma": "VWMA: A moving average weighted by volume. Usage: Confirm trends by integrating price action with volume data. Tips: Watch for skewed results from volume spikes; use in combination with other volume analyses.",
}

_AV_COL_NAME_MAP = {
    "macd": "MACD",
    "macds": "MACD_Signal",
    "macdh": "MACD_Hist",
    "boll": "Real Middle Band",
    "boll_ub": "Real Upper Band",
    "boll_lb": "Real Lower Band",
    "rsi": "RSI",
    "atr": "ATR",
    "close_10_ema": "EMA",
    "close_50_sma": "SMA",
    "close_200_sma": "SMA",
}


def _av_fetch_indicator_data(
    symbol: str,
    indicator: str,
    interval: str,
    time_period: int,
    series_type: str,
) -> str | None:
    """Call Alpha Vantage API for the given indicator; return CSV string or None."""
    if indicator == "close_50_sma":
        return _make_api_request(
            "SMA",
            {
                "symbol": symbol,
                "interval": interval,
                "time_period": "50",
                "series_type": series_type,
                "datatype": "csv",
            },
        )
    if indicator == "close_200_sma":
        return _make_api_request(
            "SMA",
            {
                "symbol": symbol,
                "interval": interval,
                "time_period": "200",
                "series_type": series_type,
                "datatype": "csv",
            },
        )
    if indicator == "close_10_ema":
        return _make_api_request(
            "EMA",
            {
                "symbol": symbol,
                "interval": interval,
                "time_period": "10",
                "series_type": series_type,
                "datatype": "csv",
            },
        )
    if indicator in ("macd", "macds", "macdh"):
        return _make_api_request(
            "MACD",
            {
                "symbol": symbol,
                "interval": interval,
                "series_type": series_type,
                "datatype": "csv",
            },
        )
    if indicator == "rsi":
        return _make_api_request(
            "RSI",
            {
                "symbol": symbol,
                "interval": interval,
                "time_period": str(time_period),
                "series_type": series_type,
                "datatype": "csv",
            },
        )
    if indicator in ("boll", "boll_ub", "boll_lb"):
        return _make_api_request(
            "BBANDS",
            {
                "symbol": symbol,
                "interval": interval,
                "time_period": "20",
                "series_type": series_type,
                "datatype": "csv",
            },
        )
    if indicator == "atr":
        return _make_api_request(
            "ATR",
            {
                "symbol": symbol,
                "interval": interval,
                "time_period": str(time_period),
                "datatype": "csv",
            },
        )
    return None


def get_indicators_av(
    symbol: str,
    indicator: str,
    as_of_date: str,
    look_back_days: int,
    interval: str = "daily",
    time_period: int = 14,
    series_type: str = "close",
) -> dict:
    """
    Technical indicators from Alpha Vantage.

    Returns:
        {"content": str, "timestamp": str} or {"error": str}.
    """
    if indicator not in _AV_SUPPORTED_INDICATORS:
        return {
            "error": f"Indicator '{indicator}' not supported. Choose from: {list(_AV_SUPPORTED_INDICATORS.keys())}",
        }

    curr_date_dt = datetime.strptime(as_of_date, "%Y-%m-%d")
    before = curr_date_dt - relativedelta(days=look_back_days)
    _, required_series_type = _AV_SUPPORTED_INDICATORS[indicator]
    if required_series_type:
        series_type = required_series_type

    if indicator == "vwma":
        content = (
            f"## VWMA (Volume Weighted Moving Average) for {symbol}:\n\n"
            "VWMA is not directly available from Alpha Vantage API; use yfinance/stockstats vendor.\n\n"
            f"{_AV_INDICATOR_DESCRIPTIONS.get('vwma', '')}"
        )
        return {"content": content, "timestamp": _now_iso()}

    try:
        data = _av_fetch_indicator_data(
            symbol, indicator, interval, time_period, series_type
        )
        if data is None:
            return {"error": f"No data returned for {indicator}"}

        lines = data.strip().split("\n")
        if len(lines) < 2:
            return {"error": f"No data returned for {indicator}"}

        header = [col.strip() for col in lines[0].split(",")]
        try:
            date_col_idx = header.index("time")
        except ValueError:
            return {"error": f"'time' column not found. Available: {header}"}

        target_col_name = _AV_COL_NAME_MAP.get(indicator)
        if target_col_name:
            try:
                value_col_idx = header.index(target_col_name)
            except ValueError:
                return {
                    "error": f"Column '{target_col_name}' not found. Available: {header}"
                }
        else:
            value_col_idx = 1

        result_data = []
        for line in lines[1:]:
            if not line.strip():
                continue
            values = line.split(",")
            if len(values) <= value_col_idx:
                continue
            try:
                date_str = values[date_col_idx].strip()
                date_dt = datetime.strptime(date_str, "%Y-%m-%d")
                if before <= date_dt <= curr_date_dt:
                    result_data.append((date_dt, values[value_col_idx].strip()))
            except (ValueError, IndexError):
                continue

        result_data.sort(key=lambda x: x[0])
        ind_string = "".join(f"{d.strftime('%Y-%m-%d')}: {v}\n" for d, v in result_data)
        if not ind_string:
            ind_string = "No data available for the specified date range.\n"

        content = (
            f"## {indicator.upper()} values from {before.strftime('%Y-%m-%d')} to {as_of_date}:\n\n"
            + ind_string
            + "\n\n"
            + _AV_INDICATOR_DESCRIPTIONS.get(indicator, "No description available.")
        )
        return {"content": content, "timestamp": _now_iso()}
    except AlphaVantageRateLimitError:
        raise
    except Exception as e:
        logger.exception("Alpha Vantage indicator %s failed", indicator)
        return {"error": str(e)}


# --- Vendor routing ---


def _route_indicators(
    symbol: str, indicator: str, as_of_date: str, look_back_days: int
) -> dict:
    """Route get_indicators to configured vendor (yfinance/stockstats or alpha_vantage)."""
    if get_indicator_vendor() == "alpha_vantage":
        try:
            return get_indicators_av(symbol, indicator, as_of_date, look_back_days)
        except AlphaVantageRateLimitError:
            pass
    return get_indicators_yf(symbol, indicator, as_of_date, look_back_days)
