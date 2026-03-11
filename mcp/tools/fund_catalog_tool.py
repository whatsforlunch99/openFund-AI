"""P1 fund catalog: search ETFs and mutual funds via FinanceDatabase.

Optional dependency: pip install financedatabase.
Returns empty/error when the library is not installed.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    """Return current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def search(payload: dict) -> dict:
    """Search ETFs and mutual funds by query or name.

    Payload:
        query (str) or name (str): Search term (e.g. "Vanguard Total Stock").
        limit (int, optional): Max results to return. Default 10.

    Returns:
        {
            "matches": [{"symbol": str, "name": str, "asset_class": str?, "exchange": str?}, ...],
            "timestamp": str,
            "source": "FinanceDatabase"
        }
        Or {"error": str, "timestamp": str} when financeDatabase is not installed or search fails.
    """
    query = (payload.get("query") or payload.get("name") or "").strip()
    limit = int(payload["limit"]) if "limit" in payload and payload["limit"] is not None else 10
    if not query:
        return {"error": "Missing required 'query' or 'name'", "timestamp": _now_iso()}

    try:
        import financedatabase as fd
    except ImportError:
        return {
            "error": "FinanceDatabase not installed. pip install financedatabase",
            "timestamp": _now_iso(),
        }

    try:
        etfs = fd.ETFs()
        etf_df = None
        if hasattr(etfs, "search"):
            # FinanceDatabase search() takes keyword args, e.g. search(name="Vanguard")
            try:
                etf_df = etfs.search(name=query)
            except (TypeError, ValueError):
                try:
                    etf_df = etfs.search(summary=query)
                except (TypeError, ValueError):
                    pass
        fund_df = None
        if hasattr(fd, "MutualFunds"):
            try:
                funds = fd.MutualFunds()
                if hasattr(funds, "search"):
                    fund_df = funds.search(name=query)
            except (AttributeError, TypeError, ValueError):
                pass

        def _df_to_matches(df: Any, limit_remaining: int) -> list[dict]:
            out = []
            if df is None:
                return out
            # Handle pandas DataFrame (FinanceDatabase uses symbol as index)
            if hasattr(df, "to_dict") and hasattr(df, "index"):
                for idx, row in df.head(limit_remaining).iterrows():
                    if isinstance(row, dict):
                        r = dict(row)
                    else:
                        r = row.to_dict() if hasattr(row, "to_dict") else {}
                    sym = r.get("symbol") or str(idx)  # FinanceDatabase index is symbol
                    out.append({
                        "symbol": str(sym),
                        "name": str(r.get("name", r.get("long_name", "")) or ""),
                        "asset_class": r.get("asset_class") or r.get("category") or r.get("sector"),
                        "exchange": r.get("exchange"),
                    })
            elif isinstance(df, dict):
                for sym, row in list(df.items())[:limit_remaining]:
                    r = row if isinstance(row, dict) else (row.to_dict() if hasattr(row, "to_dict") else {})
                    out.append({
                        "symbol": str(sym),
                        "name": str(r.get("name", r.get("long_name", "")) or ""),
                        "asset_class": r.get("asset_class") or r.get("category") or r.get("sector"),
                        "exchange": r.get("exchange"),
                    })
            return out

        seen = set()
        matches = []
        for df in (etf_df, fund_df):
            for m in _df_to_matches(df, limit - len(matches)):
                if m["symbol"] in seen:
                    continue
                seen.add(m["symbol"])
                matches.append(m)
                if len(matches) >= limit:
                    break
            if len(matches) >= limit:
                break

        return {
            "matches": matches[:limit],
            "timestamp": _now_iso(),
            "source": "FinanceDatabase",
        }
    except Exception as e:
        logger.exception("fund_catalog search failed")
        return {"error": str(e), "timestamp": _now_iso()}
