"""Layer 1: curated ticker/company aliases + fuzzy match on a closed dictionary."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Optional

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_ALIASES_PATH = os.path.join(_REPO_ROOT, "database", "symbol_resolution_aliases.json")
_aliases_loaded: Optional[dict[str, Any]] = None


def _load_aliases_doc() -> dict[str, Any]:
    global _aliases_loaded
    if _aliases_loaded is not None:
        return _aliases_loaded
    empty: dict[str, Any] = {"ticker_aliases": {}, "company_names": {}}
    if not os.path.isfile(_ALIASES_PATH):
        _aliases_loaded = empty
        return _aliases_loaded
    try:
        with open(_ALIASES_PATH, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError):
        _aliases_loaded = empty
        return _aliases_loaded
    if not isinstance(raw, dict):
        _aliases_loaded = empty
        return _aliases_loaded
    ta = raw.get("ticker_aliases") or {}
    cn = raw.get("company_names") or {}
    if not isinstance(ta, dict):
        ta = {}
    if not isinstance(cn, dict):
        cn = {}
    _aliases_loaded = {"ticker_aliases": ta, "company_names": cn}
    return _aliases_loaded


def apply_ticker_aliases(ticker: str) -> str:
    """Exact uppercase ticker → primary symbol from curated aliases (identity if unknown)."""
    u = (ticker or "").strip().upper()
    if not u:
        return u
    ta = _load_aliases_doc()["ticker_aliases"]
    entry = ta.get(u)
    if isinstance(entry, dict):
        sym = entry.get("symbol")
        if isinstance(sym, str) and sym.strip():
            return sym.strip().upper()
    return u


@dataclass(frozen=True)
class DeterministicMatch:
    symbol: str
    canonical_name: str
    confidence: float
    reason_code: str


def _fuzzy_min_ratio() -> float:
    try:
        return float(os.environ.get("SYMBOL_RESOLUTION_FUZZY_NAME_MIN_RATIO", "0.86"))
    except ValueError:
        return 0.86


def _deterministic_min_confidence() -> float:
    try:
        return float(os.environ.get("SYMBOL_RESOLUTION_DETERMINISTIC_MIN_CONFIDENCE", "0.82"))
    except ValueError:
        return 0.82


def try_deterministic_resolution(query: str) -> Optional[DeterministicMatch]:
    """Best curated match for query; None if below fuzzy threshold or no hit."""
    q = (query or "").strip()
    if not q:
        return None
    doc = _load_aliases_doc()
    ticker_aliases: dict[str, Any] = doc["ticker_aliases"]
    company_names: dict[str, Any] = doc["company_names"]
    q_lower = q.lower()
    upper = q.upper()

    tokens = re.findall(r"\b[A-Z]{2,5}\b", upper)
    for tok in sorted(set(tokens), key=len, reverse=True):
        entry = ticker_aliases.get(tok)
        if isinstance(entry, dict):
            sym = entry.get("symbol")
            if isinstance(sym, str) and sym.strip():
                name = entry.get("canonical_name") or sym
                return DeterministicMatch(
                    symbol=sym.strip().upper(),
                    canonical_name=name if isinstance(name, str) else sym.strip().upper(),
                    confidence=1.0,
                    reason_code="exact_ticker_alias",
                )

    best: Optional[DeterministicMatch] = None
    for key in sorted(
        (k for k in company_names if isinstance(k, str) and k.strip()),
        key=len,
        reverse=True,
    ):
        if key.lower() in q_lower:
            entry = company_names[key]
            if not isinstance(entry, dict):
                continue
            sym = entry.get("symbol")
            if not isinstance(sym, str) or not sym.strip():
                continue
            name = entry.get("canonical_name") or sym
            cand = DeterministicMatch(
                symbol=sym.strip().upper(),
                canonical_name=name if isinstance(name, str) else sym.strip().upper(),
                confidence=0.95,
                reason_code="company_name_substring",
            )
            best = cand
    if best is not None:
        return best

    min_r = _fuzzy_min_ratio()
    best_score = 0.0
    best_match: Optional[DeterministicMatch] = None
    for key in company_names:
        if not isinstance(key, str) or len(key.strip()) < 4:
            continue
        kl = key.lower()
        ratio = SequenceMatcher(None, q_lower, kl).ratio()
        if ratio > best_score:
            best_score = ratio
            entry = company_names[key]
            if isinstance(entry, dict):
                sym = entry.get("symbol")
                if isinstance(sym, str) and sym.strip():
                    name = entry.get("canonical_name") or sym
                    best_match = DeterministicMatch(
                        symbol=sym.strip().upper(),
                        canonical_name=name if isinstance(name, str) else sym.strip().upper(),
                        confidence=round(min(0.94, 0.65 + ratio * 0.35), 4),
                        reason_code="fuzzy_company_name",
                    )
    if best_match is not None and best_score >= min_r:
        return best_match
    return None


def passes_deterministic_threshold(match: DeterministicMatch) -> bool:
    return match.confidence >= _deterministic_min_confidence()
