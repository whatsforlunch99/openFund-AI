# Yahoo Data Project Guide

This folder contains your Yahoo Finance crawl pipeline, raw CSV outputs, and postprocessing utilities.
Use this README as the source of truth for:

- what each file does,
- what each dataset means,
- and how to collect all required data when you add new symbols.

## End-to-end flow

1. Build/refresh symbol mapping (`index_id` -> `yahoo_symbol`) in `index_symbol_map.csv`.
2. Crawl chart + quoteSummary API data into:
   - `yahoo_timeseries.csv`
   - `yahoo_indicators.csv`
   - `yahoo_crawl_log.csv`
3. Crawl quote page metrics into `yahoo_quote_metrics.csv`.
4. Crawl key statistics pages (equity symbols only) into `yahoo_key_statistics.csv`.
5. Dedupe, check completeness, then load postprocessed views in notebook/code.

## Main scripts and what they write

- `yahoo_crawler.py`
  - Primary API crawler.
  - Writes `index_symbol_map.csv`, `yahoo_timeseries.csv`, `yahoo_indicators.csv`, `yahoo_crawl_log.csv`.
- `yahoo_quote_pages.py`
  - Quote page scraper.
  - Writes `yahoo_quote_metrics.csv`.
- `yahoo_key_statistics_pages.py`
  - Key statistics page scraper.
  - Writes `yahoo_key_statistics.csv`.
  - Equity only (not for index/fund symbols).
- `run_yahoo_crawl_pipeline.py`
  - One-liner interactive pipeline.
  - Prompts for symbols first, then cookie, runs crawlers, then runs completeness auto-fix.
- `check_symbol_completeness_and_fix.py`
  - Audits missing symbols across CSVs and can run fixing crawls with `--run`.
- `dedupe_yahoo_csvs.py`
  - Removes duplicate rows from output CSVs.
- `yahoo_csv_postprocess.py`
  - Converts raw CSVs into typed pandas views, including merged fundamentals output.
- `display_postprocessed.ipynb`
  - Notebook to inspect postprocessed outputs quickly and export final files to `processed_csv/`.

## Data files (raw + postprocessed)

### Raw crawl outputs (`csv_files/`)

#### `index_symbol_map.csv`
Maps your internal `index_id` to Yahoo symbol + metadata.

Key columns:
- `index_id`: your canonical symbol ID used by `yahoo_crawler.py`.
- `yahoo_symbol`: Yahoo symbol resolved from search results.
- `quoteType`: Yahoo type (for example `EQUITY`, `INDEX`, `ETF`).
- `confidence`: matching confidence score.
- `matched_name`: matched Yahoo instrument name.
- `source_url`: search URL used to resolve mapping.

#### `yahoo_timeseries.csv`
Canonical OHLC + technical indicators by `index_id` and `date`.

Key columns:
- identity/provenance: `index_id`, `date`, `source`, `source_url`, `technical_source_url`
- OHLC: `level_open`, `level_high`, `level_low`, `level_close`
- additional level: `total_return_level` (often empty for Yahoo chart data)
- technicals: `ma_50`, `ma_200`, `rsi_14`, `macd`, `macd_signal`, `macd_hist`, `bb_upper`, `bb_mid`, `bb_lower`, `stoch_k`, `stoch_d`

Notes:
- Early rows can have empty technical values due to lookback windows.

#### `yahoo_indicators.csv`
Long-form quoteSummary indicators (valuation/fundamental/analyst/profile style metrics).

Key columns:
- `index_id`, `yahoo_symbol`
- `indicator_group` (metric family)
- `indicator_name` (metric key)
- `indicator_value` (string/raw value)
- `as_of_date`
- `source_url`

#### `yahoo_quote_metrics.csv`
Point-in-time quote page metrics by symbol and timestamp.

Key columns:
- identity/provenance: `symbol`, `as_of_timestamp`, `source_url`, `status`
- market fields: `price`, `change`, `change_percent`, `prev_close`, `open`
- range/volume: `day_range`, `week_52_range`, `volume`, `avg_volume`
- valuation/other: `market_cap`, `market_cap_intraday`, `beta_5y_monthly`, `pe_ttm`, `eps_ttm`, `target_est_1y`
- microstructure/payout/date: `bid`, `ask`, `forward_dividend_yield`, `ex_dividend_date`, `earnings_date_est`, `currency`

#### `yahoo_key_statistics.csv`
Raw key-statistics scrape payloads by symbol and timestamp.

Key columns:
- `symbol`
- `as_of_timestamp`
- `key_statistics_json` (raw JSON payload string)
- `source_url`
- `status` (`ok` / `parse_error` etc.)

Important:
- This dataset is only meaningful for equity symbols.

#### `yahoo_crawl_log.csv`
Request log for Yahoo API calls.

Key columns:
- `timestamp`
- `url`
- `status`
- `reason`
- `crumb`

#### `yahoo_failed_requests.csv`
Tracks failed quote/key-stats page fetches.

Key columns:
- `timestamp`, `crawler`, `symbol`, `url`, `status`

### Postprocessed views (`yahoo_csv_postprocess.py`)

- `postprocess_yahoo_timeseries()`: typed OHLC/technical time series.
- `postprocess_yahoo_indicators()`: long indicator table.
- `postprocess_yahoo_quote_metrics()`: parsed/scaled quote metrics.
- `postprocess_yahoo_key_statistics()`: flattened key stats metrics.
- `postprocess_yahoo_fundamentals_metrics()`: merged long fundamentals view combining:
  - indicators (`yahoo_indicators.csv`)
  - key statistics (`yahoo_key_statistics.csv`)

Final pipeline-ready data files are written under `processed_csv/` by `display_postprocessed.ipynb`:
- `processed_csv/index_symbol_map.csv`
- `processed_csv/yahoo_fundamentals_metrics.csv`
- `processed_csv/yahoo_quote_metrics.csv`
- `processed_csv/yahoo_timeseries.csv`

## When you add a new symbol: exact runbook

### 0) First step (required)

Confirm the symbol is mappable in `index_symbol_map.csv`:
- symbol should exist either as `index_id` or `yahoo_symbol`,
- and it must resolve to a valid `index_id -> yahoo_symbol` mapping.

If symbol is not mapped yet, run `yahoo_crawler.py` once for that symbol to populate mapping.

### 1) One-liner interactive pipeline (recommended)

Run:

```bash
python3 yahoo_data/run_yahoo_crawl_pipeline.py
```

You will be prompted for:
1. symbol list (required; empty input aborts),
2. cookie value (used for `YAHOO_A1`, `YAHOO_A1S`, `YAHOO_A3` automatically).

Accepted symbol input:
- comma list: `^IXIC,SPY,MSFT`
- JSON array: `["^IXIC","SPY","MSFT"]`
- mixed `index_id` + Yahoo symbol is supported (auto-detected).

What this one command does automatically:
1. runs key statistics crawl for resolved equity symbols,
2. runs `yahoo_crawler.py` for resolved `index_id`s,
3. runs `yahoo_quote_pages.py` for resolved `index_id`s,
4. runs completeness repair: `check_symbol_completeness_and_fix.py --run`,
5. runs CSV dedupe: `dedupe_yahoo_csvs.py`.

Progress output is now stage-based and readable:
- `[STAGE 1/5] Crawling key statistics pages...`
- `[STAGE 2/5] Crawling chart + indicators...`
- `[STAGE 3/5] Crawling quote metrics pages...`
- `[STAGE 4/5] Running completeness check...`
- `[STAGE 5/5] Deduplicating output CSVs...`
- final compact summary line:
  - `[SUMMARY] Missing counts -> timeseries:X, indicators:Y, quote_metrics:Z, key_statistics_equity:K`

Optional flags:

```bash
python3 yahoo_data/run_yahoo_crawl_pipeline.py --chunk-size 40
python3 yahoo_data/run_yahoo_crawl_pipeline.py --symbols '^IXIC,AAPL' --dry-run
```

Example output shape:

```text
[PIPELINE] Starting interactive Yahoo crawl pipeline
[PIPELINE] Resolved 2 index_id symbol(s) for crawler/quote.
[PIPELINE] Resolved 1 equity Yahoo symbol(s) for key statistics.
[STAGE 1/5] Crawling key statistics pages...
[CHUNK] crawling key statistics chunk 1/1 symbols=1 [AAPL] -> yahoo_key_statistics_pages.py
...
[STAGE 4/5] Running completeness check...
[SUMMARY] Missing counts -> timeseries:0, indicators:0, quote_metrics:0, key_statistics_equity:0
[STAGE 5/5] Deduplicating output CSVs...
[PIPELINE] Completed: crawl + completeness repair + dedupe finished.
```

### 2B) Component-by-component (manual control)

From project root:

```bash
python3 yahoo_data/yahoo_crawler.py --symbols '^IXIC,SPY,MSFT'
python3 yahoo_data/yahoo_quote_pages.py --symbols '^IXIC,SPY,MSFT'
python3 yahoo_data/yahoo_key_statistics_pages.py --symbols 'MSFT,AAPL,TSM'
```

Notes:
- `yahoo_key_statistics_pages.py` should be run only for equity symbols.
- `yahoo_quote_pages.py` and key stats scripts use Yahoo page scraping via shared `yahoo_quote_core.py`.

### 3) Repair any gaps automatically (standalone)

```bash
python3 yahoo_data/check_symbol_completeness_and_fix.py --run --chunk-size 25
```

This checks all symbols in `index_symbol_map.csv` and runs the appropriate crawler for missing data. The interactive pipeline already does this at the end.

### 4) Cleanup duplicates

```bash
python3 yahoo_data/dedupe_yahoo_csvs.py
```

### 5) Validate outputs

- Re-run completeness checker without `--run`:
  ```bash
  python3 yahoo_data/check_symbol_completeness_and_fix.py
  ```
- Run/open `display_postprocessed.ipynb` to generate and inspect postprocessed outputs.
- Confirm final exported files exist in `processed_csv/`:
  - `processed_csv/index_symbol_map.csv`
  - `processed_csv/yahoo_fundamentals_metrics.csv`
  - `processed_csv/yahoo_quote_metrics.csv`
  - `processed_csv/yahoo_timeseries.csv`
- Optionally quick-import in Python:
  ```bash
  python3 -c "from yahoo_data.yahoo_csv_postprocess import postprocess_yahoo_fundamentals_metrics as f; print(f().shape)"
  ```

## Common gotchas

- Key statistics is equity-only; non-equity symbols can return empty/invalid rows.
- `parse_error` in page-based CSVs means request succeeded but parser found no usable data.
- `yahoo_crawl_log.csv` records URLs/status and helps debug crumb/auth issues.
- If a CSV is malformed from interrupted appends, repair file integrity before postprocessing.

## Optional input file

`index_master.csv` can exist as a seed/source list, but pipeline execution can proceed without it if `index_symbol_map.csv` is already maintained.

---

## SEC 10-K Equity Pipeline

The repository also includes a separate SEC pipeline to collect annual report filings (`10-K (Annual report)`) as HTM and PDF for equity symbols.

### Scripts

- `sec_10k_downloader.py`
  - Single-symbol SEC downloader.
  - Resolves ticker to CIK (or uses `--cik` override), downloads exact HTM filing, downloads linked image assets, and converts to PDF.
- `sec_10k_batch_pipeline.py`
  - Batch runner for all equity symbols from `yahoo_data/csv_files/index_symbol_map.csv`.
  - Continues on errors and writes consolidated report.

### One-symbol usage

```bash
python3 sec_10k_downloader.py --symbol AAPL --start-year 2023 --end-year 2026
```

Optional:

```bash
python3 sec_10k_downloader.py --symbol AAPL --cik 0000320193 --dry-run
```

### Batch usage (all equities)

```bash
python3 sec_10k_batch_pipeline.py --start-year 2023 --end-year 2026
```

Subset run:

```bash
python3 sec_10k_batch_pipeline.py --symbols "AAPL,MSFT,ASML" --start-year 2023 --end-year 2026
```

### SEC output layout

- HTM/PDF files:
  - `sec_10k/<SYMBOL>/<YEAR>/<filing>.htm`
  - `sec_10k/<SYMBOL>/<YEAR>/<filing>.pdf`
- Batch report:
  - `sec_10k/sec_10k_batch_report.csv`
  - columns: `symbol`, `year`, `filing_date`, `accession`, `htm_found`, `htm_path`, `pdf_created`, `pdf_path`, `skip_reason`

### Batch status meaning

- `ok`: at least one year produced HTM + PDF
- `partial`: HTM found but no PDF (or mixed year results)
- `skipped`: symbol unavailable in SEC mapping or no matching annual filing
