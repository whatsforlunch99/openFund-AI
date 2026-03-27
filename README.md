# finance_database

This repository contains two coordinated data pipelines:

- `database_data/`: Yahoo Finance market/fundamental collection and postprocessing.
- `financial_report/`: SEC annual report (`10-K` / `20-F`) download and PDF conversion.

Use this README as the entry point, then follow each module README for details.

## Repository structure

- `database_data/` - Yahoo crawl scripts, raw CSVs, postprocessing notebook/utilities.
- `financial_report/` - SEC filing download scripts and report artifacts.
- `graph_data/` - graph-related outputs/supporting data.
- `requirements.txt` - Python dependencies for this repo.

## Quick start

From repo root:

```bash
cd /Users/jiani/Desktop/finance_database
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Pipeline A: Yahoo market and fundamentals (`database_data/`)

Primary flow:

1. Run the interactive crawler pipeline:
   ```bash
   python3 database_data/run_yahoo_crawl_pipeline.py
   ```
2. Inspect/export postprocessed DataFrames:
   - Open and run `database_data/display_postprocessed.ipynb`.

### Outputs for Pipeline A

- Raw crawl outputs: `database_data/csv_files/`
  - examples: `index_symbol_map.csv`, `yahoo_timeseries.csv`, `yahoo_indicators.csv`, `yahoo_quote_metrics.csv`, `yahoo_key_statistics.csv`
- Final pipeline-ready outputs: `database_data/processed_csv/`
  - `index_symbol_map.csv`
  - `yahoo_fundamentals_metrics.csv`
  - `yahoo_quote_metrics.csv`
  - `yahoo_timeseries.csv`

## Pipeline B: SEC annual reports (`financial_report/`)

Single symbol:

```bash
python3 financial_report/sec_10k_downloader.py --symbol AAPL --start-year 2023 --end-year 2026
```

Batch:

```bash
python3 financial_report/sec_10k_batch_pipeline.py --start-year 2023 --end-year 2026
```

### Outputs for Pipeline B

- Final SEC artifacts: `financial_report/sec_10k_data/`
  - per-symbol/year `.htm` and `.pdf` files
  - batch report files (for example `sec_10k_batch_report.csv`)

## Recommended end-to-end run order

1. Run `database_data/run_yahoo_crawl_pipeline.py`.
2. Run `database_data/display_postprocessed.ipynb` and confirm `database_data/processed_csv/` is generated.
3. Run SEC pipeline scripts in `financial_report/` for required symbols/years.
4. Validate final outputs in:
   - `database_data/processed_csv/`
   - `financial_report/sec_10k_data/`

## Detailed documentation

- Yahoo pipeline guide: `database_data/README.md`
- SEC reports guide: `financial_report/README.md`

