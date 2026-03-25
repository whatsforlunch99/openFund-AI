#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import json
import os
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

DEFAULT_USER_AGENT = "Mozilla/5.0 (compatible; sec-10k-crawler/1.0)"
DEFAULT_OUTPUT_DIR = "./sec_10k_data"
DEFAULT_FORM_AND_FILE = "10-K (Annual report)"
FORM_LABELS = {
    "10-K": "10-K (Annual report)",
    "20-F": "20-F (Annual report - foreign issuer)",
}
TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"


@dataclass
class FilingChoice:
    year: int
    filing_date: str
    accession: str


class RateLimiter:
    def __init__(self, max_per_sec: float):
        self.min_interval = 1.0 / max_per_sec if max_per_sec > 0 else 0.0
        self.last_time = 0.0

    def wait(self) -> None:
        if self.min_interval <= 0:
            return
        now = time.time()
        elapsed = now - self.last_time
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self.last_time = time.time()


class IndexHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_table = False
        self.in_row = False
        self.current_cells: list[str] = []
        self.current_href: Optional[str] = None
        self.rows: list[tuple[str, str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        attrs_dict = dict(attrs)
        if tag == "table" and attrs_dict.get("summary") == "Document Format Files":
            self.in_table = True
        elif self.in_table and tag == "tr":
            self.in_row = True
            self.current_cells = []
            self.current_href = None
        elif self.in_row and tag == "a":
            href = attrs_dict.get("href")
            if href:
                self.current_href = href

    def handle_endtag(self, tag: str) -> None:
        if tag == "table" and self.in_table:
            self.in_table = False
        elif tag == "tr" and self.in_row:
            if len(self.current_cells) >= 4:
                desc = self.current_cells[1].strip()
                doc_text = self.current_cells[2].strip()
                doc_href = self.current_href or ""
                doc_name = doc_text.split()[-1] if doc_text else ""
                if doc_href:
                    doc_name = doc_href.split("/")[-1]
                doc_type = self.current_cells[3].strip()
                if desc and doc_name:
                    self.rows.append((desc, doc_name, doc_type))
            self.in_row = False
            self.current_cells = []
            self.current_href = None

    def handle_data(self, data: str) -> None:
        if self.in_row:
            text = data.strip()
            if text:
                self.current_cells.append(text)


def headers_for_url(url: str, user_agent: str) -> dict[str, str]:
    netloc = urllib.parse.urlparse(url).netloc
    return {
        "User-Agent": user_agent,
        "Accept-Encoding": "gzip, deflate",
        "Host": netloc,
    }


def request_json(url: str, *, headers: dict[str, str], limiter: RateLimiter, timeout: int = 30) -> dict[str, Any]:
    max_retries = 5
    for attempt in range(max_retries):
        limiter.wait()
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                encoding = resp.headers.get("Content-Encoding", "").lower()
                if "gzip" in encoding or raw[:2] == b"\x1f\x8b":
                    raw = gzip.decompress(raw)
                return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504):
                time.sleep((2**attempt) + 0.1 * attempt)
                continue
            raise
        except urllib.error.URLError:
            time.sleep((2**attempt) + 0.1 * attempt)
            continue
    raise RuntimeError(f"Failed to fetch JSON after retries: {url}")


def download_file(url: str, dest_path: str, *, headers: dict[str, str], limiter: RateLimiter, timeout: int = 60) -> None:
    max_retries = 5
    for attempt in range(max_retries):
        limiter.wait()
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                encoding = resp.headers.get("Content-Encoding", "").lower()
                if "gzip" in encoding or raw[:2] == b"\x1f\x8b":
                    raw = gzip.decompress(raw)
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            with open(dest_path, "wb") as f:
                f.write(raw)
            return
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504):
                time.sleep((2**attempt) + 0.1 * attempt)
                continue
            raise
        except urllib.error.URLError:
            time.sleep((2**attempt) + 0.1 * attempt)
            continue
    raise RuntimeError(f"Failed to download after retries: {url}")


def fetch_index_rows(url: str, *, headers: dict[str, str], limiter: RateLimiter, timeout: int = 30) -> list[tuple[str, str, str]]:
    max_retries = 5
    for attempt in range(max_retries):
        limiter.wait()
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                encoding = resp.headers.get("Content-Encoding", "").lower()
                if "gzip" in encoding or raw[:2] == b"\x1f\x8b":
                    raw = gzip.decompress(raw)
                html = raw.decode("utf-8", errors="replace")
            parser = IndexHtmlParser()
            parser.feed(html)
            return parser.rows
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504):
                time.sleep((2**attempt) + 0.1 * attempt)
                continue
            raise
        except urllib.error.URLError:
            time.sleep((2**attempt) + 0.1 * attempt)
            continue
    raise RuntimeError(f"Failed to fetch index HTML after retries: {url}")


def parse_recent_filings(submissions: dict[str, Any]) -> list[tuple[str, str, str]]:
    recent = submissions.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    filing_dates = recent.get("filingDate", [])
    accessions = recent.get("accessionNumber", [])
    return list(zip(forms, filing_dates, accessions))


def select_latest_by_year(rows: Iterable[tuple[str, str]], start_year: int, end_year: int) -> dict[int, FilingChoice]:
    choices: dict[int, FilingChoice] = {}
    for filing_date, accession in rows:
        year = int(filing_date.split("-")[0])
        if year < start_year or year > end_year:
            continue
        cur = choices.get(year)
        if cur is None or (filing_date, accession) > (cur.filing_date, cur.accession):
            choices[year] = FilingChoice(year=year, filing_date=filing_date, accession=accession)
    return choices


def find_exact_annual_htm(
    rows: list[tuple[str, str, str]],
    *,
    filing_form: str,
    target_form_and_file: str,
) -> Optional[str]:
    """
    Extract the specific annual report HTM file matching the SEC index table "Document Format Files".

    - `filing_form` is the primary SEC form we expect (e.g. "10-K" or "20-F")
    - `target_form_and_file` is the exact "10-K (Annual report)" / "20-F (Annual report - foreign issuer)" string
    """
    form_label = FORM_LABELS.get(filing_form, filing_form)
    for desc, doc_name, _doc_type in rows:
        label = form_label if desc == filing_form else f"{form_label} {desc}"
        # Some SEC index tables include amended variants like "20-F/A" which
        # produce labels such as "20-F (Annual report - foreign issuer) 20-F/A".
        # We accept those as long as the base label matches.
        matches = label == target_form_and_file or label.startswith(target_form_and_file + " ")
        if matches and doc_name.lower().endswith((".htm", ".html")):
            return doc_name
    return None


def download_linked_images(
    *,
    htm_path: str,
    archive_base_url: str,
    user_agent: str,
    limiter: RateLimiter,
) -> tuple[int, int]:
    with open(htm_path, "r", encoding="utf-8", errors="replace") as f:
        htm_text = f.read()
    img_refs = re.findall(r"<img[^>]+src=[\"']([^\"']+)[\"']", htm_text, flags=re.I)
    ok, fail = 0, 0
    for src in [x.strip() for x in img_refs if x.strip()]:
        local_name = os.path.basename(src.split("?", 1)[0])
        if not local_name:
            continue
        img_url = urllib.parse.urljoin(archive_base_url + "/", src)
        img_dest = os.path.join(os.path.dirname(htm_path), local_name)
        try:
            download_file(img_url, img_dest, headers=headers_for_url(img_url, user_agent), limiter=limiter)
            ok += 1
        except Exception:
            fail += 1
    return ok, fail


def convert_htm_to_pdf(htm_path: str, pdf_path: str) -> tuple[bool, str]:
    os.makedirs(os.path.dirname(pdf_path), exist_ok=True)

    wkhtmltopdf = shutil.which("wkhtmltopdf")
    if wkhtmltopdf:
        try:
            subprocess.run([wkhtmltopdf, htm_path, pdf_path], check=True, capture_output=True, text=True)
            return True, ""
        except Exception as e:
            wkhtml_err = f"wkhtmltopdf failed: {e}"
    else:
        wkhtml_err = "wkhtmltopdf not installed"

    try:
        from playwright.sync_api import sync_playwright  # type: ignore

        file_url = "file://" + os.path.abspath(htm_path)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(file_url, wait_until="networkidle")
            page.pdf(path=pdf_path, format="A4", print_background=True)
            browser.close()
        return True, ""
    except Exception as e:
        playwright_err = str(e)

    return False, f"no HTML->PDF converter available ({wkhtml_err}; playwright error: {playwright_err})"


def resolve_cik(symbol: str, *, user_agent: str, limiter: RateLimiter) -> tuple[Optional[str], str]:
    url = TICKER_MAP_URL
    headers = headers_for_url(url, user_agent)
    try:
        data = request_json(url, headers=headers, limiter=limiter)
    except Exception as e:
        return None, f"failed to load SEC ticker map: {e}"
    sym_upper = symbol.upper()
    for _, row in data.items():
        ticker = str(row.get("ticker", "")).upper()
        if ticker == sym_upper:
            cik_num = str(row.get("cik_str", "")).strip()
            if not cik_num.isdigit():
                return None, "invalid cik in SEC ticker map"
            return cik_num.zfill(10), ""
    return None, "ticker not found in SEC map"


def run_for_symbol(
    *,
    symbol: str,
    cik: Optional[str],
    start_year: int,
    end_year: int,
    output_dir: str,
    user_agent: str,
    max_req_per_sec: float,
    form_and_file: str,
    dry_run: bool,
) -> list[dict[str, Any]]:
    limiter = RateLimiter(max_req_per_sec)
    cik_padded = cik or ""
    if not cik_padded:
        cik_padded, reason = resolve_cik(symbol, user_agent=user_agent, limiter=limiter)
        if not cik_padded:
            return [
                {
                    "symbol": symbol,
                    "year": year,
                    "filing_date": "",
                    "accession": "",
                    "htm_found": False,
                    "htm_path": "",
                    "pdf_created": False,
                    "pdf_path": "",
                    "skip_reason": reason,
                }
                for year in range(start_year, end_year + 1)
            ]

    cik_num = str(int(cik_padded))
    submissions_url = f"https://data.sec.gov/submissions/CIK{cik_padded}.json"
    submissions = request_json(
        submissions_url,
        headers=headers_for_url(submissions_url, user_agent),
        limiter=limiter,
    )
    recent = parse_recent_filings(submissions)
    primary_form = "10-K"
    fallback_form = "20-F"
    primary_target = form_and_file  # e.g. "10-K (Annual report)"
    fallback_target = FORM_LABELS[fallback_form]

    primary_choices: dict[int, FilingChoice] = select_latest_by_year(
        [(date, acc) for form, date, acc in recent if form == primary_form],
        start_year,
        end_year,
    )

    results: list[dict[str, Any]] = []
    for year in range(start_year, end_year + 1):
        choice = primary_choices.get(year)
        if choice is None:
            results.append(
                {
                    "symbol": symbol,
                    "year": year,
                    "filing_date": "",
                    "accession": "",
                    "htm_found": False,
                    "htm_path": "",
                    "pdf_created": False,
                    "pdf_path": "",
                    "sec_form_used": primary_form,
                    "used_fallback": False,
                    "skip_reason": "no 10-K filing in year",
                }
            )
            continue

        acc_no_dash = choice.accession.replace("-", "")
        index_url = f"https://www.sec.gov/Archives/edgar/data/{cik_num}/{acc_no_dash}/{choice.accession}-index.html"
        rows = fetch_index_rows(index_url, headers=headers_for_url(index_url, user_agent), limiter=limiter)
        htm_name = find_exact_annual_htm(
            rows,
            filing_form=primary_form,
            target_form_and_file=primary_target,
        )
        if not htm_name:
            results.append(
                {
                    "symbol": symbol,
                    "year": year,
                    "filing_date": choice.filing_date,
                    "accession": choice.accession,
                    "htm_found": False,
                    "htm_path": "",
                    "pdf_created": False,
                    "pdf_path": "",
                    "sec_form_used": primary_form,
                    "used_fallback": False,
                    "skip_reason": "no exact HTM match",
                }
            )
            continue

        symbol_dir = os.path.join(output_dir, symbol, str(year))
        htm_url = f"https://www.sec.gov/Archives/edgar/data/{cik_num}/{acc_no_dash}/{htm_name}"
        archive_base_url = f"https://www.sec.gov/Archives/edgar/data/{cik_num}/{acc_no_dash}"
        htm_path = os.path.join(symbol_dir, htm_name)
        pdf_path = os.path.join(symbol_dir, f"{Path(htm_name).stem}.pdf")

        pdf_created = False
        skip_reason = ""
        if not dry_run:
            download_file(htm_url, htm_path, headers=headers_for_url(htm_url, user_agent), limiter=limiter)
            download_linked_images(
                htm_path=htm_path,
                archive_base_url=archive_base_url,
                user_agent=user_agent,
                limiter=limiter,
            )
            pdf_created, skip_reason = convert_htm_to_pdf(htm_path, pdf_path)

        results.append(
            {
                "symbol": symbol,
                "year": year,
                "filing_date": choice.filing_date,
                "accession": choice.accession,
                "htm_found": True,
                "htm_path": htm_path,
                "pdf_created": bool(pdf_created) if not dry_run else False,
                "pdf_path": pdf_path if (pdf_created and not dry_run) else "",
                "sec_form_used": primary_form,
                "used_fallback": False,
                "skip_reason": skip_reason,
            }
        )
    any_htm_found_primary = any(bool(r.get("htm_found")) for r in results)
    if any_htm_found_primary:
        return results

    # Symbol-level fallback:
    # If we couldn't find ANY primary (10-K annual) HTM across requested years, retry using 20-F annual.
    fallback_choices: dict[int, FilingChoice] = select_latest_by_year(
        [(date, acc) for form, date, acc in recent if form == fallback_form],
        start_year,
        end_year,
    )
    fallback_results: list[dict[str, Any]] = []
    for year in range(start_year, end_year + 1):
        choice = fallback_choices.get(year)
        if choice is None:
            fallback_results.append(
                {
                    "symbol": symbol,
                    "year": year,
                    "filing_date": "",
                    "accession": "",
                    "htm_found": False,
                    "htm_path": "",
                    "pdf_created": False,
                    "pdf_path": "",
                    "sec_form_used": fallback_form,
                    "used_fallback": True,
                    "skip_reason": "no 20-F filing in year",
                }
            )
            continue

        acc_no_dash = choice.accession.replace("-", "")
        index_url = f"https://www.sec.gov/Archives/edgar/data/{cik_num}/{acc_no_dash}/{choice.accession}-index.html"
        rows = fetch_index_rows(index_url, headers=headers_for_url(index_url, user_agent), limiter=limiter)
        htm_name = find_exact_annual_htm(
            rows,
            filing_form=fallback_form,
            target_form_and_file=fallback_target,
        )
        if not htm_name:
            fallback_results.append(
                {
                    "symbol": symbol,
                    "year": year,
                    "filing_date": choice.filing_date,
                    "accession": choice.accession,
                    "htm_found": False,
                    "htm_path": "",
                    "pdf_created": False,
                    "pdf_path": "",
                    "sec_form_used": fallback_form,
                    "used_fallback": True,
                    "skip_reason": "no exact HTM match",
                }
            )
            continue

        symbol_dir = os.path.join(output_dir, symbol, str(year))
        htm_url = f"https://www.sec.gov/Archives/edgar/data/{cik_num}/{acc_no_dash}/{htm_name}"
        archive_base_url = f"https://www.sec.gov/Archives/edgar/data/{cik_num}/{acc_no_dash}"
        htm_path = os.path.join(symbol_dir, htm_name)
        pdf_path = os.path.join(symbol_dir, f"{Path(htm_name).stem}.pdf")

        pdf_created = False
        skip_reason = ""
        if not dry_run:
            download_file(htm_url, htm_path, headers=headers_for_url(htm_url, user_agent), limiter=limiter)
            download_linked_images(
                htm_path=htm_path,
                archive_base_url=archive_base_url,
                user_agent=user_agent,
                limiter=limiter,
            )
            pdf_created, skip_reason = convert_htm_to_pdf(htm_path, pdf_path)

        fallback_results.append(
            {
                "symbol": symbol,
                "year": year,
                "filing_date": choice.filing_date,
                "accession": choice.accession,
                "htm_found": True,
                "htm_path": htm_path,
                "pdf_created": bool(pdf_created) if not dry_run else False,
                "pdf_path": pdf_path if (pdf_created and not dry_run) else "",
                "sec_form_used": fallback_form,
                "used_fallback": True,
                "skip_reason": skip_reason,
            }
        )

    return fallback_results


def main() -> int:
    parser = argparse.ArgumentParser(description="Download 10-K (Annual report) HTM and PDF for one symbol")
    parser.add_argument("--symbol", default="AAPL", help="Ticker symbol (e.g. AAPL)")
    parser.add_argument("--cik", default="", help="Optional SEC CIK (10-digit zero-padded preferred)")
    parser.add_argument("--start-year", type=int, default=2023)
    parser.add_argument("--end-year", type=int, default=2026)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT)
    parser.add_argument("--max-req-per-sec", type=float, default=5.0)
    parser.add_argument("--form-and-file", default=DEFAULT_FORM_AND_FILE)
    parser.add_argument("--dry-run", action="store_true", help="List matches without downloading")
    args = parser.parse_args()

    results = run_for_symbol(
        symbol=args.symbol.strip().upper(),
        cik=(args.cik.strip() or None),
        start_year=args.start_year,
        end_year=args.end_year,
        output_dir=args.output_dir,
        user_agent=args.user_agent,
        max_req_per_sec=args.max_req_per_sec,
        form_and_file=args.form_and_file,
        dry_run=args.dry_run,
    )

    print(
        "symbol\tyear\tfiling_date\taccession\tsec_form_used\tused_fallback\thtm_found\thtm_path\tpdf_created\tpdf_path\tskip_reason"
    )
    for r in results:
        print(
            f"{r['symbol']}\t{r['year']}\t{r['filing_date']}\t{r['accession']}\t"
            f"{r.get('sec_form_used','')}\t{str(r.get('used_fallback', False)).lower()}\t"
            f"{str(r['htm_found']).lower()}\t{r['htm_path']}\t{str(r['pdf_created']).lower()}\t{r['pdf_path']}\t{r['skip_reason']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
