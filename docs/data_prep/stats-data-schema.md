# Stats Data Schema (PostgreSQL)

This document defines the PostgreSQL tables loaded from CSV files in `database/stats_data` by [`scripts/data_loader.py`](../../scripts/data_loader.py). It follows a single, repeatable layout per table: source file, primary key, explicit column types aligned with the loader, semantics, and operational notes.

## Source of truth

| Item | Location |
|------|----------|
| Loader | `scripts/data_loader.py` |
| Input files | `database/stats_data/*.csv` |
| Backend | PostgreSQL (`DATABASE_URL`) |

**Schema version:** 1.1 — adds operational contract sections (loader vs documented types, NULL/percent semantics, anomalies, limitations, reproducibility, query patterns, validation queries) per [new_plan.md](new_plan.md) guidance. Loader-managed tables remain defined by CSV headers + inference. Additive CSV columns are supported without a version bump unless behavior changes; breaking loader or PK changes should bump this note and the loader together.

**Change policy:** Additive changes (new columns, new CSV files) are expected. Breaking renames or PK changes require a loader update and a version bump here.

### Documented types vs loader-enforced types

The `CREATE TABLE` sketches under [Canonical tables](#canonical-tables) are the **expected and validated types for the current repo CSVs** (column names and loader rules in [`scripts/data_loader.py`](../../scripts/data_loader.py)).

**The loader does not ship a fixed static schema file:**

- Types are **inferred dynamically** from **normalized** column names (lowercase identifiers).
- New or renamed columns may fall through to **`TEXT`** unless they match the inference rules in `_infer_sql_type`.
- The loader does **not** validate business semantics (e.g. whether a number is “really” a P/E).

| Example header (after normalization) | Inferred type | Note |
|----------------------------------------|---------------|------|
| `price` | `DOUBLE PRECISION` | Matches numeric token `price` |
| `price_usd` | `DOUBLE PRECISION` | Substring `price` matches |
| `pe_ratio` | `DOUBLE PRECISION` | Substring `pe_` matches |
| `peRatio` → `peratio` (after normalization) | `TEXT` | Does not match `pe_` token pattern |
| `rsi_14` | `DOUBLE PRECISION` | Substring `rsi` matches |
| `rsi14` | `DOUBLE PRECISION` | Substring `rsi` still matches inside `rsi14` |
| `mkt_cap_display` | `TEXT` | No `market_cap_*` numeric token match; defaults to `TEXT` unless you rename (e.g. include `market_cap` pattern or extend loader) |

**Recommendation:** Use **snake_case** and separate tokens with **`_`** (e.g. `rsi_14`, `pe_ttm`) so names align with the loader’s substring rules.

---

## Load behavior

| Mode | Behavior |
|------|----------|
| `--load-mode existing` | Creates tables if missing. Upserts rows using loader-inferred primary keys (`ON CONFLICT … DO UPDATE` when non-PK columns exist). |
| `--load-mode fresh-all` | Drops loader-managed tables for discovered CSVs, then recreates and reloads all rows. |

---

## Loader limitations

Behavior implied by [`scripts/data_loader.py`](../../scripts/data_loader.py):

| Limitation | Detail |
|------------|--------|
| No migrations | Tables are created from scratch per run when needed; existing tables are not `ALTER`’d column-by-column. |
| No semantic validation | Values are parsed/coerced by type; correctness of business meaning is not checked. |
| No foreign keys | Relationships between tables are not enforced in PostgreSQL. |
| Inference drift | Renamed CSV columns can change inferred types or fall back to `TEXT`. |

**Implication:** If CSV structure changes, **schema drift** is possible until the loader or CSV headers are updated. Treat this document plus the loader source as the contract, not only the DDL blocks below.

---

## Reproducibility

| Mode | Determinism |
|------|-------------|
| `fresh-all` | **Deterministic** for a given set of CSV files and loader version: tables are dropped and reloaded from scratch in a stable CSV discovery order. |
| `existing` | **Not strictly deterministic across runs:** upsert order and batching can affect “last write wins” for the same primary key within one load; concurrent writers outside the loader are not modeled. |

For repeatable analytics pipelines, prefer a controlled **`fresh-all`** load from pinned inputs.

---

## Identifier and type normalization

- **Table names:** From the CSV filename stem, normalized to a safe lowercase SQL identifier (`_safe_table_name`).
- **Column names:** From CSV headers, normalized to lowercase identifiers (`_quote_ident`); Postgres folds unquoted identifiers to lowercase.
- **Type inference** (`_infer_sql_type`) — applied per column name:
  - `date`, `*_date`, `*_on` → `DATE`
  - `*timestamp*` in name → `TIMESTAMP`
  - Name matches identifier-like tokens (`symbol`, `status`, `currency`, `metric_name`, …) → `TEXT`
  - Name matches numeric-ish tokens (`price`, `volume`, `percent`, `level_`, `rsi`, `macd`, …) → `DOUBLE PRECISION`
  - Default → `TEXT`

See [Documented types vs loader-enforced types](#documented-types-vs-loader-enforced-types) for edge cases and naming recommendations.

---

## Primary keys (loader)

Primary keys are inferred in `_infer_pk_columns` (not hand-written DDL elsewhere):

| Pattern in CSV headers | Primary key |
|------------------------|-------------|
| `symbol` + `timestamp` | `(symbol, timestamp)` |
| `symbol` + `date` | `(symbol, date)` |
| `symbol` + `as_of_timestamp` + `metric_group` + `metric_name` | all four |
| `symbol` + `as_of_timestamp` only | `(symbol, as_of_timestamp)` |
| `symbol` only | `(symbol)` |
| Fallback | First column |

Rows with any primary-key field empty (after trim) are **skipped**.

---

## Operational context

### Data freshness (expected)

| Table | Typical cadence |
|-------|------------------|
| `yahoo_quote_metrics` | Intraday / near–real-time quotes (per scrape) |
| `yahoo_timeseries` | Daily (end-of-day) bars and derived technicals |
| `yahoo_fundamentals_metrics` | Periodic or event-driven (fundamentals as reported) |
| `index_symbol_map` | Mapping snapshot (refresh when routing data changes) |

### Timezone

- **`timestamp` columns:** Stored as PostgreSQL `TIMESTAMP` from parsed ISO-like strings; treat as **UTC** for consistency unless your upstream documents otherwise.
- **`date` columns:** Calendar `DATE` (no timezone).

### Enumerations (examples only)

String fields such as `status`, `quotetype`, and `source` come from upstream data. **There is no fixed enum enforced in the database.** Typical values may resemble:

- **`status`:** scrape or row status strings (e.g. success / error style values — varies by pipeline).
- **`quotetype`:** issuer or instrument classifications from the resolver (e.g. equity vs ETF style labels — exact strings depend on source).
- **`source` / `metric_source`:** vendor or lane labels (e.g. yahoo-style tags).

Confirm distinct values with `SELECT DISTINCT …` on your loaded data when you need a closed set.

---

## Percentage and ratio fields

Columns whose names include `*_percent` (e.g. `change_percent`, `forward_yield_percent`) are stored as **`DOUBLE PRECISION`**. **Convention for this project’s Yahoo-style stats pipeline:**

- Treat values as **percentage points** unless your upstream documents otherwise: e.g. **`3.5` means 3.5%**, not `0.035`.
- If a given scrape instead uses fractions (0.035), that is a **data-quality issue**—the loader does not normalize percent vs fraction; consumers should validate against source documentation or `source_url`.

Other ratio fields without `_percent` in the name may still be ratios (0–1) or scales; interpret using column name and upstream meaning.

---

## Data quality and loader rules

- **`--` or empty** after trim → stored as `NULL` (via `_parse_value` / text handling).
- **Numeric shorthand** (`3.7T`, `51.8B`, `1.2M`, `k`): parsed to `DOUBLE PRECISION` when the column type is numeric; **malformed** numerics become **`NULL`** (not coerced to 0).
- **Missing primary key:** row skipped.
- **Duplicate primary keys:** last upsert wins for SQL paths that use `ON CONFLICT DO UPDATE` (non-PK columns only in `SET`).

### NULL semantics

`NULL` can mean:

- Missing source data (`--`, blank cells).
- Failed parse (invalid date, bad numeric shorthand).
- Metric not applicable for that row/period.

**Analytics rules:**

- **`NULL` ≠ `0`.** Do not treat NULL as zero in aggregations without an explicit policy.
- The loader **does not impute** missing values.

**Example:** `price IS NULL` → no usable price for that row; `price = 0` → rare but would be a literal zero if present in source.

---

## Field classification rules

| Rule | Description |
|------|-------------|
| **Raw** | Values as in the source export (strings allowed). Must not be overwritten by the loader with computed numbers. |
| **Parsed** | Normalized numeric (or typed) fields; **should** pair with a raw or source column when both exist (e.g. `market_cap_intraday` raw string + `market_cap_intraday_parsed`). |
| **Derived** | Computed from other fields or series (e.g. technicals on `yahoo_timeseries`); must **not** replace raw OHLC columns. |

**Valid pattern:** `market_cap_intraday` = `"1.2T"` (raw TEXT), `market_cap_intraday_parsed` = `1.2e12` (parsed).

**Invalid pattern:** Storing a numeric in a column documented as raw display string without renaming the column.

---

## Known data anomalies

Real-world Yahoo and resolver data can be messy. Consumers should handle defensively:

| Area | Quirk |
|------|--------|
| `earnings_date_est` | May be a single date, a **range string** in source (e.g. multi-day window), or unparseable → stored as **`NULL`** if the loader cannot parse a single `DATE`. |
| `market_cap`, `market_cap_intraday` | May include **currency symbols**, **suffixes** (T, B, M), commas—preserved in TEXT until parsed. |
| Technicals (`ma_*`, `rsi_*`, `macd*`, etc.) | Often **`NULL` for early dates** when the lookback window is insufficient. |
| `metric_value` (EAV) | Units and scale vary by `metric_name`; see [EAV value interpretation](#eav-value-interpretation). |

---

## EAV model (`yahoo_fundamentals_metrics`)

Fundamentals are stored as **entity–attribute–value** rows:

- **Entity:** `symbol` + `as_of_timestamp` (+ `metric_group` for grouping).
- **Attribute:** `metric_name` (and `metric_group`).
- **Value:** `metric_value` — stored as **`DOUBLE PRECISION`** when the column name matches loader numeric rules.

Implications: wide “one row per symbol” reports require pivoting or aggregation in SQL; no migration is needed to add new metric names.

### EAV value interpretation

`metric_value` is typed as double precision in PostgreSQL, but **meaning is defined by `metric_name` (and group)**:

- Some rows are **absolute magnitudes** (e.g. revenue in currency units).
- Some are **ratios or margins** (0–1 or 0–100 depending on source).
- Some are **percent-style** metrics where the scale must be read from the metric label or upstream docs.

**Rule:** Always interpret `metric_value` **together with `metric_name` and `metric_group`** (and `as_of_timestamp`). Do not assume one global unit for all rows.

---

## Indexing guidance (optional)

The loader does **not** create indexes. Without them, large tables tend toward **sequential scans** for symbol/time filters.

| Use case | Suggested index | Rationale |
|----------|-----------------|-----------|
| Latest row per symbol, time-ordered history | `(symbol, timestamp DESC)` on `yahoo_quote_metrics` | Speeds `WHERE symbol = … ORDER BY timestamp` and helps `DISTINCT ON (symbol) … ORDER BY symbol, timestamp DESC`. |
| Daily bars, technicals | `(symbol, date DESC)` on `yahoo_timeseries` | Same pattern for date-based series. |
| Fundamentals by symbol and as-of | `(symbol, as_of_timestamp)` on `yahoo_fundamentals_metrics` | Filters EAV rows before sort. |

```sql
CREATE INDEX IF NOT EXISTS idx_yahoo_quote_symbol_ts
  ON yahoo_quote_metrics (symbol, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_yahoo_timeseries_symbol_date
  ON yahoo_timeseries (symbol, date DESC);

CREATE INDEX IF NOT EXISTS idx_fundamentals_symbol_time
  ON yahoo_fundamentals_metrics (symbol, as_of_timestamp);
```

---

## Common query patterns

### Latest snapshot per symbol

```sql
SELECT DISTINCT ON (symbol)
  symbol, price, timestamp
FROM yahoo_quote_metrics
ORDER BY symbol, timestamp DESC;
```

### Time series (single symbol)

```sql
SELECT date, rsi_14
FROM yahoo_timeseries
WHERE symbol = 'AAPL'
ORDER BY date;
```

### Cross-section at one timestamp

```sql
SELECT symbol, price
FROM yahoo_quote_metrics
WHERE timestamp = (
  SELECT MAX(timestamp) FROM yahoo_quote_metrics
);
```

*(Adjust if you need per-symbol latest instead of a single global timestamp.)*

### Fundamentals long format (no extension required)

```sql
SELECT metric_group, metric_name, metric_value
FROM yahoo_fundamentals_metrics
WHERE symbol = 'AAPL'
ORDER BY as_of_timestamp DESC, metric_group, metric_name;
```

### Fundamentals pivot (wide columns)

Use **conditional aggregation** or PostgreSQL **`crosstab`** (`tablefunc` extension). Units still vary by metric—see [EAV value interpretation](#eav-value-interpretation).

---

## Minimal validation queries

After a load, sanity-check data quality (expect **zero rows** where noted).

**Null PK components (should not occur on loaded rows; loader skips bad rows, so this is a post-load integrity check)**

```sql
SELECT * FROM yahoo_quote_metrics
WHERE symbol IS NULL OR timestamp IS NULL;
```

**Duplicate primary keys (should be zero)**

```sql
SELECT symbol, timestamp, COUNT(*) AS n
FROM yahoo_quote_metrics
GROUP BY symbol, timestamp
HAVING COUNT(*) > 1;
```

Repeat the same pattern for other tables using their respective PK columns.

---

## Canonical tables

### Table: `yahoo_quote_metrics`

**Source CSV:** `database/stats_data/yahoo_quote_metrics.csv`  
**Primary key:** `(symbol, timestamp)`

#### SQL schema (loader-aligned)

Illustrative `CREATE TABLE` matching `_infer_sql_type` for these column names. The loader uses `CREATE TABLE IF NOT EXISTS` with these types; only PK columns are non-null in practice for loaded rows.

```sql
CREATE TABLE yahoo_quote_metrics (
  symbol TEXT NOT NULL,
  timestamp TIMESTAMP NOT NULL,
  price DOUBLE PRECISION,
  change DOUBLE PRECISION,
  change_percent DOUBLE PRECISION,
  prev_close DOUBLE PRECISION,
  open DOUBLE PRECISION,
  volume DOUBLE PRECISION,
  avg_volume DOUBLE PRECISION,
  market_cap TEXT,
  market_cap_intraday TEXT,
  beta_5y_monthly DOUBLE PRECISION,
  pe_ttm DOUBLE PRECISION,
  eps_ttm DOUBLE PRECISION,
  earnings_date_est DATE,
  ex_dividend_date DATE,
  target_est_1y DOUBLE PRECISION,
  currency TEXT,
  source_url TEXT,
  status TEXT,
  day_low DOUBLE PRECISION,
  day_high DOUBLE PRECISION,
  week_52_low DOUBLE PRECISION,
  week_52_high DOUBLE PRECISION,
  bid_price DOUBLE PRECISION,
  bid_size DOUBLE PRECISION,
  ask_price DOUBLE PRECISION,
  ask_size DOUBLE PRECISION,
  forward_dividend DOUBLE PRECISION,
  forward_yield_percent DOUBLE PRECISION,
  market_cap_intraday_parsed DOUBLE PRECISION,
  PRIMARY KEY (symbol, timestamp)
);
```

#### Column definitions

| Column | Type | Semantics |
|--------|------|-----------|
| `symbol` | TEXT | Ticker / listing identifier (PK part). |
| `timestamp` | TIMESTAMP | Quote time (PK part); align with UTC policy above. |
| `price` | DOUBLE PRECISION | Last or current price; units follow `currency`. |
| `change`, `change_percent` | DOUBLE PRECISION | Change vs prior close; see [Percentage and ratio fields](#percentage-and-ratio-fields) for `*_percent` convention. |
| `prev_close`, `open` | DOUBLE PRECISION | Price levels. |
| `volume`, `avg_volume` | DOUBLE PRECISION | Share volume. |
| `market_cap` | TEXT | Raw display string from source (may include suffixes). |
| `market_cap_intraday` | TEXT | Raw intraday market-cap string. |
| `market_cap_intraday_parsed` | DOUBLE PRECISION | Parsed numeric (e.g. after T/B suffix handling). |
| `beta_5y_monthly`, `pe_ttm`, `eps_ttm` | DOUBLE PRECISION | Risk / valuation metrics. |
| `earnings_date_est`, `ex_dividend_date` | DATE | Corporate action dates. |
| `target_est_1y` | DOUBLE PRECISION | Price target. |
| `currency` | TEXT | Quote currency code. |
| `source_url`, `status` | TEXT | Provenance / row status. |
| `day_low`, `day_high`, `week_52_low`, `week_52_high` | DOUBLE PRECISION | Price ranges. |
| `bid_price`, `bid_size`, `ask_price`, `ask_size` | DOUBLE PRECISION | NBBO-style fields when present. |
| `forward_dividend`, `forward_yield_percent` | DOUBLE PRECISION | Dividend metrics. |

#### Field classification

See [Field classification rules](#field-classification-rules). For this table: **raw** display strings (`market_cap`, `market_cap_intraday`); **parsed** `market_cap_intraday_parsed`; other numeric quote fields are typically **raw** from the feed unless your pipeline marks them otherwise.

#### Notes

- Empty PK fields cause the row to be dropped at load time.

---

### Table: `yahoo_fundamentals_metrics`

**Source CSV:** `database/stats_data/yahoo_fundamentals_metrics.csv`  
**Primary key:** `(symbol, as_of_timestamp, metric_group, metric_name)`

#### SQL schema (loader-aligned)

```sql
CREATE TABLE yahoo_fundamentals_metrics (
  symbol TEXT NOT NULL,
  as_of_timestamp TIMESTAMP NOT NULL,
  metric_source TEXT,
  metric_group TEXT,
  metric_name TEXT NOT NULL,
  metric_value DOUBLE PRECISION,
  source_url TEXT,
  status TEXT,
  PRIMARY KEY (symbol, as_of_timestamp, metric_group, metric_name)
);
```

#### Column definitions

| Column | Type | Semantics |
|--------|------|-----------|
| `symbol` | TEXT | Entity (PK part). |
| `as_of_timestamp` | TIMESTAMP | As-of time for the metric row (column name contains `timestamp` → `TIMESTAMP` in loader). |
| `metric_source` | TEXT | Upstream lane or vendor label. |
| `metric_group` | TEXT | Grouping for EAV rows (PK part). |
| `metric_name` | TEXT | Metric key (PK part). |
| `metric_value` | DOUBLE PRECISION | Numeric value (may need scale interpretation per metric). |
| `source_url` | TEXT | Provenance URL. |
| `status` | TEXT | Row/status string. |

#### Notes

- EAV shape: see [EAV model](#eav-model-yahoo_fundamentals_metrics) above.

---

### Table: `yahoo_timeseries`

**Source CSV:** `database/stats_data/yahoo_timeseries.csv`  
**Primary key:** `(symbol, date)`

#### SQL schema (loader-aligned)

```sql
CREATE TABLE yahoo_timeseries (
  symbol TEXT NOT NULL,
  date DATE NOT NULL,
  level_open DOUBLE PRECISION,
  level_high DOUBLE PRECISION,
  level_low DOUBLE PRECISION,
  level_close DOUBLE PRECISION,
  total_return_level DOUBLE PRECISION,
  ma_50 DOUBLE PRECISION,
  ma_200 DOUBLE PRECISION,
  rsi_14 DOUBLE PRECISION,
  macd DOUBLE PRECISION,
  macd_signal DOUBLE PRECISION,
  macd_hist DOUBLE PRECISION,
  bb_upper DOUBLE PRECISION,
  bb_mid DOUBLE PRECISION,
  bb_lower DOUBLE PRECISION,
  stoch_k DOUBLE PRECISION,
  stoch_d DOUBLE PRECISION,
  source_url TEXT,
  source TEXT,
  technical_source_url TEXT,
  PRIMARY KEY (symbol, date)
);
```

#### Column definitions

| Column | Type | Semantics |
|--------|------|-----------|
| `symbol` | TEXT | Ticker (PK part). |
| `date` | DATE | Trading date (PK part). |
| `level_open`, `level_high`, `level_low`, `level_close` | DOUBLE PRECISION | OHLC levels. |
| `total_return_level` | DOUBLE PRECISION | Total-return index level when present. |
| `ma_50`, `ma_200` | DOUBLE PRECISION | Moving averages. |
| `rsi_14` | DOUBLE PRECISION | RSI (typical range 0–100). |
| `macd`, `macd_signal`, `macd_hist` | DOUBLE PRECISION | MACD stack. |
| `bb_upper`, `bb_mid`, `bb_lower` | DOUBLE PRECISION | Bollinger bands. |
| `stoch_k`, `stoch_d` | DOUBLE PRECISION | Stochastic oscillator. |
| `source_url` | TEXT | Data URL. |
| `source` | TEXT | Lane / vendor tag. |
| `technical_source_url` | TEXT | Technical series provenance. |

#### Field classification

- **Raw:** OHLC levels from source.
- **Derived:** Moving averages, RSI, MACD, Bollinger, stochastics.

---

### Table: `index_symbol_map`

**Source CSV:** `database/stats_data/index_symbol_map.csv`  
**Primary key:** `(symbol)`

#### SQL schema (loader-aligned)

```sql
CREATE TABLE index_symbol_map (
  symbol TEXT NOT NULL,
  index_id TEXT,
  confidence DOUBLE PRECISION,
  quotetype TEXT,
  matched_name TEXT,
  source_url TEXT,
  PRIMARY KEY (symbol)
);
```

#### Column definitions

| Column | Type | Semantics |
|--------|------|-----------|
| `symbol` | TEXT | Mapped symbol (PK). |
| `index_id` | TEXT | Index or benchmark identifier string. |
| `confidence` | DOUBLE PRECISION | Match confidence score. |
| `quotetype` | TEXT | Instrument/type hint from resolver (see [Enumerations](#enumerations-examples-only)). |
| `matched_name` | TEXT | Human-readable name. |
| `source_url` | TEXT | Provenance URL. |

---

## Document history

| Version | Notes |
|---------|--------|
| 1.1 | Operational contract: documented vs inferred types, inference edge cases, NULL and percent semantics, enforceable field rules, known anomalies, EAV value interpretation, loader limitations, reproducibility, index rationale, query patterns, validation SQL ([new_plan.md](new_plan.md)). |
| 1.0 | Standardized layout: explicit DDL aligned with `data_loader.py`, semantics, EAV section, optional indexes, examples, versioning note. |
