#!/usr/bin/env python3
import os
import re
import json
from datetime import datetime

from lxml import html as lxml_html

BASE_DIR = "/Users/jiani/Desktop/finance_database/yahoo_data"
OUT_PATH = os.path.join(BASE_DIR, "csv_files", "yahoo_quote_metrics.csv")

FIELDS = [
    "symbol",
    "as_of_timestamp",
    "price",
    "change",
    "change_percent",
    "prev_close",
    "open",
    "day_range",
    "week_52_range",
    "volume",
    "avg_volume",
    "market_cap",
    "market_cap_intraday",
    "bid",
    "ask",
    "beta_5y_monthly",
    "pe_ttm",
    "eps_ttm",
    "earnings_date_est",
    "forward_dividend_yield",
    "ex_dividend_date",
    "target_est_1y",
    "currency",
    "source_url",
    "status",
]


def build_url(symbol):
    return f"https://finance.yahoo.com/quote/{symbol}/"


def extract_quote_store(html, symbol):
    scripts = re.findall(r"<script[^>]*type=\"application/json\"[^>]*>(.*?)</script>", html, re.S | re.I)
    for s in scripts:
        if "quoteResponse" not in s or symbol not in s:
            continue
        s = s.strip()
        if not s.startswith("{") and not s.startswith("["):
            continue
        try:
            payload = json.loads(s)
        except Exception:
            continue
        if isinstance(payload, dict) and "body" in payload and isinstance(payload["body"], str):
            try:
                payload = json.loads(payload["body"])
            except Exception:
                continue
        if not isinstance(payload, dict):
            continue
        results = payload.get("quoteResponse", {}).get("result", [])
        for item in results:
            if item.get("symbol") == symbol:
                return item
    return None


def fmt_val(v):
    if isinstance(v, dict):
        return v.get("raw") if v.get("raw") is not None else v.get("fmt", "")
    return v if v is not None else ""


def fmt_range(low, high):
    low_v = fmt_val(low)
    high_v = fmt_val(high)
    if low_v == "" and high_v == "":
        return ""
    return f"{low_v} - {high_v}"


def fmt_bid_ask(price, size):
    p = fmt_val(price)
    s = fmt_val(size)
    if p == "" and s == "":
        return ""
    if s == "":
        return str(p)
    return f"{p} x {s}"


def fmt_date(ts):
    try:
        ts_val = fmt_val(ts)
        if ts_val == "":
            return ""
        dt = datetime.utcfromtimestamp(float(ts_val))
        return dt.strftime("%b %d, %Y")
    except Exception:
        return ""


def fmt_div_yield(rate, yld):
    r = fmt_val(rate)
    y = fmt_val(yld)
    if r == "" and y == "":
        return ""
    if y != "":
        try:
            return f"{r} ({float(y)*100:.2f}%)" if r != "" else f"({float(y)*100:.2f}%)"
        except Exception:
            return f"{r} ({y})" if r != "" else str(y)
    return str(r)


def row_from_store(symbol, store, url):
    # QuoteResponse item mapping (embedded JSON)
    return {
        "symbol": symbol,
        "as_of_timestamp": datetime.utcnow().isoformat(),
        "price": fmt_val(store.get("regularMarketPrice")),
        "change": fmt_val(store.get("regularMarketChange")),
        "change_percent": fmt_val(store.get("regularMarketChangePercent")),
        "prev_close": fmt_val(store.get("regularMarketPreviousClose")),
        "open": fmt_val(store.get("regularMarketOpen")),
        "day_range": fmt_range(store.get("regularMarketDayLow"), store.get("regularMarketDayHigh")) or fmt_val(store.get("regularMarketDayRange")),
        "week_52_range": fmt_range(store.get("fiftyTwoWeekLow"), store.get("fiftyTwoWeekHigh")) or fmt_val(store.get("fiftyTwoWeekRange")),
        "volume": fmt_val(store.get("regularMarketVolume")) or fmt_val(store.get("volume")),
        "avg_volume": fmt_val(store.get("averageDailyVolume3Month")) or fmt_val(store.get("averageDailyVolume10Day")) or fmt_val(store.get("averageVolume")),
        "market_cap": fmt_val(store.get("marketCap")),
        "market_cap_intraday": "",
        "bid": fmt_bid_ask(store.get("bid"), store.get("bidSize")),
        "ask": fmt_bid_ask(store.get("ask"), store.get("askSize")),
        "beta_5y_monthly": fmt_val(store.get("beta")),
        "pe_ttm": fmt_val(store.get("trailingPE")),
        "eps_ttm": fmt_val(store.get("epsTrailingTwelveMonths")),
        "earnings_date_est": fmt_date(store.get("earningsTimestampStart")) or fmt_date(store.get("earningsTimestamp")) or fmt_date(store.get("earningsTimestampEnd")),
        "forward_dividend_yield": fmt_div_yield(store.get("dividendRate"), store.get("dividendYield")),
        "ex_dividend_date": fmt_date(store.get("exDividendDate")),
        "target_est_1y": fmt_val(store.get("targetMeanPrice")),
        "currency": store.get("currency", "") or "",
        "source_url": url,
        "status": "ok",
    }


def empty_row(symbol, url):
    return {
        "symbol": symbol,
        "as_of_timestamp": datetime.utcnow().isoformat(),
        "price": "",
        "change": "",
        "change_percent": "",
        "prev_close": "",
        "open": "",
        "day_range": "",
        "week_52_range": "",
        "volume": "",
        "avg_volume": "",
        "market_cap": "",
        "market_cap_intraday": "",
        "bid": "",
        "ask": "",
        "beta_5y_monthly": "",
        "pe_ttm": "",
        "eps_ttm": "",
        "earnings_date_est": "",
        "forward_dividend_yield": "",
        "ex_dividend_date": "",
        "target_est_1y": "",
        "currency": "",
        "source_url": url,
        "status": "parse_error",
    }


def parse_quote_summary_table(html_text):
    try:
        doc = lxml_html.fromstring(html_text)
    except Exception:
        return {}
    data = {}
    items = doc.xpath("//li[.//span[contains(@class,'label')] and .//span[contains(@class,'value')]]") or []
    for item in items:
        label_el = item.xpath(".//span[contains(@class,'label')]")
        value_el = item.xpath(".//span[contains(@class,'value')]")
        if not label_el or not value_el:
            continue
        label = " ".join(label_el[0].text_content().split())
        value = " ".join(value_el[0].text_content().split())
        if label and value:
            data[label] = value
    rows = doc.xpath("//tr[td]") or []
    for row in rows:
        tds = row.xpath("./td")
        if len(tds) < 2:
            continue
        label = " ".join(tds[0].text_content().split())
        value = " ".join(tds[1].text_content().split())
        if label and value:
            data[label] = value
    return data


def apply_table_values(row, table_data):
    mapping = {
        "Previous Close": "prev_close",
        "Open": "open",
        "Bid": "bid",
        "Ask": "ask",
        "Day's Range": "day_range",
        "52 Week Range": "week_52_range",
        "Volume": "volume",
        "Avg. Volume": "avg_volume",
        "Market Cap (intraday)": "market_cap_intraday",
        "Beta (5Y Monthly)": "beta_5y_monthly",
        "PE Ratio (TTM)": "pe_ttm",
        "EPS (TTM)": "eps_ttm",
        "Earnings Date (est.)": "earnings_date_est",
        "Forward Dividend & Yield": "forward_dividend_yield",
        "Ex-Dividend Date": "ex_dividend_date",
        "1y Target Est": "target_est_1y",
    }
    for label, col in mapping.items():
        val = table_data.get(label, "")
        if val and not row.get(col):
            row[col] = val
    if row.get("market_cap_intraday") and not row.get("market_cap"):
        row["market_cap"] = row.get("market_cap_intraday")
    return row


def has_any_values(row):
    for key in (
        "prev_close","open","bid","ask","day_range","week_52_range","volume","avg_volume",
        "market_cap_intraday","beta_5y_monthly","pe_ttm","eps_ttm","earnings_date_est",
        "forward_dividend_yield","ex_dividend_date","target_est_1y","price","change","change_percent"
    ):
        if row.get(key):
            return True
    return False


if __name__ == "__main__":
    import sys
    from yahoo_quote_core import cli_main
    # Pass this module object into the shared runner so it can read OUT_PATH/FIELDS.
    cli_main(sys.modules[__name__], OUT_PATH)
