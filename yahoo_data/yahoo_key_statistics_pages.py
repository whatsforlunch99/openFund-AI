#!/usr/bin/env python3
import json
from datetime import datetime

from lxml import html as lxml_html

BASE_DIR = "/Users/jiani/Desktop/finance_database/yahoo_data"
OUT_PATH = f"{BASE_DIR}/yahoo_key_statistics.csv"

FIELDS = [
    "symbol",
    "as_of_timestamp",
    "key_statistics_json",
    "source_url",
    "status",
]

REQUEST_KWARGS = {"follow_redirects": False}
DISABLE_HEADERS = False
FETCHER = "static"
FETCH_KWARGS = {}
RETRY_ATTEMPTS = 5
RETRY_DELAY_SECONDS = 1.5


def build_url(symbol):
    return f"https://finance.yahoo.com/quote/{symbol}/key-statistics/"


def normalize_text(s):
    return " ".join((s or "").split())


def parse_key_statistics(html_text):
    try:
        doc = lxml_html.fromstring(html_text)
    except Exception:
        return None

    valuation_measures = {}
    sections = {}

    # Parse all tables and use nearest preceding heading as section title
    tables = doc.xpath("//table") or []
    for table in tables:
        heading = table.xpath("preceding::h2[1] | preceding::h3[1]")
        title = normalize_text(heading[-1].text_content()) if heading else ""
        rows = table.xpath(".//tr")
        if not rows:
            continue

        header_cells = rows[0].xpath(".//th|.//td")
        header_texts = [normalize_text(c.text_content()) for c in header_cells]
        is_valuation = title.lower().startswith("valuation measures") or any(h.lower() == "current" for h in header_texts)

        if is_valuation:
            periods = header_texts[1:]
            for r in rows[1:]:
                cells = r.xpath(".//th|.//td")
                if len(cells) < 2:
                    continue
                metric = normalize_text(cells[0].text_content())
                values = [normalize_text(c.text_content()) for c in cells[1:]]
                if not metric:
                    continue
                valuation_measures[metric] = {periods[i]: values[i] if i < len(values) else "" for i in range(len(periods))}
            continue

        section_data = sections.get(title, {})
        for r in rows:
            cells = r.xpath(".//th|.//td")
            if len(cells) < 2:
                continue
            label = normalize_text(cells[0].text_content())
            value = normalize_text(cells[1].text_content())
            if label:
                section_data[label] = value
        if section_data and title:
            sections[title] = section_data

    # Fallback: parse list-style label/value pairs within sections
    for section in doc.xpath("//section"):
        title_nodes = section.xpath(".//h2|.//h3")
        title = normalize_text(title_nodes[0].text_content()) if title_nodes else ""
        if not title or title in sections:
            continue
        items = section.xpath(".//li[.//span[contains(@class,'label')] and .//span[contains(@class,'value')]]")
        if not items:
            continue
        section_data = {}
        for item in items:
            label = normalize_text(" ".join(item.xpath(".//span[contains(@class,'label')]//text()")))
            value = normalize_text(" ".join(item.xpath(".//span[contains(@class,'value')]//text()")))
            if label:
                section_data[label] = value
        if section_data:
            sections[title] = section_data

    return {
        "valuation_measures": valuation_measures,
        "sections": sections,
    }

def extract_quote_store(html, symbol):
    return parse_key_statistics(html)

def parse_quote_summary_table(html_text):
    return {}


def row_from_parsed(symbol, parsed, url):
    return {
        "symbol": symbol,
        "as_of_timestamp": datetime.utcnow().isoformat(),
        "key_statistics_json": json.dumps(parsed, ensure_ascii=False),
        "source_url": url,
        "status": "ok",
    }


def empty_row(symbol, url):
    return {
        "symbol": symbol,
        "as_of_timestamp": datetime.utcnow().isoformat(),
        "key_statistics_json": "",
        "source_url": url,
        "status": "parse_error",
    }


def has_any_values(row):
    try:
        payload = json.loads(row.get("key_statistics_json") or "{}")
    except Exception:
        return False
    valuation = len(payload.get("valuation_measures", {}) or {})
    sections = len(payload.get("sections", {}) or {})
    return (valuation + sections) > 0

def row_from_store(symbol, store, url):
    if not store:
        return empty_row(symbol, url)
    return row_from_parsed(symbol, store, url)

def apply_table_values(row, table_data):
    return row

def should_retry(row, store, table_data, http_ok=True):
    if not http_ok:
        return True
    if not store:
        return True
    valuation = len(store.get("valuation_measures", {}))
    sections = len(store.get("sections", {}))
    return valuation == 0 and sections == 0
