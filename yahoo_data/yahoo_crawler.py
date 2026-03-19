#!/usr/bin/env python3
import argparse
import csv
import json
import os
import random
import time
import urllib.parse
import urllib.request
import urllib.error
import http.cookiejar
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

SEARCH_URL = "https://query2.finance.yahoo.com/v1/finance/search?q={query}"
CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=max&interval=1d&events=history"
QUOTE_SUMMARY_URLS = [
    "https://query2.finance.yahoo.com/v10/finance/quoteSummary/{symbol}?modules={modules}",
    "https://query1.finance.yahoo.com/v10/finance/quoteSummary/{symbol}?modules={modules}",
]
PREFETCH_URL = "https://finance.yahoo.com"
CRUMB_URLS = {
    "query1.finance.yahoo.com": "https://query1.finance.yahoo.com/v1/test/getcrumb",
    "query2.finance.yahoo.com": "https://query2.finance.yahoo.com/v1/test/getcrumb",
}

USER_AGENT = "Mozilla/5.0 (compatible; YahooIndexCrawler/1.0; +https://finance.yahoo.com)"
RATE_PER_SEC = 0.5  # 1 request / 2 seconds
BURST = 2
TIMEOUT = 30

class TokenBucket:
    def __init__(self, rate_per_sec, capacity):
        self.rate = rate_per_sec
        self.capacity = capacity
        self.tokens = capacity
        self.last_refill = time.time()

    def consume(self, tokens=1):
        now = time.time()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
        self.last_refill = now
        if self.tokens < tokens:
            wait = (tokens - self.tokens) / self.rate
            time.sleep(wait)
            self.tokens = 0
            self.last_refill = time.time()
        else:
            self.tokens -= tokens

class RateLimiter:
    def __init__(self, rate_per_sec, burst):
        self.rate_per_sec = rate_per_sec
        self.burst = burst
        self.buckets = defaultdict(lambda: TokenBucket(self.rate_per_sec, self.burst))

    def wait(self, host):
        self.buckets[host].consume(1)

class YahooSession:
    def __init__(self):
        self.cj = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cj))
        self.crumbs = {}
        self.apply_env_cookies()

    def _set_cookie(self, name, value, domain):
        if not value:
            return
        cookie = http.cookiejar.Cookie(
            version=0,
            name=name,
            value=value,
            port=None,
            port_specified=False,
            domain=domain,
            domain_specified=True,
            domain_initial_dot=domain.startswith("."),
            path="/",
            path_specified=True,
            secure=True,
            expires=None,
            discard=True,
            comment=None,
            comment_url=None,
            rest={"HttpOnly": None},
            rfc2109=False,
        )
        self.cj.set_cookie(cookie)

    def apply_env_cookies(self):
        # Optional auth cookies for Yahoo Finance
        a1 = os.environ.get("YAHOO_A1")
        a3 = os.environ.get("YAHOO_A3")
        a1s = os.environ.get("YAHOO_A1S")
        for domain in [".yahoo.com"]:
            self._set_cookie("A1", a1, domain)
            self._set_cookie("A3", a3, domain)
            self._set_cookie("A1S", a1s, domain)

    def prefetch(self):
        req = urllib.request.Request(PREFETCH_URL, headers={"User-Agent": USER_AGENT})
        try:
            with self.opener.open(req, timeout=TIMEOUT) as resp:
                resp.read()
        except Exception:
            pass
        for host in CRUMB_URLS:
            self.refresh_crumb(host)

    def refresh_crumb(self, host):
        url = CRUMB_URLS.get(host)
        if not url:
            return
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with self.opener.open(req, timeout=TIMEOUT) as resp:
                crumb = resp.read().decode("utf-8", errors="replace").strip()
                if crumb:
                    self.crumbs[host] = crumb
        except Exception:
            pass

class CrawlLogger:
    def __init__(self):
        self.rows = []

    def log(self, url, status, reason="", crumb=""):
        self.rows.append({
            "timestamp": datetime.utcnow().isoformat(),
            "url": url,
            "status": status,
            "reason": reason,
            "crumb": crumb,
        })

    def write(self, path):
        fieldnames = ["timestamp", "url", "status", "reason", "crumb"]
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            for r in self.rows:
                w.writerow(r)

def add_crumb(url, session):
    parsed = urllib.parse.urlparse(url)
    crumb = session.crumbs.get(parsed.netloc) if session else None
    if not crumb:
        return url
    q = urllib.parse.parse_qs(parsed.query)
    if "crumb" in q:
        return url
    q["crumb"] = [crumb]
    new_query = urllib.parse.urlencode(q, doseq=True)
    return urllib.parse.urlunparse(parsed._replace(query=new_query))

def is_invalid_crumb(obj):
    if not isinstance(obj, dict):
        return False
    finance = obj.get("finance")
    if not isinstance(finance, dict):
        return False
    err = finance.get("error")
    if not isinstance(err, dict):
        return False
    return err.get("code") == "Unauthorized" and "Crumb" in (err.get("description") or "")

def fetch_json(url, opener, rate_limiter, logger, max_retries=3, session=None, use_crumb=False):
    host = urllib.parse.urlparse(url).netloc
    for attempt in range(max_retries + 1):
        rate_limiter.wait(host)
        final_url = add_crumb(url, session) if (use_crumb and session) else url
        crumb_used = session.crumbs.get(host, "") if (use_crumb and session) else ""
        req = urllib.request.Request(final_url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        try:
            with opener.open(req, timeout=TIMEOUT) as resp:
                status = resp.status
                data = resp.read().decode("utf-8", errors="replace")
                logger.log(url, str(status), crumb=crumb_used)
                obj = json.loads(data)
                if use_crumb and is_invalid_crumb(obj):
                    print("needs new crumb")
                    sys.exit(1)
                return obj
        except urllib.error.HTTPError as e:
            code = e.code
            if code == 429 or 500 <= code < 600:
                logger.log(url, str(code), "retry", crumb=crumb_used)
                if attempt < max_retries:
                    backoff = (2 ** attempt) + random.uniform(0, 0.5)
                    time.sleep(backoff)
                    continue
            if code == 401 and use_crumb:
                print("needs new crumb")
                sys.exit(1)
            logger.log(url, str(code), "error", crumb=crumb_used)
            return None
        except Exception as e:
            logger.log(url, "error", str(e), crumb=crumb_used)
            return None
    return None

def fetch_json_with_fallbacks(urls, opener, rate_limiter, logger, session=None, use_crumb=False):
    for url in urls:
        obj = fetch_json(url, opener, rate_limiter, logger, session=session, use_crumb=use_crumb)
        if obj is None:
            continue
        if use_crumb and is_invalid_crumb(obj):
            continue
        return url, obj
    return None, None

def read_index_master(path):
    rows = []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows

def parse_symbols_arg(arg):
    if not arg:
        return []
    s = arg.strip()
    if s.startswith("["):
        try:
            arr = json.loads(s)
            if isinstance(arr, list):
                return [str(x).strip() for x in arr if str(x).strip()]
        except Exception:
            pass
    return [x.strip() for x in s.split(",") if x.strip()]

def write_index_master(path, rows, extra_fields):
    base_fields = ["index_id", "symbol", "name", "currency", "category_group", "category", "exchange", "source_url"]
    fields = base_fields + extra_fields
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            out = {k: r.get(k, "") for k in fields}
            w.writerow(out)

def normalize_symbol(s):
    return (s or "").strip()

def score_candidate(symbol, name, cand):
    score = 0.0
    cand_symbol = cand.get("symbol", "")
    cand_name = cand.get("shortname") or cand.get("longname") or ""
    quote_type = cand.get("quoteType", "")
    if quote_type == "INDEX":
        score += 0.6
    if cand_symbol.upper() == symbol.upper():
        score += 0.6
    if name and cand_name and name.lower() in cand_name.lower():
        score += 0.4
    return score, cand_symbol, cand_name, quote_type

def select_best_candidate(symbol, name, quotes):
    best = None
    best_score = -1
    for cand in quotes:
        score, cand_symbol, cand_name, quote_type = score_candidate(symbol, name, cand)
        if score > best_score:
            best_score = score
            best = {
                "yahoo_symbol": cand_symbol,
                "matched_name": cand_name,
                "quoteType": quote_type,
                "confidence": round(min(score, 1.0), 3),
            }
    return best

def append_symbol_map(path, rows):
    fields = ["index_id", "yahoo_symbol", "confidence", "quoteType", "matched_name", "source_url"]
    file_exists = Path(path).exists()
    existing = set()
    if file_exists:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            r = csv.DictReader(f)
            for row in r:
                existing.add((row.get("index_id", ""), row.get("yahoo_symbol", "")))
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if not file_exists:
            w.writeheader()
        for r in rows:
            key = (r.get("index_id", ""), r.get("yahoo_symbol", ""))
            if key in existing:
                continue
            w.writerow({k: r.get(k, "") for k in fields})

def write_levels(path, rows):
    fields = ["index_id", "date", "level_close", "level_open", "level_high", "level_low", "total_return_level", "source_url", "source"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)

def append_levels(path, rows):
    fields = ["index_id", "date", "level_close", "level_open", "level_high", "level_low", "total_return_level", "source_url", "source"]
    file_exists = Path(path).exists()
    existing = set()
    if file_exists:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            r = csv.DictReader(f)
            for row in r:
                existing.add((row.get("index_id", ""), row.get("date", "")))
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if not file_exists:
            w.writeheader()
        for r in rows:
            key = (r.get("index_id", ""), r.get("date", ""))
            if key in existing:
                continue
            w.writerow({k: r.get(k, "") for k in fields})

def write_indicators(path, rows):
    fields = ["index_id", "yahoo_symbol", "indicator_group", "indicator_name", "indicator_value", "as_of_date", "source_url"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)

def append_indicators(path, rows):
    fields = ["index_id", "yahoo_symbol", "indicator_group", "indicator_name", "indicator_value", "as_of_date", "source_url"]
    file_exists = Path(path).exists()
    existing = set()
    if file_exists:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            r = csv.DictReader(f)
            for row in r:
                existing.add((row.get("index_id", ""), row.get("yahoo_symbol", ""), row.get("indicator_group", ""), row.get("indicator_name", ""), row.get("as_of_date", "")))
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if not file_exists:
            w.writeheader()
        for r in rows:
            key = (r.get("index_id", ""), r.get("yahoo_symbol", ""), r.get("indicator_group", ""), r.get("indicator_name", ""), r.get("as_of_date", ""))
            if key in existing:
                continue
            w.writerow({k: r.get(k, "") for k in fields})

def write_technicals(path, rows):
    fields = [
        "index_id", "date",
        "ma_50", "ma_200",
        "rsi_14",
        "macd", "macd_signal", "macd_hist",
        "bb_upper", "bb_mid", "bb_lower",
        "stoch_k", "stoch_d",
        "source_url",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)

def append_timeseries(path, levels_rows, technicals_rows):
    # Combine by (index_id, date) and append to a single timeseries file.
    levels = {(r["index_id"], r["date"]): r for r in levels_rows}
    techs = {(r["index_id"], r["date"]): r for r in technicals_rows}
    all_keys = sorted(set(levels.keys()) | set(techs.keys()))
    fields = [
        "index_id", "date",
        "level_open", "level_high", "level_low", "level_close", "total_return_level", "source_url", "source",
        "ma_50", "ma_200", "rsi_14", "macd", "macd_signal", "macd_hist",
        "bb_upper", "bb_mid", "bb_lower", "stoch_k", "stoch_d",
        "technical_source_url",
    ]
    file_exists = Path(path).exists()
    existing = set()
    if file_exists:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            r = csv.DictReader(f)
            for row in r:
                existing.add((row.get("index_id", ""), row.get("date", "")))
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if not file_exists:
            w.writeheader()
        for key in all_keys:
            if key in existing:
                continue
            l = levels.get(key, {})
            t = techs.get(key, {})
            w.writerow({
                "index_id": key[0],
                "date": key[1],
                "level_open": l.get("level_open", ""),
                "level_high": l.get("level_high", ""),
                "level_low": l.get("level_low", ""),
                "level_close": l.get("level_close", ""),
                "total_return_level": l.get("total_return_level", ""),
                "source_url": l.get("source_url", ""),
                "source": l.get("source", ""),
                "ma_50": t.get("ma_50", ""),
                "ma_200": t.get("ma_200", ""),
                "rsi_14": t.get("rsi_14", ""),
                "macd": t.get("macd", ""),
                "macd_signal": t.get("macd_signal", ""),
                "macd_hist": t.get("macd_hist", ""),
                "bb_upper": t.get("bb_upper", ""),
                "bb_mid": t.get("bb_mid", ""),
                "bb_lower": t.get("bb_lower", ""),
                "stoch_k": t.get("stoch_k", ""),
                "stoch_d": t.get("stoch_d", ""),
                "technical_source_url": t.get("source_url", ""),
            })


def get_raw(v):
    if isinstance(v, dict):
        if "raw" in v:
            return v.get("raw")
        if "fmt" in v:
            return v.get("fmt")
    return v

def safe_get(obj, path):
    cur = obj
    for p in path:
        if not isinstance(cur, dict):
            return None
        if p not in cur:
            return None
        cur = cur[p]
    return cur

def sma(values, window):
    out = [None] * len(values)
    if window <= 0:
        return out
    s = 0.0
    count = 0
    for i, v in enumerate(values):
        if v is None:
            out[i] = None
            continue
        s += v
        count += 1
        if i >= window:
            prev = values[i - window]
            if prev is not None:
                s -= prev
                count -= 1
        if i >= window - 1 and count == window:
            out[i] = s / window
    return out

def ema(values, window):
    out = [None] * len(values)
    if window <= 0:
        return out
    k = 2 / (window + 1)
    ema_val = None
    for i, v in enumerate(values):
        if v is None:
            out[i] = None
            continue
        if ema_val is None:
            ema_val = v
        else:
            ema_val = (v - ema_val) * k + ema_val
        out[i] = ema_val
    return out

def rsi(values, window=14):
    out = [None] * len(values)
    if window <= 0:
        return out
    gains = 0.0
    losses = 0.0
    for i in range(1, len(values)):
        if values[i] is None or values[i - 1] is None:
            out[i] = None
            continue
        change = values[i] - values[i - 1]
        gain = max(change, 0.0)
        loss = max(-change, 0.0)
        if i <= window:
            gains += gain
            losses += loss
            if i == window:
                rs = gains / losses if losses != 0 else None
                out[i] = 100 - (100 / (1 + rs)) if rs is not None else 100
        else:
            gains = (gains * (window - 1) + gain) / window
            losses = (losses * (window - 1) + loss) / window
            rs = gains / losses if losses != 0 else None
            out[i] = 100 - (100 / (1 + rs)) if rs is not None else 100
    return out

def bollinger(values, window=20, num_std=2):
    mid = sma(values, window)
    upper = [None] * len(values)
    lower = [None] * len(values)
    for i in range(len(values)):
        if i < window - 1:
            continue
        mean = mid[i]
        if mean is None:
            continue
        window_vals = [v for v in values[i - window + 1:i + 1] if v is not None]
        if len(window_vals) != window:
            continue
        var = sum((v - mean) ** 2 for v in window_vals) / window
        std = var ** 0.5
        upper[i] = mean + num_std * std
        lower[i] = mean - num_std * std
    return upper, mid, lower

def stochastic(highs, lows, closes, window=14, smooth=3):
    k = [None] * len(closes)
    d = [None] * len(closes)
    for i in range(len(closes)):
        if i < window - 1:
            continue
        window_high = [h for h in highs[i - window + 1:i + 1] if h is not None]
        window_low = [l for l in lows[i - window + 1:i + 1] if l is not None]
        c = closes[i]
        if not window_high or not window_low or c is None:
            continue
        hh = max(window_high)
        ll = min(window_low)
        if hh == ll:
            k[i] = 0.0
        else:
            k[i] = (c - ll) / (hh - ll) * 100
    # smooth %K to %D
    k_sma = sma([v if v is not None else None for v in k], smooth)
    for i in range(len(d)):
        d[i] = k_sma[i]
    return k, d

def main():
    parser = argparse.ArgumentParser(description="Yahoo Finance index crawler")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of indexes to crawl (0 = no limit)")
    parser.add_argument("--symbols", type=str, default="", help="Comma-separated or JSON list of Yahoo symbols")
    args = parser.parse_args()

    rate_limiter = RateLimiter(RATE_PER_SEC, BURST)
    logger = CrawlLogger()
    session = YahooSession()
    session.prefetch()

    symbols = parse_symbols_arg(args.symbols)
    index_master_path = BASE_DIR / "index_master.csv"
    if symbols:
        masters = []
        for sym in symbols:
            masters.append({
                "index_id": sym,
                "symbol": sym,
                "name": "",
                "currency": "",
                "category_group": "",
                "category": "",
                "exchange": "",
                "source_url": "",
            })
    else:
        if not index_master_path.exists():
            print("index_master.csv not found. Provide --symbols or run nasdaq_crawler.py first.")
            return
        masters = read_index_master(index_master_path)
        if args.limit and args.limit > 0:
            masters = masters[: args.limit]

    symbol_map_rows = []
    levels_rows = []
    indicators_rows = []
    technicals_rows = []
    quote_cache = {}

    for rec in masters:
        index_id = rec.get("index_id")
        symbol = rec.get("symbol") or ""
        name = rec.get("name") or ""
        query = symbol if symbol else name
        if not query:
            continue
        if symbols:
            yahoo_symbol = symbol
            symbol_map_rows.append({
                "index_id": index_id,
                "yahoo_symbol": yahoo_symbol,
                "confidence": "direct",
                "quoteType": "",
                "matched_name": "",
                "source_url": "",
            })
        else:
            search_url = SEARCH_URL.format(query=urllib.parse.quote(query))
            search_json = fetch_json(search_url, session.opener, rate_limiter, logger, session=session, use_crumb=False)
            if not search_json or "quotes" not in search_json:
                symbol_map_rows.append({
                    "index_id": index_id,
                    "yahoo_symbol": "",
                    "confidence": "",
                    "quoteType": "",
                    "matched_name": "",
                    "source_url": search_url,
                })
                continue

            best = select_best_candidate(symbol, name, search_json.get("quotes", []))
            if not best or not best.get("yahoo_symbol"):
                symbol_map_rows.append({
                    "index_id": index_id,
                    "yahoo_symbol": "",
                    "confidence": "",
                    "quoteType": "",
                    "matched_name": "",
                    "source_url": search_url,
                })
                continue

            yahoo_symbol = best["yahoo_symbol"]
            symbol_map_rows.append({
                "index_id": index_id,
                "yahoo_symbol": yahoo_symbol,
                "confidence": best["confidence"],
                "quoteType": best["quoteType"],
                "matched_name": best["matched_name"],
                "source_url": search_url,
            })

        chart_url = CHART_URL.format(symbol=urllib.parse.quote(yahoo_symbol))
        chart_json = fetch_json(chart_url, session.opener, rate_limiter, logger, session=session, use_crumb=False)
        if not chart_json:
            continue
        chart = chart_json.get("chart", {})
        if chart.get("error"):
            continue
        result = (chart.get("result") or [None])[0]
        if not result:
            continue

        meta = result.get("meta", {})
        rec["yahoo_symbol"] = meta.get("symbol") or yahoo_symbol
        rec["yahoo_exchange"] = meta.get("exchangeName", "")
        rec["yahoo_currency"] = meta.get("currency", "")
        rec["yahoo_instrumentType"] = meta.get("instrumentType", "")

        timestamps = result.get("timestamp") or []
        indicators = result.get("indicators", {}).get("quote", [])
        if not indicators:
            continue
        quote = indicators[0]
        opens = quote.get("open", [])
        highs = quote.get("high", [])
        lows = quote.get("low", [])
        closes = quote.get("close", [])

        for i, ts in enumerate(timestamps):
            date = datetime.utcfromtimestamp(ts).date().isoformat()
            levels_rows.append({
                "index_id": index_id,
                "date": date,
                "level_close": closes[i] if i < len(closes) else "",
                "level_open": opens[i] if i < len(opens) else "",
                "level_high": highs[i] if i < len(highs) else "",
                "level_low": lows[i] if i < len(lows) else "",
                "total_return_level": "",
                "source_url": chart_url,
                "source": "yahoo",
            })

        # Technical indicators
        close_vals = [c if isinstance(c, (int, float)) else None for c in closes]
        high_vals = [h if isinstance(h, (int, float)) else None for h in highs]
        low_vals = [l if isinstance(l, (int, float)) else None for l in lows]
        ma50 = sma(close_vals, 50)
        ma200 = sma(close_vals, 200)
        rsi14 = rsi(close_vals, 14)
        ema12 = ema(close_vals, 12)
        ema26 = ema(close_vals, 26)
        macd = [None if ema12[i] is None or ema26[i] is None else ema12[i] - ema26[i] for i in range(len(close_vals))]
        macd_signal = ema([v if v is not None else None for v in macd], 9)
        macd_hist = [None if macd[i] is None or macd_signal[i] is None else macd[i] - macd_signal[i] for i in range(len(close_vals))]
        bb_upper, bb_mid, bb_lower = bollinger(close_vals, 20, 2)
        stoch_k, stoch_d = stochastic(high_vals, low_vals, close_vals, 14, 3)

        for i, ts in enumerate(timestamps):
            date = datetime.utcfromtimestamp(ts).date().isoformat()
            technicals_rows.append({
                "index_id": index_id,
                "date": date,
                "ma_50": ma50[i],
                "ma_200": ma200[i],
                "rsi_14": rsi14[i],
                "macd": macd[i],
                "macd_signal": macd_signal[i],
                "macd_hist": macd_hist[i],
                "bb_upper": bb_upper[i],
                "bb_mid": bb_mid[i],
                "bb_lower": bb_lower[i],
                "stoch_k": stoch_k[i],
                "stoch_d": stoch_d[i],
                "source_url": chart_url,
            })

        # QuoteSummary modules (cache)
        if yahoo_symbol not in quote_cache:
            modules = ",".join([
                "price", "summaryDetail", "defaultKeyStatistics", "financialData",
                "calendarEvents", "earningsTrend", "recommendationTrend",
                "upgradeDowngradeHistory", "esgScores", "assetProfile"
            ])
            qs_urls = [
                u.format(symbol=urllib.parse.quote(yahoo_symbol), modules=modules)
                for u in QUOTE_SUMMARY_URLS
            ]
            qs_url, qs_json = fetch_json_with_fallbacks(qs_urls, session.opener, rate_limiter, logger, session=session, use_crumb=True)
            quote_cache[yahoo_symbol] = (qs_url, qs_json)
        qs_url, qs_json = quote_cache.get(yahoo_symbol, (None, None))
        qs_result = None
        if qs_json:
            qs = qs_json.get("quoteSummary", {})
            qs_result = (qs.get("result") or [None])[0]

        indicator_specs = [
            ("price_trading", "currentPrice", ["price", "regularMarketPrice"]),
            ("price_trading", "open", ["summaryDetail", "open"]),
            ("price_trading", "previousClose", ["summaryDetail", "previousClose"]),
            ("price_trading", "dayLow", ["summaryDetail", "dayLow"]),
            ("price_trading", "dayHigh", ["summaryDetail", "dayHigh"]),
            ("price_trading", "fiftyTwoWeekLow", ["summaryDetail", "fiftyTwoWeekLow"]),
            ("price_trading", "fiftyTwoWeekHigh", ["summaryDetail", "fiftyTwoWeekHigh"]),
            ("price_trading", "volume", ["summaryDetail", "volume"]),
            ("price_trading", "averageVolume", ["summaryDetail", "averageVolume"]),
            ("price_trading", "marketCap", ["price", "marketCap"]),
            ("price_trading", "beta", ["summaryDetail", "beta"]),

            ("valuation", "trailingPE", ["summaryDetail", "trailingPE"]),
            ("valuation", "forwardPE", ["summaryDetail", "forwardPE"]),
            ("valuation", "pegRatio", ["defaultKeyStatistics", "pegRatio"]),
            ("valuation", "priceToBook", ["defaultKeyStatistics", "priceToBook"]),
            ("valuation", "priceToSalesTrailing12Months", ["summaryDetail", "priceToSalesTrailing12Months"]),
            ("valuation", "enterpriseValue", ["defaultKeyStatistics", "enterpriseValue"]),
            ("valuation", "enterpriseToEbitda", ["defaultKeyStatistics", "enterpriseToEbitda"]),
            ("valuation", "enterpriseToRevenue", ["defaultKeyStatistics", "enterpriseToRevenue"]),

            ("profitability", "grossProfits", ["financialData", "grossProfits"]),
            ("profitability", "operatingMargins", ["financialData", "operatingMargins"]),
            ("profitability", "profitMargins", ["defaultKeyStatistics", "profitMargins"]),
            ("profitability", "returnOnAssets", ["financialData", "returnOnAssets"]),
            ("profitability", "returnOnEquity", ["financialData", "returnOnEquity"]),

            ("balance_sheet", "totalCash", ["financialData", "totalCash"]),
            ("balance_sheet", "totalDebt", ["financialData", "totalDebt"]),
            ("balance_sheet", "debtToEquity", ["financialData", "debtToEquity"]),
            ("balance_sheet", "currentRatio", ["financialData", "currentRatio"]),
            ("balance_sheet", "bookValue", ["defaultKeyStatistics", "bookValue"]),

            ("income_cashflow", "totalRevenue", ["financialData", "totalRevenue"]),
            ("income_cashflow", "revenueGrowth", ["financialData", "revenueGrowth"]),
            ("income_cashflow", "netIncomeToCommon", ["defaultKeyStatistics", "netIncomeToCommon"]),
            ("income_cashflow", "ebitda", ["financialData", "ebitda"]),
            ("income_cashflow", "operatingCashflow", ["financialData", "operatingCashflow"]),
            ("income_cashflow", "freeCashflow", ["financialData", "freeCashflow"]),

            ("earnings", "trailingEps", ["defaultKeyStatistics", "trailingEps"]),
            ("earnings", "forwardEps", ["defaultKeyStatistics", "forwardEps"]),
            ("earnings", "earningsGrowth", ["financialData", "earningsGrowth"]),
            ("earnings", "earningsQuarterlyGrowth", ["defaultKeyStatistics", "earningsQuarterlyGrowth"]),

            ("dividends", "dividendYield", ["summaryDetail", "dividendYield"]),
            ("dividends", "dividendRate", ["summaryDetail", "dividendRate"]),
            ("dividends", "payoutRatio", ["summaryDetail", "payoutRatio"]),
            ("dividends", "exDividendDate", ["summaryDetail", "exDividendDate"]),

            ("analyst", "recommendationKey", ["financialData", "recommendationKey"]),
            ("analyst", "numberOfAnalystOpinions", ["financialData", "numberOfAnalystOpinions"]),
            ("analyst", "targetMeanPrice", ["financialData", "targetMeanPrice"]),
            ("analyst", "targetHighPrice", ["financialData", "targetHighPrice"]),
            ("analyst", "targetLowPrice", ["financialData", "targetLowPrice"]),

            ("additional", "sector", ["assetProfile", "sector"]),
            ("additional", "industry", ["assetProfile", "industry"]),
            ("additional", "esgScore", ["esgScores", "totalEsg"]),
        ]

        as_of_date = datetime.utcnow().date().isoformat()
        for group, name, path in indicator_specs:
            value = None
            if qs_result:
                value = get_raw(safe_get(qs_result, path))
            indicators_rows.append({
                "index_id": index_id,
                "yahoo_symbol": yahoo_symbol,
                "indicator_group": group,
                "indicator_name": name,
                "indicator_value": value if value is not None else "",
                "as_of_date": as_of_date,
                "source_url": qs_url or "",
            })

    # ensure all symbols present in indicators are also captured in index_symbol_map
    symbol_map_keys = {(r.get("index_id", ""), r.get("yahoo_symbol", "")) for r in symbol_map_rows}
    indicator_source_by_symbol = {}
    for r in indicators_rows:
        ysym = r.get("yahoo_symbol", "")
        if ysym and ysym not in indicator_source_by_symbol:
            indicator_source_by_symbol[ysym] = r.get("source_url", "")
    for r in indicators_rows:
        idx = r.get("index_id", "")
        ysym = r.get("yahoo_symbol", "")
        if not ysym:
            continue
        key = (idx, ysym)
        if key in symbol_map_keys:
            continue
        symbol_map_rows.append({
            "index_id": idx,
            "yahoo_symbol": ysym,
            "confidence": "",
            "quoteType": "",
            "matched_name": "",
            "source_url": indicator_source_by_symbol.get(ysym, ""),
        })
        symbol_map_keys.add(key)


    # write outputs
    append_symbol_map(BASE_DIR / "index_symbol_map.csv", symbol_map_rows)
    append_levels(BASE_DIR / "index_levels.csv", levels_rows)
    append_indicators(BASE_DIR / "yahoo_indicators.csv", indicators_rows)
    # write_technicals(BASE_DIR / "yahoo_technicals.csv", technicals_rows)
    append_timeseries(BASE_DIR / "yahoo_timeseries.csv", levels_rows, technicals_rows)
    if not symbols:
        write_index_master(
            index_master_path,
            masters,
            ["yahoo_symbol", "yahoo_exchange", "yahoo_currency", "yahoo_instrumentType"],
        )
    logger.write(BASE_DIR / "yahoo_crawl_log.csv")

    print("Done. Wrote:")
    print("- index_symbol_map.csv")
    # print("- index_levels.csv (source=yahoo)")
    print("- yahoo_indicators.csv")
    # print("- yahoo_technicals.csv")
    print("- yahoo_timeseries.csv (appended)")
    if not symbols:
        print("- index_master.csv (augmented Yahoo fields)")
    print("- yahoo_crawl_log.csv")

if __name__ == "__main__":
    main()
