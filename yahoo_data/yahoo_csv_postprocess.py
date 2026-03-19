"""
Post-process Yahoo Finance CSV exports into wide pandas DataFrames.

Conventions
-----------
- Time-series / snapshot tables: ``MultiIndex`` with names ``symbol`` and
  ``timestamp`` (datetime) or ``date`` (date-only from OHLC files).
- ``index_symbol_map``: reference table; index is ``symbol`` only (no time).
- ``yahoo_crawl_log``: request log; ``symbol`` parsed from URL when possible;
  ``MultiIndex(symbol, timestamp)`` with NaN symbol rows dropped by default.

Each ``postprocess_*`` accepts either a pre-loaded ``DataFrame`` or ``path``
(defaults to ``<this_dir>/<csv_filename>``).

Return shapes (index names → column content)
--------------------------------------------
``postprocess_yahoo_quote_metrics``
    Index ``(symbol, timestamp)``. Columns: parsed numerics, split
    ``day_*`` / ``week_52_*`` / ``bid_*`` / ``ask_*`` / dividend fields,
    plus ``market_cap_intraday_parsed``, ``currency``, dates/strings,
    ``source_url``, ``status``.

``postprocess_yahoo_key_statistics``
    Long format; index ``(symbol, timestamp, url, status)``. Categorical
    ``category`` (e.g. Market Cap, Fiscal Year) and ``sub_category`` (e.g.
    Current, Fiscal Year Ends); column ``value``. JSON wrappers
    ``valuation_measures`` / ``sections`` are merged away. Optional
    ``key_statistics_json_pretty`` if ``include_pretty_merged_json=True``.

``postprocess_yahoo_indicators``
    Long format; index ``(symbol, date)``. Categorical ``indicator_group`` and
    ``indicator_name``; columns ``index_id``, ``indicator_value`` (string),
    ``source_url``.

``postprocess_yahoo_timeseries`` / ``postprocess_index_levels``
    Index ``(symbol, date)``. OHLC (timeseries: open/high/low/close order),
    ``total_return_level``, technicals (timeseries only), metadata URL columns.

``postprocess_index_symbol_map``
    Index ``symbol`` (from ``yahoo_symbol``). Columns: ``index_id``,
    ``confidence``, ``quoteType``, etc.

``postprocess_yahoo_crawl_log``
    Index ``(symbol, timestamp)``. Columns: ``url``, ``status``, ``reason``,
    ``crumb``. Use ``drop_unparsed_symbol=False`` to keep rows without a parsed
    ticker (index may contain NaN symbols).

Registry: ``POSTPROCESS_BY_FILENAME``, ``postprocess_file("yahoo_indicators.csv")``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote


import pandas as pd

_DIR = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _default_path(filename: str) -> Path:
    return _DIR / filename


def _load_df(
    df: pd.DataFrame | None,
    path: str | Path | None,
    filename: str,
) -> pd.DataFrame:
    if df is not None:
        return df.copy()
    p = Path(path) if path is not None else _default_path(filename)
    return pd.read_csv(p, dtype=str, keep_default_na=False, na_values=[""])


def slugify_key(s: str) -> str:
    """Turn a label into a safe column fragment."""
    s = str(s).strip()
    s = re.sub(r"[^\w]+", "_", s, flags=re.UNICODE)
    s = re.sub(r"_+", "_", s).strip("_")
    return s or "empty"


def parse_timestamp_series(s: pd.Series) -> pd.Series:
    """Parse mixed ISO / date strings to datetime64[ns]."""
    return pd.to_datetime(s, errors="coerce", utc=False)


def parse_date_series(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, errors="coerce").dt.normalize()


def strip_commas_to_number(s: pd.Series) -> pd.Series:
    out = s.astype(str).str.replace(",", "", regex=False)
    return pd.to_numeric(out, errors="coerce")


def parse_yahoo_scaled_number(val: Any) -> float | None:
    """
    Parse strings like '3.737T', '47.47M', '1,234', '32.14'.
    Returns float or None.
    """
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        return float(val)
    s = str(val).strip()
    if not s or s.lower() in ("nan", "none", "n/a"):
        return None
    s = s.replace(",", "")
    mult = 1.0
    suffix = s[-1].upper()
    if suffix in ("T", "B", "M", "K"):
        factor = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}[suffix]
        s = s[:-1].strip()
        mult = factor
    try:
        return float(s) * mult
    except ValueError:
        return None


def parse_yahoo_scaled_series(s: pd.Series) -> pd.Series:
    return s.map(lambda x: parse_yahoo_scaled_number(x))


def dedupe_multiindex(
    df: pd.DataFrame,
    *,
    keep: str = "last",
    sort: bool = True,
) -> pd.DataFrame:
    if sort and df.index.nlevels >= 1:
        df = df.sort_index()
    return df[~df.index.duplicated(keep=keep)]


def _set_symbol_timestamp_index(
    df: pd.DataFrame,
    symbol_col: str,
    time_col: str,
    *,
    time_is_date_only: bool = False,
) -> pd.DataFrame:
    sym = df[symbol_col].astype(str)
    if time_is_date_only:
        ts = parse_date_series(df[time_col])
        names = ["symbol", "date"]
    else:
        ts = parse_timestamp_series(df[time_col])
        names = ["symbol", "timestamp"]
    out = df.drop(columns=[symbol_col, time_col], errors="ignore")
    out.index = pd.MultiIndex.from_arrays([sym.values, ts.values], names=names)
    return dedupe_multiindex(out, keep="last")


# ---------------------------------------------------------------------------
# yahoo_quote_metrics.csv
# ---------------------------------------------------------------------------


def _split_range_col(series: pd.Series, low_name: str, high_name: str) -> pd.DataFrame:
    """Split 'a - b' into two numeric columns."""
    exp = series.astype(str).str.split(r"\s*-\s*", n=1, expand=True, regex=True)
    low = pd.to_numeric(exp[0], errors="coerce")
    if exp.shape[1] > 1:
        high = pd.to_numeric(exp[1], errors="coerce")
    else:
        high = pd.Series(pd.NA, index=series.index, dtype="Float64")
    return pd.DataFrame({low_name: low, high_name: high})


def _split_bid_ask_col(series: pd.Series, prefix: str) -> pd.DataFrame:
    """Split '253.86 x 200' into price and size."""
    parts = series.astype(str).str.split(r"\s+x\s*", n=1, regex=True, expand=True)
    price = pd.to_numeric(parts[0], errors="coerce")
    size = pd.to_numeric(parts[1], errors="coerce") if parts.shape[1] > 1 else pd.Series(pd.NA, index=series.index, dtype="Float64")
    return pd.DataFrame({f"{prefix}_price": price, f"{prefix}_size": size})


def _split_forward_dividend_yield(series: pd.Series) -> pd.DataFrame:
    """Split '1.04 (0.41%)' into numeric dividend and percent."""
    m = series.astype(str).str.extract(
        r"^\s*([0-9.,]+)\s*(?:\(\s*([0-9.,]+)\s*%\s*\))?",
        expand=True,
    )
    div = pd.to_numeric(m[0].str.replace(",", "", regex=False), errors="coerce")
    pct = pd.to_numeric(m[1], errors="coerce")
    return pd.DataFrame({"forward_dividend": div, "forward_yield_percent": pct})


def postprocess_yahoo_quote_metrics(
    df: pd.DataFrame | None = None,
    path: str | Path | None = None,
) -> pd.DataFrame:
    """
    Wide quote snapshot per (symbol, as_of_timestamp).

    Splits composite string fields (ranges, bid/ask, dividend/yield) and
    coerces numerics; keeps metadata columns ``source_url``, ``status``,
    ``currency``, ``earnings_date_est``, ``ex_dividend_date`` as strings.
    """
    raw = _load_df(df, path, "yahoo_quote_metrics.csv")
    df = raw.copy()

    # Ranges
    if "day_range" in df.columns:
        dr = _split_range_col(df["day_range"], "day_low", "day_high")
        df = pd.concat([df.drop(columns=["day_range"]), dr], axis=1)
    if "week_52_range" in df.columns:
        wr = _split_range_col(df["week_52_range"], "week_52_low", "week_52_high")
        df = pd.concat([df.drop(columns=["week_52_range"]), wr], axis=1)
    if "bid" in df.columns:
        bd = _split_bid_ask_col(df["bid"], "bid")
        df = pd.concat([df.drop(columns=["bid"]), bd], axis=1)
    if "ask" in df.columns:
        ak = _split_bid_ask_col(df["ask"], "ask")
        df = pd.concat([df.drop(columns=["ask"]), ak], axis=1)
    if "forward_dividend_yield" in df.columns:
        fd = _split_forward_dividend_yield(df["forward_dividend_yield"])
        df = pd.concat([df.drop(columns=["forward_dividend_yield"]), fd], axis=1)

    num_cols_plain = [
        "price",
        "change",
        "change_percent",
        "prev_close",
        "open",
        "beta_5y_monthly",
        "pe_ttm",
        "eps_ttm",
        "target_est_1y",
    ]
    for c in num_cols_plain:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    if "volume" in df.columns:
        df["volume"] = strip_commas_to_number(df["volume"])
    if "avg_volume" in df.columns:
        df["avg_volume"] = strip_commas_to_number(df["avg_volume"])
    if "market_cap" in df.columns:
        df["market_cap"] = pd.to_numeric(df["market_cap"], errors="coerce")
    if "market_cap_intraday" in df.columns:
        df["market_cap_intraday_parsed"] = parse_yahoo_scaled_series(df["market_cap_intraday"])

    out = _set_symbol_timestamp_index(df, "symbol", "as_of_timestamp", time_is_date_only=False)
    return out


# ---------------------------------------------------------------------------
# yahoo_key_statistics.csv
# ---------------------------------------------------------------------------



def merge_key_statistics_json_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Merge out 'valuation_measures' and 'sections' top-level keys into one dict."""
    merged: dict[str, Any] = {}
    vm = data.get("valuation_measures")
    if isinstance(vm, dict):
        merged.update(vm)
    sec = data.get("sections")
    if isinstance(sec, dict):
        merged.update(sec)
    for k, v in data.items():
        if k in ("valuation_measures", "sections"):
            continue
        merged[k] = v
    return merged

def pretty_key_statistics_json(blob: str, *, indent: int = 2) -> str:
    """Return pretty-printed JSON for debugging / optional column."""
    if not blob or str(blob).strip() in ("", "{}", "nan"):
        return "{}"
    try:
        data = json.loads(blob)
    except (json.JSONDecodeError, TypeError):
        return json.dumps({"_json_parse_error": str(blob)[:500]}, indent=indent, ensure_ascii=False)
    merged = merge_key_statistics_json_dict(data if isinstance(data, dict) else {})
    return json.dumps(merged, indent=indent, ensure_ascii=False, default=str)

def _parse_key_statistics_merged(blob: str) -> dict[str, Any] | None:
    if not blob or str(blob).strip() in ("", "{}", "nan"):
        return {}
    try:
        data = json.loads(blob)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    return merge_key_statistics_json_dict(data)

def _iter_nested_key_stat_leaves(obj: dict[str, Any], prefix: str) -> list[tuple[str, Any]]:
    """Deep dict walk; paths like ``A, B, C`` for sub_category."""
    rows: list[tuple[str, Any]] = []
    for k, v in obj.items():
        p = f"{prefix}, {k}" if prefix else str(k)
        if isinstance(v, dict):
            rows.extend(_iter_nested_key_stat_leaves(v, p))
        else:
            rows.append((p, v))
    return rows


def _iter_merged_key_statistics_rows(merged: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Convert merged key statistics into long format rows:
    - category: top-level key (e.g. "Market Cap", "Fiscal Year", "Profitability")
    - sub_category: label for the value (e.g. "Current", "12/31/2025", "Fiscal Year Ends")
    - value: scalar
    """
    out: list[dict[str, Any]] = []
    for category, body in merged.items():
        cat = str(category)
        if not isinstance(body, dict):
            out.append({"category": cat, "sub_category": pd.NA, "value": body})
            continue
        for sub_key, val in body.items():
            sk = str(sub_key)
            if isinstance(val, dict):
                for leaf_key, leaf_val in val.items():
                    lk = str(leaf_key)
                    if isinstance(leaf_val, dict):
                        for path, lv in _iter_nested_key_stat_leaves(leaf_val, f"{sk}, {lk}"):
                            out.append({"category": cat, "sub_category": path, "value": lv})
                    else:
                        out.append({"category": cat, "sub_category": f"{sk}, {lk}", "value": leaf_val})
            else:
                out.append({"category": cat, "sub_category": sk, "value": val})
    return out


def postprocess_yahoo_key_statistics(
    df: pd.DataFrame | None = None,
    path: str | Path | None = None,
    *,
    include_pretty_merged_json: bool = False,
) -> pd.DataFrame:
    """
    Long-format key statistics from ``yahoo_key_statistics.csv``.

    Index: ``(symbol, timestamp, url, status)`` — same scrape shares these levels
    across many rows. Value columns: ``category``, ``sub_category``, ``value``.
    Use ``.reset_index()`` for a flat table with columns
    ``symbol, category, sub_category, timestamp, value, url, status``.

    JSON wrappers ``valuation_measures`` and ``sections`` are merged away before
    expanding rows. Optional ``key_statistics_json_pretty`` when
    ``include_pretty_merged_json=True``.
    """
    raw = _load_df(df, path, "yahoo_key_statistics.csv")
    all_rows: list[dict[str, Any]] = []

    for _, row in raw.iterrows():
        blob = row.get("key_statistics_json", "")
        sym = row.get("symbol", "")
        ts = row.get("as_of_timestamp", "")
        status = row.get("status", "")
        source_url = row.get("source_url", "")
        pretty = pretty_key_statistics_json(str(blob)) if include_pretty_merged_json else None

        merged = _parse_key_statistics_merged(str(blob))
        if merged is None:
            all_rows.append({
                "symbol": sym,
                "timestamp": ts,
                "category": "_parse_error",
                "sub_category": pd.NA,
                "value": str(blob)[:200],
                "url": source_url,
                "status": status,
                **({"key_statistics_json_pretty": pretty} if pretty else {})
            })
            continue

        if not merged:
            all_rows.append({
                "symbol": sym,
                "timestamp": ts,
                "category": pd.NA,
                "sub_category": pd.NA,
                "value": pd.NA,
                "url": source_url,
                "status": status,
                **({"key_statistics_json_pretty": pretty} if pretty else {})
            })
            continue

        for rec in _iter_merged_key_statistics_rows(merged):
            r = {
                "symbol": sym,
                "timestamp": ts,
                "category": rec["category"],
                "sub_category": rec["sub_category"],
                "value": rec["value"],
                "url": source_url,
                "status": status,
            }
            if pretty is not None:
                r["key_statistics_json_pretty"] = pretty
            all_rows.append(r)

    out = pd.DataFrame(all_rows)
    if out.empty:
        return out

    # Convert timestamp strings to datetime
    out["timestamp"] = pd.to_datetime(out["timestamp"], errors="coerce")

    out["category"] = out["category"].astype("category")
    out["sub_category"] = out["sub_category"].astype("category")

    out = out.set_index(["symbol", "timestamp", "url", "status"]).sort_index()
    return out


# ---------------------------------------------------------------------------
# yahoo_indicators.csv
# ---------------------------------------------------------------------------


def postprocess_yahoo_indicators(
    df: pd.DataFrame | None = None,
    path: str | Path | None = None,
) -> pd.DataFrame:
    """
    Long format: ``indicator_group`` and ``indicator_name`` are categorical columns
    (top-level group vs field). One row per indicator; index ``(symbol, date)``.

    Duplicate keys ``(symbol, date, indicator_group, indicator_name)`` keep the last row.
    """
    raw = _load_df(df, path, "yahoo_indicators.csv")
    df = raw.copy()
    df = df.rename(columns={"yahoo_symbol": "symbol", "as_of_date": "date"})
    df["date"] = parse_date_series(df["date"])
    df["symbol"] = df["symbol"].astype(str)
    df["indicator_group"] = df["indicator_group"].astype("category")
    df["indicator_name"] = df["indicator_name"].astype("category")

    key_cols = ["symbol", "date", "indicator_group", "indicator_name"]
    df = df.sort_values(key_cols)
    df = df.drop_duplicates(subset=key_cols, keep="last")

    # Keep values as strings (mixed semantics across indicator_name); coerce in analysis if needed
    df["indicator_value"] = df["indicator_value"].astype(str)

    keep = [c for c in ("index_id", "symbol", "date", "indicator_group", "indicator_name", "indicator_value", "source_url") if c in df.columns]
    df = df[keep]
    df = df.set_index(["symbol", "date"])
    return df.sort_index()


# ---------------------------------------------------------------------------
# yahoo_timeseries.csv & index_levels.csv
# ---------------------------------------------------------------------------


def _postprocess_ohlc_wide(
    df: pd.DataFrame,
    *,
    reorder_ohlc: bool,
) -> pd.DataFrame:
    d = df.copy()
    d["date"] = parse_date_series(d["date"])

    meta_cols = [c for c in ("source_url", "source", "technical_source_url") if c in d.columns]
    ohlc_order = ["level_open", "level_high", "level_low", "level_close"]
    ohlc_present = [c for c in ohlc_order if c in d.columns]
    exclude = {"index_id", "date", *ohlc_present, *meta_cols}
    other = [c for c in d.columns if c not in exclude]
    numeric_exclude = {"index_id", "date", *meta_cols}
    numeric_cols = [c for c in d.columns if c not in numeric_exclude]

    for c in numeric_cols:
        d[c] = pd.to_numeric(d[c], errors="coerce")

    if reorder_ohlc:
        key_cols = [c for c in ("index_id", "date") if c in d.columns]
        ordered = key_cols + ohlc_present + [c for c in other if c not in ohlc_present]
        ordered = [c for c in ordered if c in d.columns]
        ordered = ordered + [c for c in meta_cols if c in d.columns]
        d = d[ordered]

    sym = d["index_id"].astype(str)
    dt = d["date"]
    body = d.drop(columns=["index_id", "date"])
    body.index = pd.MultiIndex.from_arrays([sym.values, dt.values], names=["symbol", "date"])
    return dedupe_multiindex(body, keep="last")


def postprocess_yahoo_timeseries(
    df: pd.DataFrame | None = None,
    path: str | Path | None = None,
) -> pd.DataFrame:
    """
    OHLC + technicals per (symbol, date). Column order: OHLC, other numerics,
    then URL/metadata columns.
    """
    raw = _load_df(df, path, "yahoo_timeseries.csv")
    return _postprocess_ohlc_wide(raw, reorder_ohlc=True)


def postprocess_index_levels(
    df: pd.DataFrame | None = None,
    path: str | Path | None = None,
) -> pd.DataFrame:
    """Index levels only (no technical columns). Same index as timeseries."""
    raw = _load_df(df, path, "index_levels.csv")
    return _postprocess_ohlc_wide(raw, reorder_ohlc=False)


# ---------------------------------------------------------------------------
# index_symbol_map.csv
# ---------------------------------------------------------------------------


def postprocess_index_symbol_map(
    df: pd.DataFrame | None = None,
    path: str | Path | None = None,
) -> pd.DataFrame:
    """
    Static reference: one row per ``yahoo_symbol``; index name ``symbol``.
    No timestamp level.
    """
    raw = _load_df(df, path, "index_symbol_map.csv")
    d = raw.copy()
    d = d.set_index(d["yahoo_symbol"].astype(str))
    d.index.name = "symbol"
    d = d.drop(columns=["yahoo_symbol"], errors="ignore")
    return d[~d.index.duplicated(keep="last")]


# ---------------------------------------------------------------------------
# yahoo_crawl_log.csv
# ---------------------------------------------------------------------------

_CHART_SYM_RE = re.compile(r"/v8/finance/chart/([^/?]+)", re.I)
_QUOTE_SUMMARY_RE = re.compile(r"/v10/finance/quoteSummary/([^?]+)", re.I)


def extract_symbol_from_yahoo_url(url: str) -> str | None:
    if not url or not isinstance(url, str):
        return None
    u = unquote(url)
    m = _CHART_SYM_RE.search(u) or _QUOTE_SUMMARY_RE.search(u)
    if not m:
        return None
    return m.group(1).strip() or None


def postprocess_yahoo_crawl_log(
    df: pd.DataFrame | None = None,
    path: str | Path | None = None,
    *,
    drop_unparsed_symbol: bool = True,
) -> pd.DataFrame:
    """
    HTTP crawl log with optional ``symbol`` parsed from ``url``.

    If ``drop_unparsed_symbol`` is True (default), rows without a parsable
    symbol are removed before setting the MultiIndex.
    """
    raw = _load_df(df, path, "yahoo_crawl_log.csv")
    d = raw.copy()
    d["symbol"] = d["url"].map(extract_symbol_from_yahoo_url)
    if drop_unparsed_symbol:
        d = d[d["symbol"].notna() & (d["symbol"].astype(str).str.len() > 0)]
    d["timestamp"] = parse_timestamp_series(d["timestamp"])
    sym = d["symbol"].astype(str)
    ts = d["timestamp"]
    rest = d.drop(columns=["symbol", "timestamp"])
    rest.index = pd.MultiIndex.from_arrays([sym.values, ts.values], names=["symbol", "timestamp"])
    return rest.sort_index()


# ---------------------------------------------------------------------------
# Registry (optional convenience)
# ---------------------------------------------------------------------------

POSTPROCESS_BY_FILENAME: dict[str, Any] = {
    "yahoo_quote_metrics.csv": postprocess_yahoo_quote_metrics,
    "yahoo_key_statistics.csv": postprocess_yahoo_key_statistics,
    "yahoo_indicators.csv": postprocess_yahoo_indicators,
    "yahoo_timeseries.csv": postprocess_yahoo_timeseries,
    "index_levels.csv": postprocess_index_levels,
    "index_symbol_map.csv": postprocess_index_symbol_map,
    "yahoo_crawl_log.csv": postprocess_yahoo_crawl_log,
}


def postprocess_file(filename: str, **kwargs: Any) -> pd.DataFrame:
    """Dispatch by CSV basename."""
    fn = Path(filename).name
    if fn not in POSTPROCESS_BY_FILENAME:
        raise KeyError(f"No postprocessor registered for {fn!r}")
    return POSTPROCESS_BY_FILENAME[fn](**kwargs)


if __name__ == "__main__":
    for name in sorted(POSTPROCESS_BY_FILENAME):
        fn = POSTPROCESS_BY_FILENAME[name]
        try:
            out = fn()
            print(f"{name}: {out.shape} index={out.index.names}")
        except Exception as e:  # noqa: BLE001
            print(f"{name}: ERROR {e}")
