#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Any

from sec_10k_downloader import (
    DEFAULT_FORM_AND_FILE,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_USER_AGENT,
    run_for_symbol,
)

INDEX_SYMBOL_MAP_PATH = Path("yahoo_data/csv_files/index_symbol_map.csv")


def read_equity_symbols(path: Path) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(f"Missing symbol map: {path}")
    symbols: list[str] = []
    with open(path, "r", encoding="utf-8", errors="replace", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            quote_type = (row.get("quoteType") or "").strip().lower()
            symbol = (row.get("yahoo_symbol") or row.get("index_id") or "").strip().upper()
            if quote_type == "equity" and symbol:
                symbols.append(symbol)
    seen = set()
    out = []
    for s in symbols:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def write_report(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "symbol",
        "year",
        "filing_date",
        "accession",
        "htm_found",
        "htm_path",
        "pdf_created",
        "pdf_path",
        "sec_form_used",
        "used_fallback",
        "skip_reason",
    ]
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def status_for_symbol(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "skipped"
    htm_found = any(bool(r.get("htm_found")) for r in rows)
    pdf_created = any(bool(r.get("pdf_created")) for r in rows)
    if htm_found and pdf_created:
        return "ok"
    if htm_found and not pdf_created:
        return "partial"
    return "skipped"


def main() -> int:
    parser = argparse.ArgumentParser(description="Batch SEC 10-K HTM+PDF pipeline for all equity symbols")
    parser.add_argument("--start-year", type=int, default=2023)
    parser.add_argument("--end-year", type=int, default=2026)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT)
    parser.add_argument("--max-req-per-sec", type=float, default=5.0)
    parser.add_argument("--form-and-file", default=DEFAULT_FORM_AND_FILE)
    parser.add_argument("--symbols", default="", help="Optional comma list to limit symbols")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    symbols = read_equity_symbols(INDEX_SYMBOL_MAP_PATH)
    if args.symbols.strip():
        allowed = {s.strip().upper() for s in args.symbols.split(",") if s.strip()}
        symbols = [s for s in symbols if s in allowed]

    all_rows: list[dict[str, Any]] = []
    symbol_ok = symbol_partial = symbol_skipped = 0

    total = len(symbols)
    if total == 0:
        print("No equity symbols found.")
        return 0

    for i, symbol in enumerate(symbols, start=1):
        print(f"[{i}/{total}] {symbol} ...")
        try:
            rows = run_for_symbol(
                symbol=symbol,
                cik=None,
                start_year=args.start_year,
                end_year=args.end_year,
                output_dir=args.output_dir,
                user_agent=args.user_agent,
                max_req_per_sec=args.max_req_per_sec,
                form_and_file=args.form_and_file,
                dry_run=args.dry_run,
            )
        except Exception as e:
            rows = [
                {
                    "symbol": symbol,
                    "year": y,
                    "filing_date": "",
                    "accession": "",
                    "htm_found": False,
                    "htm_path": "",
                    "pdf_created": False,
                    "pdf_path": "",
                    "sec_form_used": "10-K",
                    "used_fallback": False,
                    "skip_reason": f"pipeline_error: {e}",
                }
                for y in range(args.start_year, args.end_year + 1)
            ]
        all_rows.extend(rows)
        st = status_for_symbol(rows)
        if st == "ok":
            symbol_ok += 1
        elif st == "partial":
            symbol_partial += 1
        else:
            symbol_skipped += 1
        print(f"  -> status: {st}")

    report_path = Path(args.output_dir) / "sec_10k_batch_report.csv"
    write_report(report_path, all_rows)

    htm_total = sum(1 for r in all_rows if r.get("htm_found"))
    pdf_total = sum(1 for r in all_rows if r.get("pdf_created"))
    print("\nBatch summary")
    print(f"- symbols attempted: {total}")
    print(f"- symbols ok: {symbol_ok}")
    print(f"- symbols partial: {symbol_partial}")
    print(f"- symbols skipped: {symbol_skipped}")
    print(f"- year rows with HTM found: {htm_total}")
    print(f"- year rows with PDF created: {pdf_total}")
    print(f"- report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
