#!/usr/bin/env python3
"""Quick verification of news source APIs. Run: python scripts/verify_news_sources.py"""
import sys
import urllib.request
import urllib.parse
import json

def test_gdelt():
    """GDELT v2 doc API - free, no key."""
    url = "https://api.gdeltproject.org/api/v2/doc/doc"
    params = {"query": "NVDA", "mode": "ArtList", "maxrecords": 3, "format": "json"}
    req = urllib.request.Request(
        f"{url}?{urllib.parse.urlencode(params)}",
        headers={"User-Agent": "OpenFund-AI/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode())
            articles = data.get("articles") or data.get("ArticleList") or []
            return "OK", f"{len(articles)} articles" if isinstance(articles, list) else str(data)[:200]
    except Exception as e:
        return "FAIL", str(e)[:150]

def test_google_news_rss():
    """Google News RSS - free."""
    url = "https://news.google.com/rss/search?q=NVDA&hl=en-US&gl=US&ceid=US:en"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; OpenFund-AI/1.0)"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            body = r.read().decode("utf-8", errors="replace")
            count = body.count("<item>") + body.count("<entry>")
            return "OK", f"~{count} items"
    except Exception as e:
        return "FAIL", str(e)[:150]

def test_yahoo_finance_rss():
    """Yahoo Finance RSS - fixed feed."""
    url = "https://finance.yahoo.com/news/rssindex"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; OpenFund-AI/1.0)"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            body = r.read().decode("utf-8", errors="replace")
            count = body.count("<item>")
            return "OK", f"~{count} items"
    except Exception as e:
        return "FAIL", str(e)[:150]

def main():
    sources = [
        ("Google News RSS", test_google_news_rss),
        ("GDELT API", test_gdelt),
        ("Yahoo Finance RSS", test_yahoo_finance_rss),
    ]
    print("News source verification:")
    print("-" * 50)
    ok = []
    for name, fn in sources:
        status, msg = fn()
        print(f"  {name}: {status} - {msg}")
        if status == "OK":
            ok.append(name)
    print("-" * 50)
    print(f"Available (no key or with key): {ok}")
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())
