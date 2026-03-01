#!/usr/bin/env python3
"""Test every third-party API call and report which ones are workable.

Loads .env via load_config(), makes real network calls per vendor (Alpha Vantage,
Finnhub, Tavily, LLM), and prints PASS/FAIL/SKIP with timing and a summary.
Skips vendors when the required API key is absent.

Usage (from project root):
  PYTHONPATH=. python scripts/test_third_party_apis.py
  PYTHONPATH=. python scripts/test_third_party_apis.py --symbol TSLA
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from traceback import format_exc


def _snippet(content: str, max_len: int = 60) -> str:
    """Return a short snippet of content for display."""
    if not content:
        return "(empty)"
    text = (content or "").strip().replace("\n", " ")
    if len(text) <= max_len:
        return text
    return text[: max_len - 3].rstrip() + "..."


def _is_pass(result: dict) -> bool:
    """True if result is success: no 'error' and non-empty 'content'."""
    if not isinstance(result, dict):
        return False
    if "error" in result:
        return False
    content = result.get("content")
    return isinstance(content, str) and len(content.strip()) > 0


def _run_one(name: str, fn, *args, **kwargs) -> tuple[str, float, str]:
    """Run fn(*args, **kwargs); return (PASS|FAIL, elapsed_sec, detail)."""
    start = time.perf_counter()
    try:
        result = fn(*args, **kwargs)
        elapsed = time.perf_counter() - start
        if _is_pass(result):
            detail = _snippet(result.get("content", ""))
            return ("PASS", elapsed, detail)
        err = result.get("error", "unknown")
        return ("FAIL", elapsed, str(err)[:80])
    except Exception as e:
        elapsed = time.perf_counter() - start
        tb = format_exc()
        line = tb.strip().split("\n")[-1] if tb else str(e)
        return ("FAIL", elapsed, line[:80])


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Test third-party APIs (Alpha Vantage, Finnhub, Tavily, LLM)."
    )
    parser.add_argument(
        "--symbol",
        default="AAPL",
        help="Ticker symbol for market/indicator tests (default: AAPL)",
    )
    args = parser.parse_args()

    # Reduce noise from mcp.tools loggers (they log full tracebacks on error)
    logging.getLogger("mcp.tools").setLevel(logging.WARNING)

    from config.config import load_config

    config = load_config()
    symbol = (args.symbol or "AAPL").strip().upper()

    today = datetime.today().strftime("%Y-%m-%d")
    start_5d = (datetime.today() - timedelta(days=5)).strftime("%Y-%m-%d")

    counts = {"PASS": 0, "FAIL": 0, "SKIP": 0, "NOT_IMPL": 0}
    rows: list[tuple[str, str, float, str]] = []

    print(f"=== Third-Party API Health Check  ({today}) ===\n")

    # --- Alpha Vantage ---
    from mcp.tools import market_tool
    from mcp.tools import analyst_tool

    has_av = bool((os.getenv("ALPHA_VANTAGE_API_KEY") or "").strip())
    print(f"\n[Alpha Vantage]  (key set: {'YES' if has_av else 'NO'})")
    if has_av:
        av_cases = [
            ("get_stock_data_av", lambda: market_tool.get_stock_data_av(symbol, start_5d, today)),
            ("get_fundamentals_av", lambda: market_tool.get_fundamentals_av(symbol)),
            ("get_balance_sheet_av", lambda: market_tool.get_balance_sheet_av(symbol)),
            ("get_cashflow_av", lambda: market_tool.get_cashflow_av(symbol)),
            ("get_income_statement_av", lambda: market_tool.get_income_statement_av(symbol)),
            ("get_news_av", lambda: market_tool.get_news_av(symbol, start_5d, today)),
            ("get_global_news_av", lambda: market_tool.get_global_news_av(today, 5, 3)),
            ("get_insider_transactions_av", lambda: market_tool.get_insider_transactions_av(symbol)),
            ("get_ticker_info_av", lambda: market_tool.get_ticker_info_av(symbol)),
            (
                "get_indicators_av",
                lambda: analyst_tool.get_indicators_av(
                    symbol, "close_50_sma", today, 30
                ),
            ),
        ]
        for name, fn in av_cases:
            status, elapsed, detail = _run_one(name, fn)
            counts[status] += 1
            rows.append((name, status, elapsed, detail))
            print(f"  {name:<28} {status:<6} {elapsed:.2f}s  {detail}")
    else:
        counts["SKIP"] += 10
        print("  (skipping all — ALPHA_VANTAGE_API_KEY not set)")

    # --- Finnhub ---
    has_finnhub = bool((os.getenv("FINNHUB_API_KEY") or "").strip())
    print(f"\n[Finnhub]  (key set: {'YES' if has_finnhub else 'NO'})")
    if has_finnhub:
        fh_cases = [
            ("get_fundamentals_finnhub", lambda: market_tool.get_fundamentals_finnhub(symbol)),
            ("get_ticker_info_finnhub", lambda: market_tool.get_ticker_info_finnhub(symbol)),
            (
                "get_stock_data_finnhub",
                lambda: market_tool.get_stock_data_finnhub(symbol, start_5d, today),
            ),
        ]
        for name, fn in fh_cases:
            status, elapsed, detail = _run_one(name, fn)
            counts[status] += 1
            rows.append((name, status, elapsed, detail))
            print(f"  {name:<28} {status:<6} {elapsed:.2f}s  {detail}")
    else:
        counts["SKIP"] += 3
        print("  (skipping all — FINNHUB_API_KEY not set)")

    # --- Tavily ---
    has_tavily = bool((config.tavily_api_key or "").strip())
    print(f"\n[Tavily]  (key set: {'YES' if has_tavily else 'NO'})")
    if has_tavily:
        try:
            market_tool.search_web("test query")
        except NotImplementedError:
            counts["NOT_IMPL"] += 1
            print("  search_web              NOT_IMPL  —  (NotImplementedError)")
        else:
            status, elapsed, detail = _run_one("search_web", market_tool.search_web, "test")
            counts[status] += 1
            print(f"  {'search_web':<28} {status:<6} {elapsed:.2f}s  {detail}")
    else:
        counts["SKIP"] += 1
        print("  (skipping — TAVILY_API_KEY not set; search_web is NotImplementedError)")

    # --- LLM ---
    has_llm = bool((config.llm_api_key or "").strip())
    model = (config.llm_model or "gpt-4o-mini").strip() or "gpt-4o-mini"
    print(f"\n[LLM]  (key set: {'YES' if has_llm else 'NO'}, model: {model})")
    if has_llm:
        try:
            from llm.factory import get_llm_client

            client = get_llm_client(config)
            start = time.perf_counter()
            out = client.complete("You are a test bot.", "Say exactly: pong")
            elapsed = time.perf_counter() - start
            if isinstance(out, str) and out.strip():
                counts["PASS"] += 1
                print(f"  {'chat_completion':<28} PASS   {elapsed:.2f}s  {_snippet(out)}")
            else:
                counts["FAIL"] += 1
                print(f"  {'chat_completion':<28} FAIL   {elapsed:.2f}s  (empty or non-string)")
        except Exception as e:
            counts["FAIL"] += 1
            print(f"  {'chat_completion':<28} FAIL    —  {e}")
    else:
        counts["SKIP"] += 1
        print("  (skipping — LLM_API_KEY not set)")

    # --- Summary ---
    print("\n=== Summary ===")
    print(f"  PASS     {counts['PASS']}")
    print(f"  FAIL     {counts['FAIL']}")
    print(f"  SKIP     {counts['SKIP']}")
    print(f"  NOT_IMPL {counts['NOT_IMPL']}")

    return 1 if counts["FAIL"] > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
