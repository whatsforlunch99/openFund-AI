"""Layer 3–4 helpers: Yahoo identity + OpenFIGI cross-check."""

from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any

from util.openfigi_client import map_us_equity_ticker


def _name_align_score(a: str, b: str) -> float:
    a = (a or "").lower().strip()
    b = (b or "").lower().strip()
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return 0.95
    return SequenceMatcher(None, a, b).ratio()


def yahoo_validate_entity(
    candidate_symbol: str,
    inferred_entity_name: str,
) -> dict[str, Any]:
    """
    Use Yahoo chart meta (longName/shortName) to tie ticker to entity wording.

    Returns:
        {"ok": True, "matched_fields": {...}, "evidence_summary": str, "validation_method": "yahoo_chart_meta"}
        or {"ok": False, "error": str}
    """
    from openfund_mcp.tools import yahoo_finance_tool

    sym = (candidate_symbol or "").strip().upper()
    inferred = (inferred_entity_name or "").strip()
    if not sym:
        return {"ok": False, "error": "missing symbol"}
    res = yahoo_finance_tool.get_price({"symbol": sym})
    if res.get("error"):
        return {"ok": False, "error": str(res.get("error"))}

    long_name = str(res.get("longName") or "")
    short_name = str(res.get("shortName") or "")
    if not long_name and not short_name:
        return {"ok": False, "error": "yahoo returned no company name in meta"}

    best = 0.0
    for n in (long_name, short_name):
        s = _name_align_score(inferred, n)
        if s > best:
            best = s
    if inferred:
        if best < 0.5:
            return {
                "ok": False,
                "error": "inferred entity does not align with Yahoo company name",
                "matched_fields": {
                    "symbol": sym,
                    "long_name": long_name,
                    "short_name": short_name,
                },
            }
    return {
        "ok": True,
        "matched_fields": {
            "symbol": res.get("symbol") or sym,
            "long_name": long_name,
            "short_name": short_name,
        },
        "evidence_summary": f"Yahoo meta: {long_name or short_name}",
        "validation_method": "yahoo_chart_meta",
    }


def openfigi_validate_ticker(candidate_symbol: str) -> dict[str, Any]:
    """Layer 4: OpenFIGI mapping; returns client dict with ok flag."""
    return map_us_equity_ticker(candidate_symbol)
