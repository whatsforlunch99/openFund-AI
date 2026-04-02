# CN Fund Data Schema Reference

This document describes the **China (CN) fund** data schema produced by the offline ingestion pipeline described in [data-ingestion.md](data-ingestion.md). These tables are keyed by **`fund_id`** (e.g. `000001`, kept as a string to preserve leading zeros).

> **Relationship to other docs:** The existing fund schema in [fund-data-schema.md](fund-data-schema.md) is keyed by ticker-like `symbol` (e.g. `VOO`) and represents the canonical `combined_funds.json` distribution. This document covers a separate **CN fund domain** and its `cn_fund_*` tables.

---

## Raw source layer (files)

Raw snapshots are stored as JSON envelopes for replay and debugging.

- **Path convention:** `datasets/raw/ingestion/{dataset}/{as_of_date}/{fund_id}.json`
- **Envelope fields:** `dataset`, `fund_id`, `as_of_date`, `collected_at`, `source`, `payload`

**Repo hygiene note:** This raw path is a runtime artifact and should not be committed to git. Example fixtures belong under `datasets/examples/` only.

---

## PostgreSQL schema (curated)

### Table: `cn_fund_basic`

Basic fund metadata as of a reference date.

- **Key:** `(fund_id, as_of_date)`
- **Unique constraint:** `(fund_id, as_of_date)`
- **Recommended index:** `(fund_id, as_of_date DESC)`

| Column | Type | Notes |
|--------|------|------|
| fund_id | VARCHAR(16) | string, keep leading zeros |
| fund_name | VARCHAR(256) | nullable |
| fund_type | VARCHAR(64) | e.g. 混合型/指数型/债券型 |
| risk_level | VARCHAR(32) | upstream label if available |
| inception_date | DATE | nullable |
| fund_manager | VARCHAR(256) | nullable |
| management_company | VARCHAR(256) | nullable |
| tracking_index | VARCHAR(256) | nullable |
| investment_scope | TEXT | nullable |
| latest_scale | DECIMAL(18,6) | nullable; unit must be documented by the ETL |
| description | TEXT | nullable |
| as_of_date | DATE | data reference date |
| collected_at | TIMESTAMP | collection timestamp |
| source | VARCHAR(64) | e.g. `akshare` |

### Table: `cn_fund_nav`

NAV time series.

- **Key:** `(fund_id, nav_date)`
- **Unique constraint:** `(fund_id, nav_date)`
- **Recommended index:** `(fund_id, nav_date DESC)`

| Column | Type | Notes |
|--------|------|------|
| fund_id | VARCHAR(16) | |
| nav_date | DATE | trading/NAV date |
| nav | DECIMAL(18,8) | unit NAV |
| nav_accumulated | DECIMAL(18,8) | nullable |
| collected_at | TIMESTAMP | |
| source | VARCHAR(64) | |

**Time semantics:** `nav_date` is the NAV business date. No separate `as_of_date` is stored for NAV; if upstream provides revisions/corrections for the same `nav_date`, represent that via revision metadata (e.g. `published_at`/`revision_id`) rather than a second date column.

### Table: `cn_fund_fee`

Fee schedule (normalized).

- **Key:** `(fund_id, as_of_date)`
- **Unique constraint:** `(fund_id, as_of_date)`

| Column | Type | Notes |
|--------|------|------|
| fund_id | VARCHAR(16) | |
| purchase_fee | DECIMAL(18,8) | decimal (e.g. 1.5% → 0.015) |
| redemption_fee | DECIMAL(18,8) | decimal |
| management_fee | DECIMAL(18,8) | decimal |
| custodian_fee | DECIMAL(18,8) | decimal |
| as_of_date | DATE | |
| collected_at | TIMESTAMP | |
| source | VARCHAR(64) | |

**Normalization rules:** all fee rates stored as decimals (percent values must be converted). If upstream provides tiered schedules, preserve full detail in raw snapshots (or a future detail table).

### Table: `cn_fund_holdings`

Holdings composition per report date/period.

- **Key:** `(fund_id, as_of_date, holding_code)` (or a surrogate id if upstream lacks stable codes)
- **Unique constraint:** `(fund_id, as_of_date, holding_code)`
- **Recommended index:** `(fund_id, as_of_date DESC)`

| Column | Type | Notes |
|--------|------|------|
| fund_id | VARCHAR(16) | |
| as_of_date | DATE | report date/quarter |
| holding_code | VARCHAR(32) | stock/bond identifier if present |
| holding_name | VARCHAR(256) | |
| weight | DECIMAL(10,8) | 0–1 |
| holding_type | VARCHAR(64) | equity/bond/cash/… |
| collected_at | TIMESTAMP | |
| source | VARCHAR(64) | |

**Time semantics:** `as_of_date` is the portfolio report date (often quarter-end). If upstream provides a separate publish date, keep it in raw payload (or add `published_at` later).

### Table: `cn_fund_rank`

Fund ranking/labels over different windows.

- **Key:** `(fund_id, as_of_date, rank_period)`
- **Unique constraint:** `(fund_id, as_of_date, rank_period)`

| Column | Type | Notes |
|--------|------|------|
| fund_id | VARCHAR(16) | |
| as_of_date | DATE | |
| rank_period | VARCHAR(16) | `1m`/`3m`/`1y`… |
| rank | INTEGER | lower is better |
| percentile | DECIMAL(10,6) | 0–1 if available |
| collected_at | TIMESTAMP | |
| source | VARCHAR(64) | |

---

## PostgreSQL schema (features)

### Table: `cn_fund_features`

Derived metrics computed from curated inputs.

- **Key:** `(fund_id, as_of_date)`
- **Source:** `derived`
- **Unique constraint:** `(fund_id, as_of_date)`

| Column | Type | Notes |
|--------|------|------|
| fund_id | VARCHAR(16) | |
| as_of_date | DATE | features computed “as of” this date |
| return_1d / 7d / 30d / 90d | DECIMAL(18,8) | from NAV series |
| annualized_return | DECIMAL(18,8) | optional |
| volatility | DECIMAL(18,8) | NAV return std |
| max_drawdown | DECIMAL(18,8) | negative decimal |
| sharpe | DECIMAL(18,8) | optional; uses configured/default risk-free rate |
| fee_total | DECIMAL(18,8) | derived from fee table |
| institution_ratio | DECIMAL(18,8) | optional future field |
| scale_trend | DECIMAL(18,8) | optional future field |
| collected_at | TIMESTAMP | feature generation time |
| source | VARCHAR(64) | `derived` |

### Feature conventions

- **NAV returns:** simple returns \(r_t = nav_t/nav_{t-1} - 1\); do not forward-fill missing NAV dates.
- **Sharpe:** default \(r_f = 0.0\) unless explicitly configured (e.g. `CN_RISK_FREE_RATE`).
- **Volatility window:** compute over a fixed trailing window (e.g. 30 most recent NAV observations) and document the exact window used by the job.

---

## Notes and constraints

- **Decimals:** all rates are stored as decimals (e.g. 1.5% → 0.015).
- **Identifiers:** `fund_id` is a string; never cast to int (leading zeros matter).
- **Provenance:** every curated/features row must include `as_of_date`, `collected_at`, and `source`.

### Optional: NAV revisions / corrections (NOT implemented in current version)

This schema does **not** currently model NAV revisions/corrections. `cn_fund_nav` is assumed to have a single record per `(fund_id, nav_date)`.

If revisions are needed later, implement either:

- **A (columns on `cn_fund_nav`)**: add `published_at`, `revision_id`, `is_latest`, and adjust uniqueness/query defaults, or
- **B (separate revisions table)**: keep `cn_fund_nav` as latest view, introduce `cn_fund_nav_revisions` for audit/history.

### Aggregate raw snapshot (implemented)

Offline ingestion may collect an aggregate raw snapshot via `cn_fund_tool.get_all` (task type `cn_fund_all`). The raw file still follows the same envelope fields, but `payload`/`content` contains nested sections:

- `basic` (dict)
- `nav.items` (list)
- `fee.items` (list)
- `holdings.items` (list)
- `rank.items` (list)

In the current implementation, the distributor splits this aggregate payload into curated writes for `cn_fund_basic` and `cn_fund_nav` only.

