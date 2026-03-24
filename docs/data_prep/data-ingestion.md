# Data Ingestion Design (AKShare → Data Assets)

This document specifies the **offline data ingestion** module design for fund data. It turns AKShare (and similar unstable upstreams) into **durable internal data assets** (raw + curated + features) that the rest of the system queries via PostgreSQL / Neo4j / Milvus (through MCP tools).

> **Why this exists:** Do **not** treat AKShare as a real-time API for the chat path. Use it as a **batch ingestion source** so the agent layer depends on stable internal storage, not third‑party availability/latency/limits.

---

## Scope

### In scope

- **Offline ingestion** of fund datasets (primarily CN mutual funds/ETFs identified by `fund_id` like `000001`).
- **Layered storage**:
  - **Raw**: append-only snapshots of upstream responses.
  - **Curated**: normalized tables with stable schema and constraints.
  - **Features**: derived metrics (returns, volatility, max drawdown, sharpe, fee rollups, behavior signals).
- **Scheduling**: daily/weekly/quarterly jobs with per-dataset cadence.
- **Idempotency + traceability**: upserts keyed by `(fund_id, as_of_date)` and `collected_at`, `source`.
- **Integration boundary**: ingestion runs via `data_manager` (CLI/scheduler), not via WebSearcher’s real-time path.

### Out of scope (for this module)

- Real-time “fetch on every user query” AKShare calls.
- Model training / RL / LTR (may consume the features later).
- Full portfolio optimization and backtesting engine (separate module).

---

## Design goals

- **Reliability first**: upstream instability must not affect query-time UX.
- **Simple + reviewable**: minimal moving parts; explicit schemas and job definitions.
- **Deterministic outputs**: same inputs produce the same curated rows (idempotent writes).
- **Traceable provenance**: every row has `source`, `as_of_date`, `collected_at`.

---

## Architecture overview

Ingestion runs as a background pipeline:

```
AKShare (upstream)
   ↓
Raw snapshots (files)           ← retry / throttling / fallback live here
   ↓
Curated tables (PostgreSQL)     ← stable query interface
   ↓
Feature tables (PostgreSQL)     ← ranking, filtering, and explanations
   ↓
Optional: Graph (Neo4j) & Vector (Milvus)
```

### Invocation (aligned with current repo)

Ingestion should be wired into the existing `data_manager` background workflow style rather than introducing a parallel CLI surface.

- **Collect (raw snapshots):** `python -m data_manager collect ...` (AKShare is called only inside the collector layer; never from the real-time chat path)
- **Distribute (curated writes):** `python -m data_manager distribute ...` (writes to PostgreSQL/Neo4j/Milvus via MCP tools)
- **(Optional) Features:** `python -m data_manager features ...` (derived metrics written to PostgreSQL via MCP tools)

> If a single `ingest` subcommand is added later, it must remain a thin wrapper around the above commands (collect → distribute → features), not a second independent ingestion interface.

---

## Upstream data sources

This module treats upstreams as **best-effort** producers. Each dataset has:
- a **collector** (calls upstream and writes raw snapshots)
- a **transformer** (normalizes to curated schema)
- a **distributor** (writes to Postgres/Neo4j/Milvus via MCP tools)

### Recommended datasets (from the raw idea)

- **Fund list / basic info**
  - Example upstream functions (prefer EM/Tiantianfund): `ak.fund_name_em()`
  - Optional supplements (version-dependent): `ak.fund_individual_basic_info_*` (EM) / `ak.fund_individual_*_xq` (XQ; unstable)
- **NAV and returns**
  - Example: `ak.fund_open_fund_info_em(symbol=...)` (history)
  - Latest snapshot (bulk table): `ak.fund_open_fund_daily_em()` (use cautiously; very large)
- **Fees**
  - Example: `ak.fund_fee_em(symbol=...)`
- **Holdings / portfolio**
  - Example: `ak.fund_portfolio_hold_em()`
- **Rank / labels**
  - Example (bulk table): `ak.fund_open_fund_rank_em()` (filter locally; refuse bulk if cannot filter)

> Implementation detail: upstream calls should be encapsulated in the collector layer; the rest of the system never imports AKShare directly.

### Stable-source priority (recommended)

AKShare is an **aggregator** (EM / Tiantianfund / XQ / etc.). For production-style ingestion, prefer these priorities:

| Data type | Primary (stable) | Secondary (supplement) | Fallback (unstable) |
|----------|-------------------|-------------------------|---------------------|
| **Basic name/type** | `fund_name_em` (EM) | `fund_manager_em`, `fund_individual_basic_info_xq` (enrich nulls) | – |
| **NAV history** | ETF: `fund_etf_fund_info_em`; open-end: `fund_open_fund_info_em` | open-end: `indicator=累计净值走势` when 累计净值 missing | – |
| **Fees** | `fund_fee_em` (tries 申购费率, 赎回费率, 运作费用) | – | – |
| **Holdings** | `fund_portfolio_hold_em(symbol=...)` (EM; may still be partial) | bond/industry allocation endpoints | – |
| **Rank** | `fund_open_fund_rank_em` (EM bulk) | – | – |

This repo’s ingestion tools implement these priorities and add safeguards:

- **XQ enriches basic** when fund_name_em has name/type but risk_level, inception_date, tracking_index, etc. are null.
- **Bulk endpoints are not written unfiltered** into single-fund snapshots; if we cannot reliably filter to the requested `fund_id`, we return `error` for that section.
- **Rule-based basic enrichment (implemented for offline CN ingestion):** after EM/XQ attempts, when metadata fields are still missing, we apply deterministic inference to reduce null rate:
  - `risk_level`: infer from `fund_type` substring mapping (e.g. `货币型`→`低`, `债券型`→`低-中`, `混合型`→`中`, `股票型`/`指数型-股票`→`高`, `QDII`→`高`).
  - `tracking_index`: extract from `fund_name` keywords for common index/theme ETF-like names (e.g. `沪深300`/`中证500`/`创业板`/`有色金属`→`有色金属指数`); if `ETF` is detected but no keyword hits, fall back to `未知指数ETF`.
  - `investment_scope`: infer from `fund_type` (e.g. `债券`→`债券为主`, `股票`→`股票为主`, `混合型`→`股债混合`).
  - `latest_scale`: if still null and AKShare `fund_scale_change_em` is available, take the latest record’s scale-like field (`最新规模`/`规模`/`基金规模`) as `latest_scale`; otherwise keep null.
  - If inference fails, we keep explicit nulls (no silent drops).

### Optional: one-call aggregate ingestion (implemented)

For offline ingestion convenience, the MCP layer provides an **aggregate tool**:

- `cn_fund_tool.get_all` — fetches a fund’s basic info + NAV + fee + holdings + rank + **announcements** in **one call** and returns a single structured payload.

This is wired into `data_manager` as task type:

- `cn_fund_all` → `cn_fund_tool.get_all`

**Note:** The current distributor splits `cn_fund_all` into curated writes for `cn_fund_basic` and `cn_fund_nav` only; fee/holdings/rank are retained in raw snapshots for replay but are not yet distributed to curated tables.

**Important:** Some AKShare endpoints (notably ranks/holdings) may return **bulk datasets** (many funds). The aggregate tool enforces a single-fund snapshot policy: if the payload is bulk and cannot be reliably filtered to the requested `fund_id`, that section is returned as `error` (rather than writing tens of thousands of unrelated funds into the raw snapshot).

**NAV compaction (implemented):** In `cn_fund_all`, the NAV section is compacted by default to improve information density:

- `nav.summary`: date range, point count, first/last NAV, total return (best-effort)
- `nav.items_full_count`: count of full NAV points before compaction
- `nav.items`: only the most recent N points (default `nav_max_items=400`)
- `nav.items_format`: default `triples` in `cn_fund_all` to reduce JSON overhead. In `triples` format, `nav.items` is a list of `[nav_date, nav, nav_accumulated]`.

If you need the full NAV series, use the dedicated task `cn_fund_nav` (no max_items by default).

**Announcements (implemented):** The `announcements` section in `cn_fund_all` JSON output aggregates four sources:

- `dividend` — 分红配送 (fund_announcement_dividend_em)
- `report` — 定期报告 (fund_announcement_report_em)
- `personnel` — 人事公告 (fund_announcement_personnel_em)
- `disclosure_cninfo` — 巨潮资讯基金披露 (stock_zh_a_disclosure_report_cninfo, market="基金") — broader coverage; items have 代码, 简称, 公告标题, 公告时间, 公告链接. Not all funds are in cninfo (e.g. 000001, 510010 may KeyError); failures are caught per-section.

Each sub-section has `fund_id`, `items`, `timestamp`, and `source`. Per-category failures set an `error` key on that sub-section but do not fail the overall payload.

---

## Storage design

### Relationship to existing fund schema (US/ETF vs CN funds)

The repo already defines a fund schema keyed by **ticker-like `symbol`** (e.g. `VOO`) in:

- [fund-data-schema.md](fund-data-schema.md) (tables `fund_info`, `fund_performance`, `fund_risk_metrics`, `fund_holdings`, `fund_sector_allocation`, `fund_flows`)

This ingestion design introduces a **CN fund domain** keyed by **`fund_id`** (e.g. `000001`, keep leading zeros). The CN tables below are intentionally namespaced as `cn_fund_*` to avoid ambiguity with existing `fund_*`.

**Important constraint (current repo):** the `sql_tool` documentation restricts query-time agents to an explicit allowlist of tables/columns (see [Agent Tools Reference](../workflow/03_tools_and_mcp/agent-tools-reference.md)). Therefore, when `cn_fund_*` tables are implemented, the corresponding documentation/tool-contract updates must land before query-time agents should use them:

- Add a CN schema reference doc: [cn-fund-data-schema.md](cn-fund-data-schema.md)
- Update [Agent Tools Reference](../workflow/03_tools_and_mcp/agent-tools-reference.md) (`sql_tool` schema allowlist) to include the `cn_fund_*` tables/columns (**TODO when tables go live**)

Until those updates land, `cn_fund_*` should be treated as **offline assets** only (for ingestion verification and internal analysis), not part of the guaranteed query surface.

### 1) Raw layer (files)

**Purpose:** preserve upstream payloads for debugging, replay, and schema evolution.

- **Path convention (aligned with existing `datasets/` layout):** `datasets/raw/ingestion/{dataset}/{as_of_date}/{fund_id}/data.json` for `cn_fund_all`. Other cn_ tasks use `{as_of_date}/{fund_id}.json`. Each fund's directory may also contain `data.csv` and `reports/*.pdf` (downloaded quarterly/annual reports).
- **Metadata envelope** (top-level fields):
  - `dataset` (e.g. `fund_basic`, `fund_nav`)
  - `fund_id`
  - `as_of_date` (date the data refers to; not collection time)
  - `collected_at` (UTC ISO)
  - `source` (e.g. `akshare`)
  - `payload` (raw upstream response)

**Repo hygiene note:** This raw path is a **runtime artifact** and should not be committed to git. Example fixtures belong under `datasets/examples/` only.

#### Optional: CSV output (cn_fund_all)

When `collect` is run with `--format csv` or `--format both`, the collector also writes one CSV file per fund alongside the JSON:

- **Path:** `datasets/raw/ingestion/cn_fund_all/{as_of_date}/{fund_id}/data.csv`
- **File naming:** `data.csv` (alongside `data.json` in the same fund directory)
- **Encoding:** UTF-8 with BOM (`utf-8-sig`) for Excel compatibility
- **Content:** All sections (basic, nav, fee, holdings, rank, announcements) in one file, separated by `# ===` section headers. **FEE** uses a long-table format (fee_type, condition, fee_value, fee_unit) to avoid many empty cells; **HOLDINGS** uses normalized columns (report_period, holding_code, holding_name, weight, etc.). Announcements are split into sub-sections: 公告-分红 (dividend), 公告-定期报告 (report), 公告-人事 (personnel), 公告-巨潮资讯 (disclosure_cninfo).

- **Empty value markers:** Instead of blank cells, CSV uses explicit markers for missing data:

  | Marker | Meaning |
  |--------|---------|
  | `not_exist` | 数据不存在 — field not present in source |
  | `not_disclosed` | 未披露 — issuer explicitly did not disclose (e.g. upstream returned 未披露/暂无/-) |
  | `parse_failed` | 解析失败 — parse/validation failed |
  | `api_missing` | 接口缺失 — API unavailable or call failed |

  `data_manager/empty_markers.py` defines these constants; cn_fund_tool and collector apply them during ingestion; consolidation preserves or fills missing columns with `not_exist`.

**Example:**
```
python -m data_manager collect --symbols 004433,510010 --tasks cn_fund_all --date 2026-03-18 --format csv
```
Produces `datasets/raw/ingestion/cn_fund_all/2026-03-18/004433/data.json`, `data.csv`, and optionally `reports/*.pdf` (downloaded quarterly/annual reports). Same for `510010`.

**Note:** The distribute pipeline reads only JSON. CSV output is for human inspection, Excel analysis, and external tools; it does not replace the JSON canonical format.

**Consolidation (implemented):** `python -m data_manager consolidate --date yyyy-mm-dd` merges per-fund data.csv into `daily.csv` (NAV + Rank blocks) and `static.csv` (Basic, Fee, Holdings, Announcements blocks). Each file contains multiple tables with `# === SECTION ===` delimiters; each block has its own header and dense columns. `static.csv` stores `as_of_date` and `consolidated_at` in file header comments and removes row-level `as_of_date`/`collected_at` columns to reduce redundancy. See [csv-consolidation-design.md](csv-consolidation-design.md).

**Report downloads (implemented):** When announcements contain 季度报告 or 年度报告 (quarterly/annual reports), the collector downloads PDFs from 东方财富 (`https://pdf.dfcfw.com/pdf/H2_{报告ID}_1.pdf`) into `{fund_id}/reports/{报告ID}.pdf`. Only EM announcement items with 报告ID (e.g. `AN202601221818251025`) are downloaded; cninfo disclosure links are not fetched (they require page parsing). **Time limits:** NAV data is limited to the last 365 days (`look_back_days` in tasks). Announcements and report downloads are limited to the last 3 years. Use `--no-reports` to skip report PDF downloads: `python -m data_manager collect --symbols 004433 --tasks cn_fund_all --no-reports`.

### 2) Curated layer (PostgreSQL)

**Purpose:** stable schema for query and joins.

#### Table: `cn_fund_basic`

Keyed by `(fund_id, as_of_date)`.

| Column | Type | Notes |
|--------|------|------|
| fund_id | VARCHAR(16) | `000001` (string, keep leading zeros) |
| fund_name | VARCHAR(256) | |
| fund_type | VARCHAR(64) | e.g. 混合型/指数型/债券型 |
| risk_level | VARCHAR(32) | upstream label if available |
| inception_date | DATE | nullable |
| fund_manager | VARCHAR(256) | nullable |
| management_company | VARCHAR(256) | nullable |
| tracking_index | VARCHAR(256) | nullable |
| investment_scope | TEXT | nullable |
| latest_scale | DECIMAL(18,6) | nullable; unit documented in ETL |
| description | TEXT | nullable |
| as_of_date | DATE | data reference date |
| collected_at | TIMESTAMP | collection timestamp |
| source | VARCHAR(64) | `akshare` |

**Unique constraint:** `(fund_id, as_of_date)`

**Recommended indexes:**

- `(fund_id, as_of_date DESC)`

**Time semantics:**

- `as_of_date` is the **business reference date** the metadata is considered valid for (not the fetch time).

#### Table: `cn_fund_nav`

Keyed by `(fund_id, nav_date)`.

| Column | Type | Notes |
|--------|------|------|
| fund_id | VARCHAR(16) | |
| nav_date | DATE | trading/NAV date |
| nav | DECIMAL(18,8) | unit NAV |
| nav_accumulated | DECIMAL(18,8) | optional, if upstream provides |
| collected_at | TIMESTAMP | |
| source | VARCHAR(64) | |

**Unique constraint:** `(fund_id, nav_date)`

**Recommended indexes:**

- `(fund_id, nav_date DESC)` (time-series queries)

**Time semantics:**

- `nav_date` is the NAV’s **business date**.
- No separate `as_of_date` is stored for NAV: this table is a pure time-series fact table keyed by `nav_date`. If upstream provides revisions/corrections for the same `nav_date`, represent that via additional revision metadata (e.g. `published_at`/`revision_id`) rather than introducing an ambiguous second date column.

#### Table: `cn_fund_fee`

Keyed by `(fund_id, as_of_date)`.

| Column | Type | Notes |
|--------|------|------|
| fund_id | VARCHAR(16) | |
| purchase_fee | DECIMAL(18,8) | normalized to decimal (e.g. 0.015) |
| redemption_fee | DECIMAL(18,8) | |
| management_fee | DECIMAL(18,8) | |
| custodian_fee | DECIMAL(18,8) | |
| as_of_date | DATE | |
| collected_at | TIMESTAMP | |
| source | VARCHAR(64) | |

**Unique constraint:** `(fund_id, as_of_date)`

**Normalization rules:**

- All fee rates stored as **decimals**. Examples:
  - `1.5%` → `0.015`
  - `0.15%` → `0.0015`
- If upstream provides tiered fee schedules, store a summarized headline rate here and preserve the full schedule in the raw snapshot (or a separate detail table in a later stage).

#### Table: `cn_fund_holdings`

Keyed by `(fund_id, as_of_date, holding_code)` (or a surrogate id if upstream lacks stable code).

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

**Unique constraint:** `(fund_id, as_of_date, holding_code)`

**Recommended indexes:**

- `(fund_id, as_of_date DESC)`
- `(holding_code)` when joining to a security master table (future)

**Time semantics:**

- `as_of_date` should represent the **portfolio report date** (often quarter-end). If upstream provides both “report_end_date” and “publish_date”, store report end as `as_of_date` and keep publish date in raw payload (or add a `published_at` column later).

#### Table: `cn_fund_rank`

Keyed by `(fund_id, as_of_date, rank_period)`.

| Column | Type | Notes |
|--------|------|------|
| fund_id | VARCHAR(16) | |
| as_of_date | DATE | |
| rank_period | VARCHAR(16) | `1m`/`3m`/`1y`… |
| rank | INTEGER | lower is better |
| percentile | DECIMAL(10,6) | 0–1 if available |
| collected_at | TIMESTAMP | |
| source | VARCHAR(64) | |

**Unique constraint:** `(fund_id, as_of_date, rank_period)`

**Recommended indexes:**

- `(fund_id, as_of_date DESC)`
- `(as_of_date DESC, rank_period, rank)` for leaderboard queries (optional)

> **Normalization rules:** All rates are stored as **decimals** (e.g. 1.5% → 0.015). All IDs are strings (do not lose leading zeros).

### 3) Feature layer (PostgreSQL)

**Purpose:** simple, stable features used by ranking and explanations.

#### Table: `cn_fund_features`

Keyed by `(fund_id, as_of_date)`.

| Column | Type | Notes |
|--------|------|------|
| fund_id | VARCHAR(16) | |
| as_of_date | DATE | features computed “as of” this date |
| return_1d / 7d / 30d / 90d | DECIMAL(18,8) | from NAV series |
| annualized_return | DECIMAL(18,8) | optional |
| volatility | DECIMAL(18,8) | nav return std |
| max_drawdown | DECIMAL(18,8) | negative decimal |
| sharpe | DECIMAL(18,8) | optional; requires risk-free assumption |
| fee_total | DECIMAL(18,8) | derived from fee table |
| institution_ratio | DECIMAL(18,8) | optional future field |
| scale_trend | DECIMAL(18,8) | optional future field |
| collected_at | TIMESTAMP | feature generation time |
| source | VARCHAR(64) | `derived` |

**Feature conventions (to keep outputs deterministic):**

- **NAV returns:** simple returns \(r_t = nav_t/nav_{t-1} - 1\); do not forward-fill missing NAV dates.
- **Volatility window:** compute volatility over a fixed trailing window (e.g. 30 most recent NAV observations) and document the exact window length used by the job (avoid “calendar-day” ambiguity).
- **Sharpe risk-free rate:** default \(r_f = 0.0\) unless explicitly configured (e.g. env/config `CN_RISK_FREE_RATE`). Document the chosen value and return periodicity (daily vs weekly) used by the feature job.

---

## Scheduling (cadence)

Recommended update frequency (same spirit as the raw idea):

| Dataset | Frequency | Reason |
|---------|-----------|--------|
| fund_basic | weekly | slow-changing metadata |
| fund_nav | daily | NAV updates |
| fund_rank | daily | used as label/feature |
| fund_holdings | quarterly | published in reports |
| fund_fee | low frequency (monthly/quarterly) | slow-changing |

**Scheduler options:** cron / Windows Task Scheduler / Airflow. Keep the first implementation simple (cron/Task Scheduler calling CLI).

---

## Failure handling and operational rules

- **Rate limits / bans:** throttle per dataset and per fund_id; prefer backoff in the collector.
- **Partial success:** one dataset failing does not block others.
- **Timestamp alignment:** every curated write requires an explicit `as_of_date`; never guess from `collected_at`.
- **Missing data:** explicit nulls + default strategy; no silent drop of rows.
- **Replay:** raw snapshots allow re-running transforms without hitting upstream.

---

## Integration with the rest of the system

### Relationship to `data_manager`

This ingestion module should be implemented as an extension of `data_manager` (background workflows). The real-time agent flow (Planner → WebSearcher/Librarian/Analyst) should query Postgres via `sql_tool` and vector/graph stores via MCP tools, not AKShare directly.

### Implementation boundary (repo-aligned)

- **AKShare access:** only inside ingestion collectors (offline).
- **Database writes:** via MCP tools under `openfund_mcp/tools/` (e.g. `sql_tool`, `kg_tool`, `vector_tool`) so the ingestion path is consistent with other background workflows.
- **Task integration point:** implement CN ingestion as a **new task family** under `data_manager/tasks.py` (e.g. `cn_fund_basic`, `cn_fund_nav`, `cn_fund_fee`, `cn_fund_holdings`, `cn_fund_rank`) plus an optional `cn_fund_features` generator job. This should be additive and must not break existing stock/US tasks.

### Doc & tool-contract updates (required when CN tables go live)

- ✅ Added [cn-fund-data-schema.md](cn-fund-data-schema.md) for `cn_fund_basic`, `cn_fund_nav`, `cn_fund_fee`, `cn_fund_holdings`, `cn_fund_rank`, `cn_fund_features`.
- ⛳ **TODO (when enabling query-time use):** Update [Agent Tools Reference](../workflow/03_tools_and_mcp/agent-tools-reference.md) (`sql_tool` schema allowlist) to include the CN tables/columns, and ensure agents only query tables present in the allowlist.
- If/when query-time integration is desired, update the Librarian/planner heuristics to choose CN (`fund_id`) vs global (`symbol`) schemas explicitly (no guessing across domains).

### Optional outputs (future)

- **Neo4j:** `Fund → Holding → Stock` edges from `cn_fund_holdings`.
- **Milvus:** “Fund profile generator” turns curated + features into a short text paragraph, embeds it, and stores for semantic retrieval.

---

## Optional: NAV revisions / corrections (NOT implemented in current version)

Some upstreams may publish **corrections** for a previously released NAV value for the same `fund_id` and `nav_date`. The **current version does not implement** NAV revisions; `cn_fund_nav` is treated as a single-record-per-day fact table keyed by `(fund_id, nav_date)`.

If revisions become necessary later, prefer one of these explicit patterns:

### Pattern A: Add revision metadata columns on `cn_fund_nav` (lightweight)

- **Add columns:** `published_at TIMESTAMP NULL`, `revision_id VARCHAR(64) NULL`, `is_latest BOOLEAN NOT NULL DEFAULT TRUE`
- **Rule:** Keep multiple rows per `(fund_id, nav_date)` by extending uniqueness to include `revision_id` (or by dropping the simple unique constraint and using a composite unique key).
- **Query rule:** default queries filter `is_latest = TRUE`.

### Pattern B: Separate `cn_fund_nav_revisions` table (cleaner)

- Keep `cn_fund_nav` as the “latest view” (one row per day).
- Add a new table `cn_fund_nav_revisions(fund_id, nav_date, revision_id, nav, published_at, collected_at, source, raw_ref)` to preserve all versions.
- **Query rule:** `cn_fund_nav` is what query-time agents use; revisions table is for auditing/debugging/replay.

Both patterns require rethinking DDL constraints and the feature job’s “as-of” semantics. Do not implement revisions until a real upstream correction case is observed.

---

## Security and compliance notes

- No secrets in code; upstream keys (if any) via environment variables.
- Respect upstream terms; scraping-heavy sources should be rate limited and cached.

