"""Ticker extraction from free-form query text (agent-agnostic).

Used by planner symbol resolution and WebSearcher normalization. Logic must stay
aligned with WebSearcher heuristics (database/agent_heuristics.json).
"""

from __future__ import annotations

import re

from util.agent_heuristics import get_websearcher_heuristics
from util.symbol_resolution_deterministic import apply_ticker_aliases


def _standalone_upper_tickers(upper: str) -> list[str]:
    tokens = re.findall(r"\b[A-Z]{1,5}\b", upper)
    bl = get_websearcher_heuristics().ticker_blocklist
    return [t for t in tokens if t not in bl]


def _symbol_from_known_company_phrase(lower: str) -> str | None:
    for phrase, sym in get_websearcher_heuristics().known_company_phrases:
        if phrase in lower:
            return sym
    return None


def _prefer_etf_over_sp500_index_phrase(lower: str, upper: str) -> str | None:
    """If text names an ETF ticker and also S&P 500 wording, return that ETF symbol."""
    h = get_websearcher_heuristics()
    etf_hits = [
        t for t in _standalone_upper_tickers(upper) if t in h.etf_tickers_override_sp500_phrase
    ]
    if not etf_hits:
        return None
    if not any(p in lower for p in h.sp500_verbiage_substrings):
        return None
    return etf_hits[0]


def merge_catalog_symbols_for_query(symbols: list[str], query: str) -> list[str]:
    """Prefer explicit query ETFs over SPX when catalog + S&P 500 phrasing collide."""
    lower = query.lower()
    upper = query.upper()
    out = [str(s).strip().upper() for s in symbols if s]
    ovr = _prefer_etf_over_sp500_index_phrase(lower, upper)
    if ovr:
        out = [ovr if s == "SPX" else s for s in out]
        if ovr not in out:
            out.append(ovr)
    seen: set[str] = set()
    deduped: list[str] = []
    for s in out:
        if s and s not in seen:
            seen.add(s)
            deduped.append(s)
    return deduped


def extract_symbol_from_query(raw: str) -> str:
    """Extract expected ticker from free-form query text.

    Same logic as WebSearcherAgent normalization. Used by planner for symbol-mismatch validation.
    """
    h = get_websearcher_heuristics()

    def _finalize(sym: str) -> str:
        if sym == h.default_fallback_symbol:
            return sym
        return apply_ticker_aliases(sym)

    text = (raw or "").strip()
    if not text:
        return h.default_fallback_symbol
    upper = text.upper()
    lower = text.lower()
    paren = re.search(r"\(([A-Z]{2,5})\)", upper)
    if paren:
        sym = paren.group(1)
        if sym not in h.ticker_blocklist:
            return _finalize(sym)
    etf_over_index = _prefer_etf_over_sp500_index_phrase(lower, upper)
    if etf_over_index:
        return _finalize(etf_over_index)
    for key, sym in h.query_substring_to_symbol:
        if key in lower:
            return _finalize(sym)
    phrase_sym = _symbol_from_known_company_phrase(lower)
    if phrase_sym:
        return _finalize(phrase_sym)
    tokens = re.findall(r"\b[A-Z]{1,5}\b", upper)
    candidates = [t for t in tokens if t not in h.ticker_blocklist]
    if candidates:
        preferred_set = set(h.preferred_tickers)
        in_preferred = [t for t in candidates if t in preferred_set]
        if in_preferred:
            return _finalize(in_preferred[0])
        return _finalize(max(candidates, key=len))
    return h.default_fallback_symbol
