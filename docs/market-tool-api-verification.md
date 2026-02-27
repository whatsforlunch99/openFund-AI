# Market tool API verification (yfinance & Alpha Vantage)

This document records how `mcp/tools/market_tool.py` and `mcp/tools/analyst_tool.py` align with official API documentation for **yfinance** and **Alpha Vantage**, including parameters and return handling.

---

## yfinance

**Docs:** [pypi yfinance](https://pypi.org/project/yfinance/), [yfinance reference](https://yfinance-python.org/reference/api/yfinance.Ticker.html), [ranaroussi.github.io/yfinance](https://ranaroussi.github.io/yfinance)

### Ticker.history(start, end)

- **Parameters:** `start`, `end` (strings YYYY-MM-DD or datetime). `end` is **exclusive** (last data point is day before end).
- **Implementation:** `get_stock_data_yf(symbol, start_date, end_date)` calls `ticker_obj.history(start=start_date, end=end_date)`. Correct. Docstring updated to note that `end_date` is exclusive per yfinance.

### Ticker.info

- **Returns:** Dict of company/fund fundamentals (longName, sector, trailingPE, etc.).
- **Implementation:** `_symbol_info(symbol)` uses `yf.Ticker(symbol.upper()).info`. Correct.

### Balance sheet / Cash flow / Income statement

- **API:** Both property-style (`balance_sheet`, `quarterly_balance_sheet`) and method-style (`get_balance_sheet(freq='quarterly')`) exist. Valid `freq`: `"annual"` / `"yearly"` or `"quarterly"`.
- **Implementation:** Uses `obj.quarterly_balance_sheet` / `obj.balance_sheet`, `obj.quarterly_cashflow` / `obj.cashflow`, `obj.quarterly_income_stmt` / `obj.income_stmt` with `freq` "quarterly" or "annual". Correct.

### Ticker.get_news(count)

- **Parameters:** `count` (int) for max number of articles.
- **Implementation:** `get_news_yf(..., limit)` calls `stock.get_news(count=limit)`. Correct.

### TLS / curl_cffi (macOS and some Linux)

- **Issue:** yfinance uses curl_cffi for TLS. On some systems (e.g. macOS with LibreSSL, or Ubuntu 24.04) you may see: `curl: (35) TLS connect error: OPENSSL_internal:invalid library` when connecting to `fc.yahoo.com`.
- **SSL verify=False:** The [Stack Overflow workaround](https://stackoverflow.com/questions/79189727/how-to-disable-or-ignore-the-ssl-for-the-yfinance-package) (e.g. `session.verify = False`) helps when the error is **certificate verification** (e.g. `CERTIFICATE_VERIFY_FAILED` behind a proxy). It does **not** fix the `OPENSSL_internal:invalid library` error, which occurs earlier in the TLS handshake inside curl_cffi’s bundled library.
- **Fix in this repo:** If yfinance raises this SSL error, the market tool **automatically falls back to Alpha Vantage** for stock data, fundamentals, balance sheet, cashflow, and income statement when `ALPHA_VANTAGE_API_KEY` is set. No code change needed.
- **Alternative:** Set `MCP_MARKET_VENDOR=alpha_vantage` so all market calls use Alpha Vantage by default.

### Mitigations tried (OPENSSL_internal:invalid library)

| Mitigation | Result on macOS (Python 3.9, LibreSSL 2.8.3) |
|------------|-----------------------------------------------|
| **1. Downgrade to yfinance 0.2.36, remove curl_cffi** | Uses `requests` instead of curl_cffi. **Still fails:** `fc.yahoo.com` returns `SSLEOFError(8, 'EOF occurred in violation of protocol')` — LibreSSL handshake fails with Yahoo. |
| **2. Remove curl_cffi only (keep newer yfinance)** | Newer yfinance requires curl_cffi; not applicable. |
| **3. Reinstall curl_cffi from source** (`pip install --no-binary curl_cffi curl_cffi`) | Build failed: curl_cffi’s build script attempted to write under `/Users/runner` (CI path), causing `PermissionError`. |
| **4. Direct requests to chart API** (bypass `fc.yahoo.com`) | `query1.finance.yahoo.com/v8/finance/chart/...` is reachable with `requests` (no TLS error) but returns **429 Too Many Requests** without cookie/crumb from `fc.yahoo.com`. |
| **5. Alpha Vantage fallback** | Works when `ALPHA_VANTAGE_API_KEY` is set; market tool uses it automatically on yfinance SSL error, or set `MCP_MARKET_VENDOR=alpha_vantage` to use it by default. |

**Recommendation for this environment:** Use **yfinance 0.2.36** without curl_cffi so that on systems where `requests` can reach `fc.yahoo.com`, yfinance works. On macOS with LibreSSL where both curl_cffi and requests fail for `fc.yahoo.com`, set `ALPHA_VANTAGE_API_KEY` (and optionally `MCP_MARKET_VENDOR=alpha_vantage`).

### Search(query, news_count, enable_fuzzy_query)

- **Parameters:** `query`, `news_count` (default 8), `enable_fuzzy_query` (default False).
- **Implementation:** `get_global_news_yf` uses `yf.Search(query=query, news_count=limit, enable_fuzzy_query=True)`. Correct.

---

## Alpha Vantage

**Docs:** [Alpha Vantage API](https://www.alphavantage.co/documentation/), [documentation.alphavantage.co](https://documentation.alphavantage.co/)

### Common

- **Base URL:** `https://www.alphavantage.co/query`. **Required:** `function`, `apikey`. **Implementation:** `_make_api_request(function_name, params)` adds `function` and `apikey`; returns response body as **string** (CSV or JSON text). Return type corrected to `str`.

### TIME_SERIES_DAILY_ADJUSTED

- **Parameters:** `symbol` (required), `outputsize` ("compact" ≤100 points or "full"), `datatype` ("csv" or "json").
- **Implementation:** `_av_stock_csv` uses `symbol`, `outputsize` ("compact" when start is &lt;100 days ago else "full"), `datatype`: "csv". Correct.

### OVERVIEW

- **Parameters:** `symbol` (required).
- **Implementation:** `get_fundamentals_av` uses `{"symbol": symbol}`. Correct.

### BALANCE_SHEET / CASH_FLOW / INCOME_STATEMENT

- **Parameters:** `symbol` (required), optional `report` ("annual" | "quarterly").
- **Implementation:** Now passes `report` when `freq` is "annual" or "quarterly" so AV returns the requested report type.

### NEWS_SENTIMENT

- **Parameters:** `tickers`, `time_from`, `time_to` (YYYYMMDDTHHMM format), optional `limit`, `topics` (for global news).
- **Implementation:** `get_news_av` uses `tickers`, `time_from`, `time_to` via `format_datetime_for_api`. `get_global_news_av` uses `topics`, `time_from`, `time_to`, `limit`. Correct.

### INSIDER_TRANSACTIONS

- **Parameters:** `symbol` (required).
- **Implementation:** `get_insider_transactions_av` uses `{"symbol": symbol}`. Correct.

### Technical indicators (analyst_tool)

- **SMA, EMA, RSI, MACD, BBANDS, ATR:** Require `symbol`, `interval`, `time_period` (where applicable), `series_type` ("close"), `datatype` ("csv").
- **Implementation:** `_av_fetch_indicator_data` passes these; VWMA is not supported by AV and returns a message to use yfinance/stockstats. Correct.

---

## Summary of code changes made

1. **market_tool._make_api_request** — Return type set to `str` (always returns `response.text`).
2. **market_tool.get_stock_data_yf** — Docstring updated: `end_date` is exclusive (last trading day is day before).
3. **market_tool.get_balance_sheet_av / get_cashflow_av / get_income_statement_av** — Pass optional `report` ("annual" | "quarterly") to Alpha Vantage when `freq` is one of these so AV returns the requested report type.

No breaking changes; behavior remains the same when `freq` is already "annual" or "quarterly".
