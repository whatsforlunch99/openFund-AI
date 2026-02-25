"""Quantitative analysis via custom Analyst API and local statistical tools (MCP tool)."""

from __future__ import annotations

import logging
from datetime import datetime

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


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


def get_indicators(
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
            return {
                "error": f"Indicator '{indicator}' not supported. Choose from: {list(allowed)}",
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
        logger.exception("get_indicators failed")
        return {"error": str(e)}
