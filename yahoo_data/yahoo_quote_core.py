#!/usr/bin/env python3
import argparse
import csv
import json
import os
import random
import time
from datetime import datetime

from scrapling import Fetcher, PlayWrightFetcher


def parse_symbols(arg):
    if not arg:
        return ["AAPL"]
    s = arg.strip()
    if s.startswith("["):
        try:
            arr = json.loads(s)
            return [str(x).strip() for x in arr if str(x).strip()]
        except Exception:
            pass
    return [x.strip() for x in s.split(",") if x.strip()]


def get_cookie_header():
    parts = []
    for name in ("YAHOO_A1", "YAHOO_A1S", "YAHOO_A3"):
        val = os.environ.get(name)
        if val:
            parts.append(f"{name.replace('YAHOO_','') }={val}")
    return "; ".join(parts) if parts else ""


def ensure_schema(path, fields):
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        existing_fields = reader.fieldnames or []
        if all(f in existing_fields for f in fields) and len(existing_fields) == len(fields):
            return
        rows = list(reader)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            out = {k: r.get(k, "") for k in fields}
            w.writerow(out)


def append_rows(path, rows, fields):
    ensure_schema(path, fields)
    existing = set()
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            r = csv.DictReader(f)
            for row in r:
                existing.add((row.get("symbol", ""), row.get("as_of_timestamp", "")))
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if not os.path.exists(path):
            w.writeheader()
        for row in rows:
            key = (row.get("symbol", ""), row.get("as_of_timestamp", ""))
            if key in existing:
                continue
            w.writerow({k: row.get(k, "") for k in fields})


def crawl_symbols(symbols, headers, page, out_path, rate_seconds=2.0):
    fetch_mode = getattr(page, "FETCHER", "static")
    if fetch_mode == "playwright":
        fetcher = PlayWrightFetcher()
    else:
        fetcher = Fetcher()
    request_kwargs = getattr(page, "REQUEST_KWARGS", {})
    headers_override = getattr(page, "HEADERS_OVERRIDE", None)
    disable_headers = getattr(page, "DISABLE_HEADERS", False)
    fetch_kwargs = getattr(page, "FETCH_KWARGS", {})
    rows = []
    # Ensure schema once up front for per-row appends
    ensure_schema(out_path, page.FIELDS)
    retry_attempts = max(1, int(getattr(page, "RETRY_ATTEMPTS", 1)))
    retry_delay = float(getattr(page, "RETRY_DELAY_SECONDS", 1.5))
    for i, symbol in enumerate(symbols):
        url = page.build_url(symbol)
        for attempt in range(1, retry_attempts + 1):
            try:
                req_headers = None
                if not disable_headers:
                    req_headers = headers_override if headers_override is not None else headers
                if fetch_mode == "playwright":
                    try:
                        if req_headers is not None:
                            res = fetcher.fetch(url, extra_headers=req_headers, **fetch_kwargs)
                        else:
                            res = fetcher.fetch(url, **fetch_kwargs)
                    except Exception:
                        # Fallback to static fetcher if Playwright fails
                        fallback = Fetcher()
                        if req_headers is not None:
                            res = fallback.get(url, timeout=20, stealthy_headers=True, headers=req_headers, **request_kwargs)
                        else:
                            res = fallback.get(url, timeout=20, stealthy_headers=True, **request_kwargs)
                else:
                    if req_headers is not None:
                        res = fetcher.get(url, timeout=20, stealthy_headers=True, headers=req_headers, **request_kwargs)
                    else:
                        res = fetcher.get(url, timeout=20, stealthy_headers=True, **request_kwargs)
                status = getattr(res, "status", None)
                if status != 200:
                    # Stop immediately on any non-200 response
                    print(f"{status}")
                    return rows
                html = str(res.body or "")
                http_ok = True
                store = page.extract_quote_store(html, symbol)
                table_data = page.parse_quote_summary_table(html)
                if store:
                    row = page.row_from_store(symbol, store, url)
                else:
                    row = page.empty_row(symbol, url)
                row = page.apply_table_values(row, table_data)
                data_ok = bool(page.has_any_values(row))
                row["status"] = "ok" if data_ok else "parse_error"

                should_retry = False
                if hasattr(page, "should_retry"):
                    try:
                        should_retry = bool(page.should_retry(row, store, table_data, http_ok))
                    except Exception:
                        should_retry = False
                if not http_ok:
                    should_retry = True

                if should_retry and attempt < retry_attempts:
                    time.sleep(retry_delay)
                    continue

                if http_ok and data_ok:
                    rows.append(row)
                    append_rows(out_path, [row], page.FIELDS)
                break
            except Exception:
                if attempt < retry_attempts:
                    time.sleep(retry_delay)
                    continue
                break

        if i < len(symbols) - 1:
            time.sleep(rate_seconds + random.random() * 0.5)

    return rows


def build_headers():
    cookie_header = get_cookie_header()
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }
    if cookie_header:
        headers["Cookie"] = cookie_header
    return headers


def cli_main(page, out_path):
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", help="Comma list or JSON array; default AAPL")
    args = parser.parse_args()
    symbols = parse_symbols(args.symbols)
    headers = build_headers()
    rows = crawl_symbols(symbols, headers, page, out_path)
    print(f"Wrote {len(rows)} rows to {out_path}")
