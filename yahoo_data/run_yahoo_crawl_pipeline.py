#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Iterable


HERE = Path(__file__).resolve().parent
CSV_DIR = HERE / "csv_files"
INDEX_SYMBOL_MAP_PATH = CSV_DIR / "index_symbol_map.csv"

CRAWLER_SCRIPT = HERE / "yahoo_crawler.py"
KEY_STATS_PAGES_SCRIPT = HERE / "yahoo_key_statistics_pages.py"
QUOTE_PAGES_SCRIPT = HERE / "yahoo_quote_pages.py"


def dedupe_in_order(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in items:
        if x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out


def chunked(items: list[str], *, chunk_size: int) -> Iterable[list[str]]:
    for i in range(0, len(items), chunk_size):
        yield items[i : i + chunk_size]


def run_script(script_path: Path, *, symbols: list[str], dry_run: bool) -> None:
    # Sub-scripts parse `--symbols` as comma-separated or JSON list.
    cmd_symbols = ",".join(symbols)
    cmd = [sys.executable, str(script_path), "--symbols", cmd_symbols]

    if dry_run:
        print("[DRY-RUN]", " ".join(cmd))
        return

    print("[RUN]", " ".join(cmd))
    subprocess.run(cmd, check=True, cwd=str(HERE))


def read_index_symbol_map_rows() -> list[dict[str, str]]:
    if not INDEX_SYMBOL_MAP_PATH.exists():
        raise FileNotFoundError(f"Missing {INDEX_SYMBOL_MAP_PATH}")

    with open(INDEX_SYMBOL_MAP_PATH, "r", encoding="utf-8", errors="replace", newline="") as f:
        reader = csv.DictReader(f)
        return list(reader)


def parse_symbols_input(s: str) -> list[str]:
    """
    Parse CLI `--symbols` input as:
    - comma-separated list: "^IXIC,SPY,MSFT"
    - JSON array: ["^IXIC","SPY","MSFT"]
    """
    s = (s or "").strip()
    if not s:
        return []
    if s.startswith("["):
        try:
            arr = json.loads(s)
            return [str(x).strip() for x in arr if str(x).strip()]
        except Exception:
            # Fall through to comma parsing
            pass
    return [x.strip() for x in s.split(",") if x.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Yahoo crawling pipeline")
    parser.add_argument("--dry-run", action="store_true", help="Print commands without executing")
    parser.add_argument(
        "--symbols",
        type=str,
        default="",
        help="Optional list of `index_id` inputs to crawl (comma-separated or JSON list). Example: --symbols ^IXIC,SPY",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=80,
        help="Number of symbols per subprocess invocation",
    )
    args = parser.parse_args()

    # Prompt for a single cookie value used as YAHOO_A1/YAHOO_A1S/YAHOO_A3.
    cookie_val = input(
        "Paste YAHOO cookie value (the part after '=') to use for YAHOO_A1, YAHOO_A1S, YAHOO_A3: "
    ).strip()
    if not cookie_val:
        raise ValueError("Cookie value cannot be empty.")

    os.environ["YAHOO_A1"] = cookie_val
    os.environ["YAHOO_A1S"] = cookie_val
    os.environ["YAHOO_A3"] = cookie_val

    rows = read_index_symbol_map_rows()

    input_index_ids = dedupe_in_order(parse_symbols_input(args.symbols))

    equity_symbols = dedupe_in_order(
        row.get("yahoo_symbol", "").strip()
        for row in rows
        if (row.get("quoteType", "") or "").strip().lower() == "equity"
        and row.get("yahoo_symbol", "").strip()
    )
    crawler_symbols = dedupe_in_order(
        row.get("index_id", "").strip() for row in rows if row.get("index_id", "").strip()
    )


    # 1) Key stats (equities only)
    if equity_symbols:
        for chunk in chunked(equity_symbols, chunk_size=args.chunk_size):
            run_script(KEY_STATS_PAGES_SCRIPT, symbols=chunk, dry_run=args.dry_run)
    else:
        print("No EQUITY symbols found in index_symbol_map.csv; skipping key statistics crawl.")

    # 2) Crawler (index_id list)
    if crawler_symbols:
        for chunk in chunked(crawler_symbols, chunk_size=args.chunk_size):
            run_script(CRAWLER_SCRIPT, symbols=chunk, dry_run=args.dry_run)
            run_script(QUOTE_PAGES_SCRIPT, symbols=chunk, dry_run=args.dry_run)
    else:
        print("No index_id symbols found in index_symbol_map.csv; skipping yahoo_crawler.")


    return 0


if __name__ == "__main__":
    raise SystemExit(main())

