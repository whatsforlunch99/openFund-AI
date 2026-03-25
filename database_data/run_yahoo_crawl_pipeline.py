#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterable


HERE = Path(__file__).resolve().parent
CSV_DIR = HERE / "csv_files"
INDEX_SYMBOL_MAP_PATH = CSV_DIR / "index_symbol_map.csv"

CRAWLER_SCRIPT = HERE / "yahoo_crawler.py"
KEY_STATS_PAGES_SCRIPT = HERE / "yahoo_key_statistics_pages.py"
QUOTE_PAGES_SCRIPT = HERE / "yahoo_quote_pages.py"
COMPLETENESS_SCRIPT = HERE / "check_symbol_completeness_and_fix.py"
DEDUPE_SCRIPT = HERE / "dedupe_yahoo_csvs.py"


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


def _fmt_elapsed(seconds: float) -> str:
    return f"{seconds:.1f}s"


def log(msg: str) -> None:
    print(msg, flush=True)


def _print_chunk_header(
    *,
    stage_label: str,
    chunk_idx: int,
    chunk_total: int,
    symbols: list[str],
    script_path: Path,
) -> None:
    preview = ",".join(symbols[:5])
    if len(symbols) > 5:
        preview += f",...(+{len(symbols)-5})"
    log(
        f"[CHUNK] {stage_label} chunk {chunk_idx}/{chunk_total} "
        f"symbols={len(symbols)} [{preview}] -> {script_path.name}"
    )


def run_script(
    script_path: Path,
    *,
    symbols: list[str],
    dry_run: bool,
    stage_label: str,
    chunk_idx: int,
    chunk_total: int,
) -> None:
    # Sub-scripts parse `--symbols` as comma-separated or JSON list.
    cmd_symbols = ",".join(symbols)
    cmd = [sys.executable, str(script_path), "--symbols", cmd_symbols]
    _print_chunk_header(
        stage_label=stage_label,
        chunk_idx=chunk_idx,
        chunk_total=chunk_total,
        symbols=symbols,
        script_path=script_path,
    )

    if dry_run:
        log(f"[DRY-RUN] {' '.join(cmd)}")
        return

    log(f"[RUN] {' '.join(cmd)}")
    started = time.perf_counter()
    try:
        subprocess.run(cmd, check=True, cwd=str(HERE))
    except subprocess.CalledProcessError as exc:
        log(f"[ERROR] Stage failed: {stage_label} (chunk {chunk_idx}/{chunk_total})")
        log(f"[ERROR] Command: {' '.join(cmd)}")
        log(f"[ERROR] Exit code: {exc.returncode}")
        log(
            "[HINT] If you see 'needs new crumb', paste the full cookie value in form "
            "'d=...&S=...' when prompted."
        )
        raise
    elapsed = time.perf_counter() - started
    log(f"[DONE] {stage_label} chunk {chunk_idx}/{chunk_total} finished in {_fmt_elapsed(elapsed)}")


def parse_missing_summary(text: str) -> dict[str, int]:
    keys = {
        "timeseries": "yahoo_timeseries.csv",
        "indicators": "yahoo_indicators.csv",
        "quote_metrics": "yahoo_quote_metrics.csv",
        "key_statistics": "yahoo_key_statistics.csv (equity only)",
    }
    out: dict[str, int] = {k: -1 for k in keys}
    for line in text.splitlines():
        stripped = line.strip()
        for short, label in keys.items():
            prefix = f"- {label}: missing "
            if stripped.startswith(prefix):
                try:
                    out[short] = int(stripped.split(prefix, 1)[1])
                except ValueError:
                    pass
    return out


def run_completeness_check(*, chunk_size: int, dry_run: bool) -> dict[str, int] | None:
    cmd = [
        sys.executable,
        str(COMPLETENESS_SCRIPT),
        "--run",
        "--chunk-size",
        str(chunk_size),
    ]
    log("[STAGE] Running completeness check and auto-fix...")
    if dry_run:
        log(f"[DRY-RUN] {' '.join(cmd)}")
        return None
    log(f"[RUN] {' '.join(cmd)}")
    started = time.perf_counter()
    proc = subprocess.run(
        cmd,
        check=False,
        cwd=str(HERE),
        text=True,
        capture_output=True,
    )
    if proc.stdout:
        print(proc.stdout, end="" if proc.stdout.endswith("\n") else "\n", flush=True)
    if proc.stderr:
        print(proc.stderr, end="" if proc.stderr.endswith("\n") else "\n", flush=True)
    if proc.returncode != 0:
        log(f"[ERROR] Completeness check failed with exit code {proc.returncode}")
        log(f"[ERROR] Command: {' '.join(cmd)}")
        raise subprocess.CalledProcessError(proc.returncode, cmd)
    elapsed = time.perf_counter() - started
    log(f"[DONE] Completeness check finished in {_fmt_elapsed(elapsed)}")
    summary = parse_missing_summary(proc.stdout or "")
    return summary


def run_dedupe(*, dry_run: bool) -> None:
    cmd = [sys.executable, str(DEDUPE_SCRIPT)]
    log("[STAGE] Running CSV deduplication...")
    if dry_run:
        log(f"[DRY-RUN] {' '.join(cmd)}")
        return
    log(f"[RUN] {' '.join(cmd)}")
    started = time.perf_counter()
    subprocess.run(cmd, check=True, cwd=str(HERE))
    elapsed = time.perf_counter() - started
    log(f"[DONE] CSV deduplication finished in {_fmt_elapsed(elapsed)}")


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

def build_symbol_maps(rows: list[dict[str, str]]) -> tuple[dict[str, str], dict[str, str], set[str]]:
    index_to_yahoo: dict[str, str] = {}
    yahoo_to_index: dict[str, str] = {}
    equity_yahoo_symbols: set[str] = set()

    for row in rows:
        index_id = (row.get("index_id") or "").strip()
        yahoo_symbol = (row.get("yahoo_symbol") or "").strip()
        quote_type = (row.get("quoteType") or "").strip().lower()

        if not index_id or not yahoo_symbol:
            continue

        index_to_yahoo[index_id] = yahoo_symbol
        yahoo_to_index.setdefault(yahoo_symbol, index_id)
        if quote_type == "equity":
            equity_yahoo_symbols.add(yahoo_symbol)

    return index_to_yahoo, yahoo_to_index, equity_yahoo_symbols

def resolve_inputs(
    tokens: list[str],
    *,
    index_to_yahoo: dict[str, str],
    yahoo_to_index: dict[str, str],
    equity_yahoo_symbols: set[str],
) -> tuple[list[str], list[str], list[str]]:
    resolved_index_ids: list[str] = []
    resolved_equity_yahoo_symbols: list[str] = []
    unknown_tokens: list[str] = []

    for token in tokens:
        tok = token.strip()
        if not tok:
            continue

        if tok in index_to_yahoo:
            idx = tok
            ysym = index_to_yahoo[idx]
        elif tok in yahoo_to_index:
            ysym = tok
            idx = yahoo_to_index[tok]
        else:
            unknown_tokens.append(tok)
            continue

        resolved_index_ids.append(idx)
        if ysym in equity_yahoo_symbols:
            resolved_equity_yahoo_symbols.append(ysym)

    return (
        dedupe_in_order(resolved_index_ids),
        dedupe_in_order(resolved_equity_yahoo_symbols),
        dedupe_in_order(unknown_tokens),
    )

def prompt_required_symbols() -> str:
    user_input = input(
        "Enter symbol(s) to crawl (comma list or JSON array; accepts mixed index_id + Yahoo symbol): "
    ).strip()
    if not user_input:
        raise ValueError("No symbols provided. Aborting.")
    return user_input

def prompt_cookie() -> str:
    cookie_val = input(
        "Paste YAHOO cookie value to use for YAHOO_A1, YAHOO_A1S, YAHOO_A3: "
    ).strip()
    if not cookie_val:
        raise ValueError("Cookie value cannot be empty.")
    return cookie_val


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Yahoo crawling pipeline")
    parser.add_argument("--dry-run", action="store_true", help="Print commands without executing")
    parser.add_argument(
        "--symbols",
        type=str,
        default="",
        help="Optional list of symbols to crawl (comma-separated or JSON list). Accepts mixed index_id + Yahoo symbols.",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=80,
        help="Number of symbols per subprocess invocation",
    )
    args = parser.parse_args()

    symbol_input = args.symbols.strip() or prompt_required_symbols()
    input_tokens = dedupe_in_order(parse_symbols_input(symbol_input))
    if not input_tokens:
        raise ValueError("No parseable symbols provided. Aborting.")

    cookie_val = prompt_cookie()

    os.environ["YAHOO_A1"] = cookie_val
    os.environ["YAHOO_A1S"] = cookie_val
    os.environ["YAHOO_A3"] = cookie_val

    rows = read_index_symbol_map_rows()
    index_to_yahoo, yahoo_to_index, equity_yahoo_set = build_symbol_maps(rows)

    crawler_symbols, equity_symbols, unknown = resolve_inputs(
        input_tokens,
        index_to_yahoo=index_to_yahoo,
        yahoo_to_index=yahoo_to_index,
        equity_yahoo_symbols=equity_yahoo_set,
    )
    if unknown:
        raise ValueError(
            f"Unknown/unmapped symbol(s): {unknown}. Add them to index_symbol_map.csv or crawl mapping first."
        )
    if not crawler_symbols:
        raise ValueError("No valid mapped symbols resolved from input. Aborting.")

    log("[PIPELINE] Starting interactive Yahoo crawl pipeline")
    log(f"[PIPELINE] Resolved {len(crawler_symbols)} index_id symbol(s) for crawler/quote.")
    log(f"[PIPELINE] Resolved {len(equity_symbols)} equity Yahoo symbol(s) for key statistics.")
    log(f"[PIPELINE] Chunk size: {args.chunk_size}")

    # 1) Key stats (equities only)
    log("\n[STAGE 1/5] Crawling key statistics pages...")
    if equity_symbols:
        key_chunks = list(chunked(equity_symbols, chunk_size=args.chunk_size))
        for i, chunk in enumerate(key_chunks, start=1):
            run_script(
                KEY_STATS_PAGES_SCRIPT,
                symbols=chunk,
                dry_run=args.dry_run,
                stage_label="crawling key statistics",
                chunk_idx=i,
                chunk_total=len(key_chunks),
            )
    else:
        log("[WARN] No equity symbols resolved; skipping key statistics stage.")

    # 2) Crawler (index_id list)
    log("\n[STAGE 2/5] Crawling chart + indicators...")
    if crawler_symbols:
        crawl_chunks = list(chunked(crawler_symbols, chunk_size=args.chunk_size))
        for i, chunk in enumerate(crawl_chunks, start=1):
            run_script(
                CRAWLER_SCRIPT,
                symbols=chunk,
                dry_run=args.dry_run,
                stage_label="crawling chart and indicators",
                chunk_idx=i,
                chunk_total=len(crawl_chunks),
            )
    else:
        log("[WARN] No index_id symbols found; skipping chart/indicator crawler stage.")

    # 3) Quote pages
    log("\n[STAGE 3/5] Crawling quote metrics pages...")
    if crawler_symbols:
        quote_chunks = list(chunked(crawler_symbols, chunk_size=args.chunk_size))
        for i, chunk in enumerate(quote_chunks, start=1):
            run_script(
                QUOTE_PAGES_SCRIPT,
                symbols=chunk,
                dry_run=args.dry_run,
                stage_label="crawling quote metrics",
                chunk_idx=i,
                chunk_total=len(quote_chunks),
            )
    else:
        log("[WARN] No index_id symbols found; skipping quote pages stage.")

    # 4) Completeness check + auto-fix
    log("\n[STAGE 4/5] Running completeness check...")
    summary = run_completeness_check(chunk_size=max(1, min(args.chunk_size, 25)), dry_run=args.dry_run)
    if summary is not None:
        timeseries_missing = summary.get("timeseries", -1)
        indicators_missing = summary.get("indicators", -1)
        quote_missing = summary.get("quote_metrics", -1)
        key_stats_missing = summary.get("key_statistics", -1)
        log(
            "[SUMMARY] Missing counts -> "
            f"timeseries:{timeseries_missing}, "
            f"indicators:{indicators_missing}, "
            f"quote_metrics:{quote_missing}, "
            f"key_statistics_equity:{key_stats_missing}"
        )
        unresolved = [x for x in [timeseries_missing, indicators_missing, quote_missing, key_stats_missing] if x > 0]
        if unresolved:
            log("[WARN] Some missing data remains after auto-fix. Re-run pipeline or inspect failing symbols.")
        else:
            log("[DONE] Completeness check reports no remaining gaps for tracked datasets.")

    # 5) Dedupe
    log("\n[STAGE 5/5] Deduplicating output CSVs...")
    run_dedupe(dry_run=args.dry_run)

    log("\n[PIPELINE] Completed: crawl + completeness repair + dedupe finished.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

