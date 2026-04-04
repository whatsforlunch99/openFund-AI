"""Lightweight coverage hints for planner sufficiency (no LLM).

When multiple concrete facts exist (e.g. live price + internal SQL history), the planner
may treat the round as sufficient even if the sufficiency LLM is overly conservative.

Keeps WebSearcher/Librarian payload shape knowledge here so planner_agent stays orchestration-only.
"""

from __future__ import annotations

from typing import Any


def normalized_fund_price_line(websearcher_payload: dict[str, Any]) -> str:
    """One-line price summary from websearcher normalized_fund (same rules as planner formatting)."""
    nf = websearcher_payload.get("normalized_fund")
    if not isinstance(nf, list) or not nf:
        return ""
    parts: list[str] = []
    for rec in nf[:3]:
        if not isinstance(rec, dict):
            continue
        sym = rec.get("symbol") or "?"
        pr = rec.get("price")
        py = rec.get("price_yahoo")
        src = rec.get("source") if isinstance(rec.get("source"), dict) else {}
        price_src = src.get("price") if isinstance(src, dict) else None
        if pr is not None:
            try:
                line = f"{sym} ${float(pr):.2f}"
                if price_src:
                    line += f" ({price_src})"
                elif py is not None:
                    line += f" (Yahoo ${float(py):.2f})"
                parts.append(line)
            except (TypeError, ValueError):
                pass
        elif py is not None:
            try:
                parts.append(f"{sym} ${float(py):.2f} (Yahoo)")
            except (TypeError, ValueError):
                pass
    return "; ".join(parts) if parts else ""


def librarian_sql_row_count(lib: dict[str, Any] | None) -> int:
    """Best-effort row count from librarian sql payload (run_query or export_results)."""
    if not isinstance(lib, dict):
        return 0
    sql = lib.get("sql")
    if not isinstance(sql, dict):
        return 0
    rc = sql.get("row_count")
    if isinstance(rc, int) and rc >= 0:
        return rc
    data = sql.get("data")
    if isinstance(data, list):
        return len(data)
    rows = sql.get("rows")
    if isinstance(rows, list):
        return len(rows)
    return 0


def has_structured_timeseries_metrics(lib: dict[str, Any] | None) -> bool:
    if not isinstance(lib, dict):
        return False
    m = lib.get("structured_timeseries_metrics")
    return isinstance(m, dict) and bool(m.get("span_last_date"))


def strong_equity_evidence_for_sufficiency(collected: dict[str, Any]) -> bool:
    """True when we have a usable price line and librarian SQL history or computed series metrics."""
    w = collected.get("websearcher")
    if not isinstance(w, dict) or not normalized_fund_price_line(w).strip():
        return False
    lib = collected.get("librarian")
    if not isinstance(lib, dict):
        return False
    if has_structured_timeseries_metrics(lib):
        return True
    return librarian_sql_row_count(lib) >= 3
