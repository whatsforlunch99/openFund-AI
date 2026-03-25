# `financial_report/`

This folder contains the **SEC annual report (10‑K / 20‑F) downloader** and its generated artifacts (HTM + PDF).

## What it does
- Downloads **annual report HTML** files from SEC EDGAR for a given symbol and year range.
- Converts each downloaded `.htm` into a **PDF** (best-effort), and also downloads linked image assets so the PDF can render figures/tables.
- Uses a **symbol-level fallback**:
  - First tries **`10-K (Annual report)`**.
  - If **no 10‑K annual HTM is found for any requested year** for that symbol, it retries the same year range using **`20-F (Annual report - foreign issuer)`**.

## Key script
- `financial_report/sec_10k_downloader.py`: single-symbol downloader with 10‑K → 20‑F fallback.

## Output layout
By default, `financial_report/sec_10k_downloader.py` writes into:
- `financial_report/sec_10k_data/<SYMBOL>/<YEAR>/...`

Typical contents:
- `financial_report/sec_10k_data/<SYMBOL>/<YEAR>/*.htm` (downloaded filing document)
- `financial_report/sec_10k_data/<SYMBOL>/<YEAR>/*.pdf` (rendered PDF, when conversion succeeds)
- `financial_report/sec_10k_data/<SYMBOL>/<YEAR>/*.(jpg|png|gif|webp)` (downloaded images referenced by the HTM)

Batch/check artifacts often found here as well:
- `financial_report/sec_10k_data/sec_10k_batch_report.csv`
- `financial_report/sec_10k_data/missing_sec_10k_pdfs.txt`

## How to run

All commands below assume you run from the repo root:
- `/Users/jiani/Desktop/finance_database`

### Single symbol (dry-run: discover what would be downloaded)

```bash
python3 financial_report/sec_10k_downloader.py \
  --symbol SONY \
  --start-year 2023 --end-year 2026 \
  --output-dir financial_report/sec_10k_data \
  --dry-run
```

### Single symbol (real run: download HTM + generate PDF)

```bash
python3 financial_report/sec_10k_downloader.py \
  --symbol SONY \
  --start-year 2023 --end-year 2026 \
  --output-dir financial_report/sec_10k_data
```

### Batch run (all equity symbols from `index_symbol_map.csv`)

The batch runner lives at repo root as `sec_10k_batch_pipeline.py` and reads:
- `yahoo_data/csv_files/index_symbol_map.csv` (rows where `quoteType == equity`)

Write the batch outputs into this folder’s data dir:

```bash
python3 sec_10k_batch_pipeline.py \
  --start-year 2023 --end-year 2026 \
  --output-dir financial_report/sec_10k_data
```

### Batch run (subset)

```bash
python3 sec_10k_batch_pipeline.py \
  --start-year 2023 --end-year 2026 \
  --output-dir financial_report/sec_10k_data \
  --symbols "GILD,SONY,XOM"
```

## Output fields (what the scripts report)

`financial_report/sec_10k_downloader.py` prints one row per year and includes:
- `htm_found`: whether an exact annual-report HTM was identified in the SEC “Document Format Files” table
- `pdf_created`: whether a PDF was successfully produced
- `sec_form_used`: `10-K` or `20-F`
- `used_fallback`: `true` when the 10‑K pass found no annual HTMs for the symbol and the run switched to 20‑F
- `skip_reason`: reason for skipping/failure (e.g. no filing found, no exact HTM match, missing converter)

## Troubleshooting

- **`ticker not found in SEC map`**
  - The script resolves ticker → CIK via SEC’s `company_tickers.json`. If a symbol isn’t in that mapping (common for Yahoo-style tickers like `LVMH.PA`), you can’t crawl it by ticker alone.
  - Use a valid SEC ticker or run the downloader with an explicit `--cik` if you have it.

- **SEC 403 / 429 / transient network errors**
  - Re-run the command (the downloader retries some transient failures).
  - Consider lowering `--max-req-per-sec` to be gentler.

- **`no HTML->PDF converter available ...`**
  - The converter path is (1) `wkhtmltopdf` if installed, else (2) Playwright Chromium.
  - Install at least one of them for reliable PDFs.

