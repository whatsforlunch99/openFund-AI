"""Deterministic metrics from ordered (date, close) series (stdlib only).

Used when Librarian returns yahoo_timeseries-style SQL rows so the planner/responder
see numeric summaries without extra LLM reasoning.
"""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any, Iterable, Optional


def _parse_day(v: Any) -> Optional[date]:
    if v is None:
        return None
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, str):
        s = v.strip()[:10]
        if len(s) >= 10 and s[4] == "-" and s[7] == "-":
            try:
                y, m, d = int(s[:4]), int(s[5:7]), int(s[8:10])
                return date(y, m, d)
            except ValueError:
                return None
    return None


def _parse_close(row: dict[str, Any]) -> Optional[float]:
    for key in ("level_close", "close", "price", "adj_close", "total_return_level"):
        v = row.get(key)
        if v is None:
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return None


def extract_date_close_rows(rows: Iterable[dict[str, Any]]) -> list[tuple[date, float]]:
    """Build sorted (date, close) pairs from SQL/export row dicts."""
    pairs: list[tuple[date, float]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        d = _parse_day(row.get("date") or row.get("dt") or row.get("timestamp"))
        c = _parse_close(row)
        if d is not None and c is not None and c > 0 and math.isfinite(c):
            pairs.append((d, c))
    pairs.sort(key=lambda x: x[0])
    # de-dupe by date: keep last close per day
    out: list[tuple[date, float]] = []
    seen: dict[date, float] = {}
    for d, c in pairs:
        seen[d] = c
    for d in sorted(seen.keys()):
        out.append((d, seen[d]))
    return out


def compute_timeseries_metrics(pairs: list[tuple[date, float]]) -> dict[str, Any]:
    """Return total return over span, CAGR, annualized volatility, max drawdown.

    Empty or single-point series returns an empty dict.
    """
    if len(pairs) < 2:
        return {}
    d0, p0 = pairs[0]
    d1, p1 = pairs[-1]
    if p0 <= 0 or p1 <= 0:
        return {}
    days = (d1 - d0).days
    if days < 1:
        return {}
    years = days / 365.25
    total_return = (p1 / p0) - 1.0
    if years > 1e-6:
        cagr = (p1 / p0) ** (1.0 / years) - 1.0
    else:
        cagr = total_return

    log_rets: list[float] = []
    for i in range(1, len(pairs)):
        _, prev = pairs[i - 1]
        _, cur = pairs[i]
        if prev > 0 and cur > 0:
            log_rets.append(math.log(cur / prev))
    if len(log_rets) >= 2:
        mean_lr = sum(log_rets) / len(log_rets)
        var = sum((x - mean_lr) ** 2 for x in log_rets) / (len(log_rets) - 1)
        daily_vol = math.sqrt(max(var, 0.0))
        ann_vol = daily_vol * math.sqrt(252.0)
    else:
        ann_vol = 0.0

    peak = pairs[0][1]
    max_dd = 0.0
    for _, px in pairs:
        if px > peak:
            peak = px
        if peak > 0:
            dd = (px / peak) - 1.0
            if dd < max_dd:
                max_dd = dd

    return {
        "span_first_date": d0.isoformat(),
        "span_last_date": d1.isoformat(),
        "span_trading_days": len(pairs),
        "span_calendar_years_approx": round(years, 4),
        "total_return_fraction": round(total_return, 6),
        "cagr_fraction": round(cagr, 6),
        "volatility_annualized": round(ann_vol, 6),
        "max_drawdown_fraction": round(max_dd, 6),
        "first_close": round(p0, 4),
        "last_close": round(p1, 4),
    }


def structured_metrics_from_sql_payload(sql: dict[str, Any]) -> Optional[dict[str, Any]]:
    """If sql payload has yahoo_timeseries-like rows, attach metrics under key structured_timeseries_metrics."""
    if not isinstance(sql, dict) or sql.get("error"):
        return None
    rows: list[dict[str, Any]] = []
    data = sql.get("data")
    if isinstance(data, list):
        rows = [r for r in data if isinstance(r, dict)]
    elif isinstance(sql.get("rows"), list):
        rows = [r for r in sql["rows"] if isinstance(r, dict)]
    if len(rows) < 2:
        return None
    sample = rows[0]
    keys = {str(k).lower() for k in sample.keys()}
    if "date" not in keys and "dt" not in keys:
        return None
    if not any(k in keys for k in ("level_close", "close", "price", "total_return_level")):
        return None
    pairs = extract_date_close_rows(rows)
    metrics = compute_timeseries_metrics(pairs)
    if not metrics:
        return None
    sym = sample.get("symbol")
    if isinstance(sym, str) and sym.strip():
        metrics = dict(metrics)
        metrics["symbol"] = sym.strip().upper()
    return metrics


def attach_structured_timeseries_metrics(reply: dict[str, Any]) -> None:
    """Mutate librarian reply dict: set structured_timeseries_metrics when SQL rows allow."""
    if not isinstance(reply, dict):
        return
    sql = reply.get("sql")
    if not isinstance(sql, dict):
        return
    m = structured_metrics_from_sql_payload(sql)
    if m:
        reply["structured_timeseries_metrics"] = m


def format_timeseries_metrics_for_final_response(stm: dict[str, Any]) -> str:
    """One sentence for planner final_response bundle; empty if not usable."""
    if not isinstance(stm, dict) or not stm.get("span_last_date"):
        return ""
    try:
        tr = float(stm.get("total_return_fraction") or 0) * 100
        cg = float(stm.get("cagr_fraction") or 0) * 100
        dd = float(stm.get("max_drawdown_fraction") or 0) * 100
        sym_m = stm.get("symbol") or ""
        sym_prefix = f"{sym_m} " if sym_m else ""
        return (
            f"Librarian {sym_prefix}series ({stm.get('span_first_date')}→"
            f"{stm.get('span_last_date')}, n≈{stm.get('span_trading_days')}): "
            f"total return ~{tr:.1f}%, CAGR ~{cg:.1f}%, max drawdown ~{dd:.1f}%."
        )
    except (TypeError, ValueError):
        return ""


def format_timeseries_metrics_for_sufficiency_chunk(stm: dict[str, Any]) -> str:
    """Single line for planner sufficiency aggregation text."""
    if not isinstance(stm, dict) or stm.get("cagr_fraction") is None:
        return ""
    return (
        "structured_timeseries_metrics: "
        f"total_return={stm.get('total_return_fraction')} "
        f"cagr={stm.get('cagr_fraction')} "
        f"max_dd={stm.get('max_drawdown_fraction')} "
        f"window={stm.get('span_first_date')}..{stm.get('span_last_date')}"
    )
