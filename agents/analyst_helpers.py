"""Shared helper utilities for analyst mixins."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Optional

from util.agent_heuristics import get_analyst_heuristics

logger = logging.getLogger(__name__)


def tool_error_is_av_cooldown(result: dict[str, Any]) -> bool:
    """Return True when the tool error indicates Alpha Vantage cooldown/rate-limit."""
    err = result.get("error")
    if not isinstance(err, str):
        return False
    lowered = err.lower()
    return "cooldown" in lowered or "rate limit" in lowered


def resolved_symbol_from_planner(symbol_resolution: Any) -> Optional[str]:
    """Return first resolved ticker symbol from planner symbol resolution."""
    if not isinstance(symbol_resolution, dict):
        return None
    if symbol_resolution.get("status") != "resolved":
        return None
    listings = symbol_resolution.get("listings") or []
    if not listings or not isinstance(listings[0], dict):
        return None
    symbol = listings[0].get("symbol_yahoo") or listings[0].get("symbol_compact")
    if isinstance(symbol, str) and symbol.strip():
        return symbol.strip().upper()
    return None


def apply_resolved_symbol_to_analyst_calls(
    tool_calls: list[dict[str, Any]],
    symbol_resolution: Any,
) -> list[dict[str, Any]]:
    """Force analyst indicator calls to use planner-resolved ticker when available."""
    locked_symbol = resolved_symbol_from_planner(symbol_resolution)
    if not locked_symbol:
        return tool_calls
    rewritten: list[dict[str, Any]] = []
    for tool_call in tool_calls:
        if not isinstance(tool_call, dict):
            continue
        tool = tool_call.get("tool", "")
        if tool != "analyst_tool.get_indicators":
            rewritten.append(tool_call)
            continue
        payload = tool_call.get("payload")
        payload_dict = dict(payload) if isinstance(payload, dict) else {}
        for key in ("symbol", "ticker"):
            if key not in payload_dict:
                continue
            raw = payload_dict[key]
            if not isinstance(raw, str) or not raw.strip():
                continue
            current_symbol = raw.strip().upper()
            if current_symbol != locked_symbol:
                logger.warning(
                    "Analyst tool payload %s=%s overridden to %s (planner symbol_resolution)",
                    key,
                    current_symbol,
                    locked_symbol,
                )
                payload_dict[key] = locked_symbol
        if "symbol" not in payload_dict and "ticker" not in payload_dict:
            payload_dict["symbol"] = locked_symbol
        rewritten.append({"tool": tool, "payload": payload_dict})
    return rewritten


def derive_symbol(structured_data: dict[str, Any], market_data: dict[str, Any]) -> str:
    """Infer ticker symbol from structured payloads before fallback API calls."""
    heuristics = get_analyst_heuristics()
    if isinstance(structured_data, dict):
        resolved_symbol = structured_data.get("resolved_symbol")
        if isinstance(resolved_symbol, str) and resolved_symbol.strip():
            return resolved_symbol.strip().upper()
        for key in ("symbol", "fund", "ticker"):
            value = structured_data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip().upper()
        query = structured_data.get("query") or structured_data.get("vector_query")
        if isinstance(query, str) and query.strip():
            query_upper = query.strip().upper()
            query_lower = query.lower()
            for ticker in heuristics.query_scan_tickers:
                if ticker in query_upper or ticker.lower() in query_lower:
                    return ticker
    if isinstance(market_data, dict):
        for key in ("symbol", "ticker", "fund"):
            value = market_data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip().upper()
    return heuristics.default_symbol


def parse_iso_utc(value: Any) -> Optional[date]:
    """Parse ISO-like timestamp into a UTC date."""
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if len(raw) >= 10 and raw[4] == "-" and raw[7] == "-":
        try:
            return date.fromisoformat(raw[:10])
        except ValueError:
            return None
    return None


def extract_market_price(market_data: dict[str, Any]) -> Optional[float]:
    """Extract best-available market price from market payload."""
    if not isinstance(market_data, dict):
        return None
    direct_price = market_data.get("price")
    if isinstance(direct_price, (int, float)):
        return float(direct_price)
    normalized_fund = market_data.get("normalized_fund")
    if isinstance(normalized_fund, list):
        for row in normalized_fund:
            if not isinstance(row, dict):
                continue
            row_price = row.get("price")
            if isinstance(row_price, (int, float)):
                return float(row_price)
    return None
