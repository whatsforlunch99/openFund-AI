# CN Fund CSV Consolidation Design

This document describes the current implementation of `python -m data_manager consolidate`.

It is intentionally based on repository code behavior only (no dependency on draft notes).

## Purpose

Consolidation reads per-fund CSV files:

- `datasets/raw/ingestion/cn_fund_all/{as_of_date}/{fund_id}/data.csv`

and produces date-level consolidated CSVs:

- `datasets/raw/ingestion/cn_fund_all/consolidated/{as_of_date}/daily.csv`
- `datasets/raw/ingestion/cn_fund_all/consolidated/{as_of_date}/static.csv`

## Output contract

- Both outputs are UTF-8 with BOM (`utf-8-sig`).
- Both are multi-table files separated by section markers:
  - `# === NAV ===`
  - `# === BASIC ===`
  - etc.
- Missing cell values are filled with marker `not_exist`.

### `daily.csv`

- Contains sections: `NAV`, `RANK`
- Keeps row-level metadata columns such as `as_of_date` and `collected_at` when present in source section rows.

### `static.csv` (Scheme C)

- Contains sections: `BASIC`, `FEE`, `HOLDINGS`, `ANNOUNCEMENTS_*`
- File-level metadata is stored in header comments:

```text
# as_of_date: 2026-03-23
# consolidated_at: 2026-03-23T12:30:29+00:00
```

- Row-level `as_of_date` and `collected_at` columns are removed from all static sections to avoid redundancy.

## Section mappings

- Daily sections:
  - `NAV` -> `nav`
  - `RANK` -> `rank`
- Static sections:
  - `BASIC` -> `basic`
  - `FEE` -> `fee`
  - `HOLDINGS` -> `holdings`
  - `ANNOUNCEMENTS_DIVIDEND` -> `announcements_dividend`
  - `ANNOUNCEMENTS_REPORT` -> `announcements_report`
  - `ANNOUNCEMENTS_PERSONNEL` -> `announcements_personnel`
  - `ANNOUNCEMENTS_DISCLOSURE_CNINFO` -> `announcements_disclosure_cninfo`

## Column behavior

- For each section, the consolidator builds a column union across all funds.
- Column order per section:
  1. preferred: `fund_id`, `as_of_date`, `collected_at` (if present)
  2. remaining columns sorted lexicographically
- For `static.csv`, `as_of_date` and `collected_at` are dropped after merging (moved to file header).

## CLI behavior

```bash
python -m data_manager consolidate --date 2026-03-23
python -m data_manager consolidate --date 2026-03-23 --output daily
python -m data_manager consolidate --date 2026-03-23 --output static
python -m data_manager consolidate --date-from 2026-03-21 --date-to 2026-03-23
python -m data_manager consolidate --date 2026-03-23 --dry-run
```

Options:

- `--output`: `daily|static|both` (default `both`)
- `--dry-run`: reports output row counts without writing files

## Idempotency and cleanup

- Running consolidation repeatedly for the same date overwrites `daily.csv`/`static.csv`.
- Legacy section-per-file CSV artifacts in the output folder are removed.

## Source of truth

- Implementation: `data_manager/consolidation.py`
- Per-fund CSV writer: `data_manager/collector.py` (`_save_cn_fund_all_csv`)
- Marker rules: `data_manager/empty_markers.py`
