"""Load editable agent heuristics from ``database/agent_heuristics.json``.

Ticker blocklists, phrase→symbol maps, and defaults live in that file—not in ``agents/``.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

logger = logging.getLogger(__name__)

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_HEURISTICS_PATH = os.path.join(_REPO_ROOT, "database", "agent_heuristics.json")


@dataclass(frozen=True)
class WebsearcherHeuristics:
    ticker_blocklist: frozenset[str]
    query_substring_to_symbol: tuple[tuple[str, str], ...]
    known_company_phrases: tuple[tuple[str, str], ...]
    preferred_tickers: tuple[str, ...]
    known_index_symbols: frozenset[str]
    etf_tickers_override_sp500_phrase: frozenset[str]
    sp500_verbiage_substrings: tuple[str, ...]
    default_fallback_symbol: str


@dataclass(frozen=True)
class PlannerHeuristics:
    partial_insufficient_prefix: str
    partial_insufficient_suffix: str


@dataclass(frozen=True)
class AnalystHeuristics:
    default_symbol: str
    query_scan_tickers: tuple[str, ...]


def _pair_list(raw: Any) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if (
            isinstance(item, (list, tuple))
            and len(item) == 2
            and isinstance(item[0], str)
            and isinstance(item[1], str)
        ):
            a, b = item[0].strip().lower(), item[1].strip().upper()
            if a and b:
                out.append((a, b))
    return out


def _str_list(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [str(x).strip() for x in raw if isinstance(x, str) and str(x).strip()]


def load_agent_heuristics_document_raw() -> dict[str, Any]:
    if not os.path.isfile(_HEURISTICS_PATH):
        logger.error("Missing %s", _HEURISTICS_PATH)
        return {}
    try:
        with open(_HEURISTICS_PATH, encoding="utf-8") as f:
            raw = json.load(f)
        return raw if isinstance(raw, dict) else {}
    except (OSError, json.JSONDecodeError) as e:
        logger.error("Invalid agent heuristics JSON: %s", e)
        return {}


@lru_cache(maxsize=1)
def load_agent_heuristics_document() -> dict[str, Any]:
    return load_agent_heuristics_document_raw()


@lru_cache(maxsize=1)
def get_websearcher_heuristics() -> WebsearcherHeuristics:
    doc = load_agent_heuristics_document()
    ws = doc.get("websearcher")
    if not isinstance(ws, dict):
        raise RuntimeError(
            f"database/agent_heuristics.json missing valid 'websearcher' object: {_HEURISTICS_PATH}"
        )
    bl = frozenset(s.strip().upper() for s in _str_list(ws.get("ticker_blocklist")) if s)
    qpairs = _pair_list(ws.get("query_substring_to_symbol"))
    cph = _pair_list(ws.get("known_company_phrases"))
    pref = tuple(s.strip().upper() for s in _str_list(ws.get("preferred_tickers")) if s)
    idx = frozenset(s.strip().upper() for s in _str_list(ws.get("known_index_symbols")) if s)
    etfo = frozenset(
        s.strip().upper() for s in _str_list(ws.get("etf_tickers_override_sp500_phrase")) if s
    )
    sp5 = tuple(s.lower() for s in _str_list(ws.get("sp500_verbiage_substrings")) if s)
    dfb = ws.get("default_fallback_symbol")
    fallback = (
        dfb.strip().upper()
        if isinstance(dfb, str) and dfb.strip()
        else "AAPL"
    )
    if not bl or not qpairs:
        raise RuntimeError(
            "database/agent_heuristics.json: websearcher.ticker_blocklist and "
            "query_substring_to_symbol must be non-empty"
        )
    return WebsearcherHeuristics(
        ticker_blocklist=bl,
        query_substring_to_symbol=tuple(qpairs),
        known_company_phrases=tuple(cph),
        preferred_tickers=pref,
        known_index_symbols=idx,
        etf_tickers_override_sp500_phrase=etfo,
        sp500_verbiage_substrings=sp5,
        default_fallback_symbol=fallback,
    )


@lru_cache(maxsize=1)
def get_planner_heuristics() -> PlannerHeuristics:
    doc = load_agent_heuristics_document()
    pl = doc.get("planner")
    if not isinstance(pl, dict):
        return PlannerHeuristics(
            partial_insufficient_prefix=(
                "The research did not fully answer every part of your question. "
                "Here is what was gathered:\n\n"
            ),
            partial_insufficient_suffix=(
                "\n\nSome details you asked for may still be missing; you can ask a narrower "
                "follow-up for a specific symbol, timeframe, or metric."
            ),
        )
    pre = pl.get("partial_insufficient_prefix")
    suf = pl.get("partial_insufficient_suffix")
    return PlannerHeuristics(
        partial_insufficient_prefix=pre if isinstance(pre, str) else "",
        partial_insufficient_suffix=suf if isinstance(suf, str) else "",
    )


@lru_cache(maxsize=1)
def get_analyst_heuristics() -> AnalystHeuristics:
    doc = load_agent_heuristics_document()
    an = doc.get("analyst")
    if not isinstance(an, dict):
        return AnalystHeuristics(
            default_symbol="NVDA",
            query_scan_tickers=("NVDA", "AAPL", "TSLA", "MSFT", "GOOGL"),
        )
    ds = an.get("default_symbol")
    sym = ds.strip().upper() if isinstance(ds, str) and ds.strip() else "NVDA"
    ticks = tuple(s.strip().upper() for s in _str_list(an.get("query_scan_tickers")) if s)
    if not ticks:
        ticks = ("NVDA", "AAPL", "TSLA", "MSFT", "GOOGL")
    return AnalystHeuristics(default_symbol=sym, query_scan_tickers=ticks)


def planner_fallback_substring_symbol_pairs() -> tuple[tuple[str, str], ...]:
    """Ordered (substring, symbol) for planner LLM-off fallback fund= hint."""
    return get_websearcher_heuristics().query_substring_to_symbol


def clear_heuristics_cache() -> None:
    """Reload JSON from disk on next access (tests)."""
    load_agent_heuristics_document.cache_clear()
    get_websearcher_heuristics.cache_clear()
    get_planner_heuristics.cache_clear()
    get_analyst_heuristics.cache_clear()
