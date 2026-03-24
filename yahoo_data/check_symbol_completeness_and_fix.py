#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable
from urllib.parse import unquote

BASE_DIR = Path(__file__).resolve().parent
CSV_DIR = BASE_DIR / "csv_files"

INDEX_SYMBOL_MAP = CSV_DIR / "index_symbol_map.csv"
YAHOO_TIMESERIES = CSV_DIR / "yahoo_timeseries.csv"
YAHOO_INDICATORS = CSV_DIR / "yahoo_indicators.csv"
YAHOO_QUOTE_METRICS = CSV_DIR / "yahoo_quote_metrics.csv"
YAHOO_KEY_STATISTICS = CSV_DIR / "yahoo_key_statistics.csv"

YAHOO_CRAWLER = BASE_DIR / "yahoo_crawler.py"
YAHOO_QUOTE_PAGES = BASE_DIR / "yahoo_quote_pages.py"
YAHOO_KEY_STATS_PAGES = BASE_DIR / "yahoo_key_statistics_pages.py"

_CHART_SYM_RE = re.compile(r"/v8/finance/chart/([^/?]+)", re.I)
_QUOTE_SUMMARY_RE = re.compile(r"/v10/finance/quoteSummary/([^?]+)", re.I)


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8", errors="replace", newline="") as f:
        return list(csv.DictReader(f))


def parse_symbols_arg(s: str) -> list[str]:
    s = (s or "").strip()
    if not s:
        return []
    if s.startswith("["):
        try:
            arr = json.loads(s)
            if isinstance(arr, list):
                return [str(x).strip() for x in arr if str(x).strip()]
        except Exception:
            pass
    return [x.strip() for x in s.split(",") if x.strip()]


def normalize_symbols(items: Iterable[str]) -> set[str]:
    return {str(x).strip() for x in items if str(x).strip()}


def extract_symbol_from_yahoo_url(url: str) -> str | None:
    if not url or not isinstance(url, str):
        return None
    u = unquote(url)
    m = _CHART_SYM_RE.search(u) or _QUOTE_SUMMARY_RE.search(u)
    if not m:
        return None
    sym = m.group(1).strip()
    return sym or None


def chunked(items: list[str], n: int) -> Iterable[list[str]]:
    for i in range(0, len(items), n):
        yield items[i : i + n]


def print_missing(label: str, missing: list[str], *, limit: int = 30) -> None:
    print(f"- {label}: missing {len(missing)}")
    if not missing:
        return
    preview = missing[:limit]
    print(f"  sample({len(preview)}): {preview}")
    if len(missing) > limit:
        print(f"  ... +{len(missing) - limit} more")


def ensure_cookie_env() -> None:
    if os.environ.get("YAHOO_A1") and os.environ.get("YAHOO_A1S") and os.environ.get("YAHOO_A3"):
        return
    cookie_val = input(
        "Paste Yahoo cookie value in form d=<...>&S=<...> (used for YAHOO_A1/YAHOO_A1S/YAHOO_A3): "
    ).strip()
    if not cookie_val:
        raise ValueError("Cookie value cannot be empty.")
    os.environ["YAHOO_A1"] = cookie_val
    os.environ["YAHOO_A1S"] = cookie_val
    os.environ["YAHOO_A3"] = cookie_val


def run_script(script: Path, symbols: list[str], *, dry_run: bool) -> None:
    if not symbols:
        return
    cmd = [sys.executable, str(script), "--symbols", json.dumps(symbols)]
    if dry_run:
        print("[DRY-RUN]", " ".join(cmd))
        return
    print("[RUN]", " ".join(cmd))
    subprocess.run(cmd, check=True, cwd=str(BASE_DIR))


def compute_missing() -> dict[str, list[str]]:
    rows = read_csv_rows(INDEX_SYMBOL_MAP)
    if not rows:
        raise FileNotFoundError(f"Missing or empty: {INDEX_SYMBOL_MAP}")

    index_ids = sorted(normalize_symbols(r.get("index_id", "") for r in rows))
    id_to_symbol = {
        r.get("index_id", "").strip(): r.get("yahoo_symbol", "").strip()
        for r in rows
        if r.get("index_id", "").strip()
    }

    # Equity symbols for key statistics check (using yahoo_symbol)
    equity_symbols = sorted(
        normalize_symbols(
            r.get("yahoo_symbol", "")
            for r in rows
            if (r.get("quoteType", "") or "").strip().lower() == "equity"
        )
    )

    ts_rows = read_csv_rows(YAHOO_TIMESERIES)
    ind_rows = read_csv_rows(YAHOO_INDICATORS)
    qm_rows = read_csv_rows(YAHOO_QUOTE_METRICS)
    ks_rows = read_csv_rows(YAHOO_KEY_STATISTICS)

    ts_ids = normalize_symbols(r.get("index_id", "") for r in ts_rows)
    ind_ids = normalize_symbols(r.get("index_id", "") for r in ind_rows)
    qm_syms = normalize_symbols(r.get("symbol", "") for r in qm_rows)


    # For quote/crawl checks, expected symbol is yahoo_symbol mapped from each index_id.
    expected_mapped_syms = sorted(
        normalize_symbols(id_to_symbol.get(idx, "") for idx in index_ids)
    )

    ks_syms = normalize_symbols(r.get("symbol", "") for r in ks_rows)

    missing = {
        "yahoo_timeseries.csv": sorted(set(index_ids) - ts_ids),
        "yahoo_indicators.csv": sorted(set(index_ids) - ind_ids),
        "yahoo_quote_metrics.csv": sorted(set(expected_mapped_syms) - qm_syms),
        "yahoo_key_statistics.csv (equity only)": sorted(set(equity_symbols) - ks_syms),
        # Useful for deciding crawler inputs:
        "_missing_for_yahoo_crawler_index_ids": sorted(
            set(index_ids)
            - (ts_ids & ind_ids)
        ),
    }
    return missing


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Check symbol completeness across Yahoo CSVs and optionally run crawlers "
            "for missing symbols."
        )
    )
    parser.add_argument("--run", action="store_true", help="Run crawlers to fill gaps.")
    parser.add_argument("--dry-run", action="store_true", help="Show crawl commands without executing.")
    parser.add_argument("--chunk-size", type=int, default=25, help="Symbols per crawler invocation.")
    args = parser.parse_args()

    print("== Initial completeness check ==")
    missing = compute_missing()
    print_missing("yahoo_timeseries.csv", missing["yahoo_timeseries.csv"])
    print_missing("yahoo_indicators.csv", missing["yahoo_indicators.csv"])
    print_missing("yahoo_quote_metrics.csv", missing["yahoo_quote_metrics.csv"])
    print_missing("yahoo_key_statistics.csv (equity only)", missing["yahoo_key_statistics.csv (equity only)"])

    if not args.run:
        print("\nRun with --run to execute crawlers for missing symbols.")
        return 0

    if args.chunk_size <= 0:
        raise ValueError("--chunk-size must be > 0")

    ensure_cookie_env()

    # 1) yahoo_crawler fixes timeseries+indicators 
    to_crawl_index_ids = sorted(
        set(missing["yahoo_timeseries.csv"]) | set(missing["yahoo_indicators.csv"]) | set(missing["_missing_for_yahoo_crawler_index_ids"])
    )
    if to_crawl_index_ids:
        print(f"\n== Running yahoo_crawler.py for {len(to_crawl_index_ids)} index_id symbols ==")
        for ch in chunked(to_crawl_index_ids, args.chunk_size):
            run_script(YAHOO_CRAWLER, ch, dry_run=args.dry_run)
    else:
        print("\nNo missing symbols for yahoo_crawler.py.")

    # 2) quote metrics
    to_crawl_quote = missing["yahoo_quote_metrics.csv"]
    if to_crawl_quote:
        print(f"\n== Running yahoo_quote_pages.py for {len(to_crawl_quote)} symbols ==")
        for ch in chunked(to_crawl_quote, args.chunk_size):
            run_script(YAHOO_QUOTE_PAGES, ch, dry_run=args.dry_run)
    else:
        print("\nNo missing symbols for yahoo_quote_pages.py.")

    # 3) key stats (equity only)
    to_crawl_key_stats = missing["yahoo_key_statistics.csv (equity only)"]
    if to_crawl_key_stats:
        print(f"\n== Running yahoo_key_statistics_pages.py for {len(to_crawl_key_stats)} equity symbols ==")
        for ch in chunked(to_crawl_key_stats, args.chunk_size):
            run_script(YAHOO_KEY_STATS_PAGES, ch, dry_run=args.dry_run)
    else:
        print("\nNo missing equity symbols for yahoo_key_statistics_pages.py.")

    print("\n== Final completeness check ==")
    final_missing = compute_missing()
    print_missing("yahoo_timeseries.csv", final_missing["yahoo_timeseries.csv"])
    print_missing("yahoo_indicators.csv", final_missing["yahoo_indicators.csv"])
    print_missing("yahoo_quote_metrics.csv", final_missing["yahoo_quote_metrics.csv"])
    print_missing(
        "yahoo_key_statistics.csv (equity only)",
        final_missing["yahoo_key_statistics.csv (equity only)"],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

