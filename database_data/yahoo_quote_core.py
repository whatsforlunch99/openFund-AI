#!/usr/bin/env python3
import argparse
import csv
import json
import os
import random
import time
from datetime import datetime

from scrapling import Fetcher, PlayWrightFetcher

FAILED_LOG_PATH = "/Users/jiani/Desktop/finance_database/yahoo_data/csv_files/yahoo_failed_requests.csv"


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


def log_failed_symbol(symbol, url, status, crawler_name):
    fields = ["timestamp", "crawler", "symbol", "url", "status"]
    ensure_schema(FAILED_LOG_PATH, fields)
    row = {
        "timestamp": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "crawler": crawler_name,
        "symbol": symbol,
        "url": url,
        "status": str(status) if status is not None else "",
    }
    exists = os.path.exists(FAILED_LOG_PATH)
    with open(FAILED_LOG_PATH, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if not exists:
            w.writeheader()
        w.writerow(row)


def crawl_symbols(symbols, headers, page, out_path, rate_seconds=2.0):
    """
    Backward-compatible wrapper that crawls and writes directly to CSV.

    For refactor/pipeline automation, prefer `crawl_symbols_collect(...)` which
    performs no file I/O and returns both successful rows and failures.
    """
    # Keep the same behavior as before: ensure output schema even if no
    # successful rows are produced.
    fetch_mode = getattr(page, "FETCHER", "playwright")
    _ = fetch_mode  # kept for backward compatibility; collect-only uses the same page attrs.
    ensure_schema(out_path, page.FIELDS)

    rows, failures = crawl_symbols_collect(
        symbols=symbols,
        headers=headers,
        page=page,
        rate_seconds=rate_seconds,
    )

    if rows:
        append_rows(out_path, rows, page.FIELDS)

    for f in failures:
        log_failed_symbol(
            symbol=f.get("symbol", ""),
            url=f.get("url", ""),
            status=f.get("status_code"),
            crawler_name=f.get("crawler_name", "yahoo_crawler"),
        )

    return rows


def crawl_symbols_collect(
    symbols,
    headers,
    page,
    rate_seconds=2.0,
):
    """
    Collect-only quote crawler.

    Returns `(rows, failures)` without performing any CSV writes.
    - `rows`: list of parsed row dicts matching `page.FIELDS`
    - `failures`: list of dicts including `{symbol, url, status_code, crawler_name}`
    """
    fetcher = Fetcher()
    playwright_fetcher = PlayWrightFetcher()
    request_kwargs = getattr(page, "REQUEST_KWARGS", {})
    headers_override = getattr(page, "HEADERS_OVERRIDE", None)
    disable_headers = getattr(page, "DISABLE_HEADERS", False)
    fetch_kwargs = getattr(page, "FETCH_KWARGS", {})

    rows = []
    failures = []

    retry_attempts = 3
    retry_delay = float(getattr(page, "RETRY_DELAY_SECONDS", 1.5))
    crawler_name = getattr(page, "CRAWLER_NAME", getattr(page, "__name__", "yahoo_crawler"))

    for i, symbol in enumerate(symbols):
        url = page.build_url(symbol)
        print(f"[{i+1}/{len(symbols)}] {symbol} -> {url}")
        last_status = None
        success = False

        for attempt in range(1, retry_attempts + 1):
            try:
                req_headers = None
                if not disable_headers:
                    req_headers = headers_override if headers_override is not None else headers

                # Respect page-level FETCHER setting.
                # - Some pages (e.g. key statistics) set FETCHER="static" so we don't
                #   depend on a Playwright browser being installed.
                fetch_mode = getattr(page, "FETCHER", "playwright")

                if fetch_mode == "static":
                    # Static fetch (Scrapling Fetcher)
                    if req_headers is not None:
                        res = fetcher.get(
                            url,
                            timeout=20,
                            stealthy_headers=True,
                            headers=req_headers,
                            **request_kwargs,
                        )
                    else:
                        res = fetcher.get(url, timeout=20, stealthy_headers=True, **request_kwargs)
                else:
                    # Playwright fetch first (default)
                    if req_headers is not None:
                        res = playwright_fetcher.fetch(url, extra_headers=req_headers, **fetch_kwargs)
                    else:
                        res = playwright_fetcher.fetch(url, **fetch_kwargs)

                status = getattr(res, "status", None)
                last_status = status
                html = str(res.body or "")

                def parse_html(html_text):
                    store = page.extract_quote_store(html_text, symbol)
                    table_data = page.parse_quote_summary_table(html_text)
                    if store:
                        row = page.row_from_store(symbol, store, url)
                    else:
                        row = page.empty_row(symbol, url)
                    row = page.apply_table_values(row, table_data)
                    data_ok = bool(page.has_any_values(row))
                    row["status"] = "ok" if data_ok else "parse_error"
                    return row, data_ok, store, table_data

                row, data_ok, store, table_data = parse_html(html)
                http_ok = (status == 200)

                # Static fallback if needed
                if (not http_ok) or (not data_ok):
                    try:
                        if req_headers is not None:
                            res_fb = fetcher.get(
                                url,
                                timeout=20,
                                stealthy_headers=True,
                                headers=req_headers,
                                **request_kwargs,
                            )
                        else:
                            res_fb = fetcher.get(url, timeout=20, stealthy_headers=True, **request_kwargs)

                        status_fb = getattr(res_fb, "status", None)
                        last_status = status_fb if status_fb is not None else last_status
                        html_fb = str(res_fb.body or "")
                        row_fb, data_ok_fb, store_fb, table_data_fb = parse_html(html_fb)

                        if status_fb == 200 and data_ok_fb:
                            rows.append(row_fb)
                            success = True
                            break

                        # Use static parse results for retry decision
                        row, data_ok, store, table_data = row_fb, data_ok_fb, store_fb, table_data_fb
                        http_ok = (status_fb == 200)
                    except Exception:
                        pass

                if http_ok and data_ok:
                    rows.append(row)
                    success = True
                    break

                should_retry = False
                if hasattr(page, "should_retry"):
                    try:
                        should_retry = bool(page.should_retry(row, store, table_data, http_ok))
                    except Exception:
                        should_retry = False
                if (not http_ok) or (not data_ok):
                    should_retry = True

                if should_retry and attempt < retry_attempts:
                    time.sleep(retry_delay)
                    continue

                break
            except Exception:
                if attempt < retry_attempts:
                    time.sleep(retry_delay)
                    continue
                break

        if not success:
            failures.append(
                {
                    "symbol": symbol,
                    "url": url,
                    "status_code": last_status,
                    "crawler_name": crawler_name,
                }
            )

        if i < len(symbols) - 1:
            time.sleep(rate_seconds + random.random() * 0.5)

    return rows, failures


def build_headers():
    cookie_header = get_cookie_header()
    headers = {
        # Yahoo is sensitive to some UA strings. A simpler UA consistently returns the
        # expected key-statistics HTML in this environment.
        "User-Agent": "Mozilla/5.0",
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
