# Fund Data Schema Reference

This document describes the data categories, formats, and types stored in the three databases after importing fund data from `datasets/combined_funds.json`.

> **Relationship to other docs:** This is a companion reference to [data-manager-agent.md](data-manager-agent.md). While data-manager-agent.md covers the agent design, CLI commands, and stock data schema, this document provides detailed schema for **fund-specific** data (ETFs, mutual funds).

---

## Source Data File

| File | Description | Data Categories |
|------|-------------|-----------------|
| `combined_funds.json` | Canonical merged fund dataset used for backend distribution | Info, Performance, Risk, Holdings, Sectors, Flows, Company Fundamentals |

---

## PostgreSQL Schema

PostgreSQL stores structured tabular data with full indexing and query capabilities.

### Tables Overview

| Table | Description | Records per Fund |
|-------|-------------|------------------|
| `fund_info` | Basic fund information | 1 |
| `fund_performance` | Historical returns | 1 |
| `fund_risk_metrics` | Risk indicators | 1 |
| `fund_holdings` | Top holdings | 10 (top 10) |
| `fund_sector_allocation` | Sector weights | ~11 |
| `fund_flows` | Inflow/outflow data | 1 |

### Table: `fund_info`

Basic fund information and characteristics.

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `id` | SERIAL | Primary key | 1 |
| `symbol` | VARCHAR(32) | Fund ticker | `VOO` |
| `name` | VARCHAR(256) | Fund name | `Vanguard S&P 500 ETF` |
| `category` | VARCHAR(128) | Fund category | `Large Cap Blend` |
| `index_tracked` | VARCHAR(128) | Benchmark index | `S&P 500` |
| `investment_style` | VARCHAR(64) | Investment style | `Large Cap Growth` |
| `total_assets_billion` | DECIMAL(12,2) | AUM in billions | `688.60` |
| `expense_ratio` | DECIMAL(8,6) | Annual expense ratio | `0.000300` |
| `dividend_yield` | DECIMAL(8,6) | Dividend yield | `0.011000` |
| `holdings_count` | INTEGER | Number of holdings | `503` |
| `as_of_date` | DATE | Data reference date | `2025-02-28` |
| `collected_at` | TIMESTAMP | Collection timestamp | `2026-02-28T10:30:00Z` |

**Unique Constraint:** `(symbol, as_of_date)`

### Table: `fund_performance`

Historical return metrics.

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `id` | SERIAL | Primary key | 1 |
| `symbol` | VARCHAR(32) | Fund ticker | `VOO` |
| `as_of_date` | DATE | Data reference date | `2025-02-28` |
| `ytd_return` | DECIMAL(10,6) | Year-to-date return | `0.178200` |
| `return_1yr` | DECIMAL(10,6) | 1-year annualized return | `0.264000` |
| `return_3yr` | DECIMAL(10,6) | 3-year annualized return | `0.115900` |
| `return_5yr` | DECIMAL(10,6) | 5-year annualized return | `0.147500` |
| `return_10yr` | DECIMAL(10,6) | 10-year annualized return | `0.120800` |
| `collected_at` | TIMESTAMP | Collection timestamp | `2026-02-28T10:30:00Z` |

**Unique Constraint:** `(symbol, as_of_date)`

### Table: `fund_risk_metrics`

Risk and volatility indicators.

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `id` | SERIAL | Primary key | 1 |
| `symbol` | VARCHAR(32) | Fund ticker | `VOO` |
| `as_of_date` | DATE | Data reference date | `2025-02-28` |
| `beta` | DECIMAL(8,4) | Beta vs market | `1.0000` |
| `standard_deviation` | DECIMAL(8,6) | Volatility (std dev) | `0.132500` |
| `sharpe_ratio` | DECIMAL(8,4) | Risk-adjusted return | `1.8600` |
| `max_drawdown` | DECIMAL(8,6) | Maximum drawdown | `-0.245300` |
| `collected_at` | TIMESTAMP | Collection timestamp | `2026-02-28T10:30:00Z` |

**Unique Constraint:** `(symbol, as_of_date)`

### Table: `fund_holdings`

Top holdings composition.

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `id` | SERIAL | Primary key | 1 |
| `fund_symbol` | VARCHAR(32) | Fund ticker | `VOO` |
| `holding_symbol` | VARCHAR(32) | Holding ticker | `AAPL` |
| `holding_name` | VARCHAR(256) | Holding name | `Apple Inc.` |
| `weight` | DECIMAL(8,6) | Portfolio weight | `0.072000` |
| `sector` | VARCHAR(128) | Holding sector | `Technology` |
| `as_of_date` | DATE | Data reference date | `2025-02-28` |
| `collected_at` | TIMESTAMP | Collection timestamp | `2026-02-28T10:30:00Z` |

**Unique Constraint:** `(fund_symbol, holding_symbol, as_of_date)`

### Table: `fund_sector_allocation`

Sector distribution weights.

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `id` | SERIAL | Primary key | 1 |
| `symbol` | VARCHAR(32) | Fund ticker | `VOO` |
| `sector` | VARCHAR(128) | Sector name | `Technology` |
| `weight` | DECIMAL(8,6) | Allocation weight | `0.310000` |
| `as_of_date` | DATE | Data reference date | `2025-02-28` |
| `collected_at` | TIMESTAMP | Collection timestamp | `2026-02-28T10:30:00Z` |

**Unique Constraint:** `(symbol, sector, as_of_date)`

### Table: `fund_flows`

Fund inflow and outflow data.

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `id` | SERIAL | Primary key | 1 |
| `symbol` | VARCHAR(32) | Fund ticker | `VOO` |
| `period` | VARCHAR(32) | Time period | `2025` |
| `inflow_billion` | DECIMAL(12,4) | Inflows in billions | `137.7000` |
| `outflow_billion` | DECIMAL(12,4) | Outflows in billions | `NULL` |
| `net_flow_billion` | DECIMAL(12,4) | Net flows | `137.7000` |
| `pct_of_aum` | DECIMAL(8,6) | Flow as % of AUM | `0.200000` |
| `as_of_date` | DATE | Data reference date | `2025-02-28` |
| `collected_at` | TIMESTAMP | Collection timestamp | `2026-02-28T10:30:00Z` |

**Unique Constraint:** `(symbol, period, as_of_date)`

---

## Neo4j Graph Schema

Neo4j stores relationship data as a property graph with nodes and edges.

### Node Types

#### Fund Node

Represents an ETF or mutual fund.

| Property | Type | Description | Example |
|----------|------|-------------|---------|
| `symbol` | String | Fund ticker (unique key) | `VOO` |
| `name` | String | Fund name | `Vanguard S&P 500 ETF` |
| `category` | String | Fund category | `Large Cap Blend` |
| `index_tracked` | String | Benchmark index | `S&P 500` |
| `investment_style` | String | Investment style | `Large Cap Growth` |
| `total_assets_billion` | Float | AUM in billions | `688.6` |
| `expense_ratio` | Float | Annual expense ratio | `0.0003` |
| `collected_at` | String | Collection timestamp | `2026-02-28T10:30:00Z` |

**Cypher Example:**
```cypher
MATCH (f:Fund {symbol: 'VOO'})
RETURN f.name, f.total_assets_billion, f.expense_ratio
```

#### Company Node

Represents a company held in fund portfolios.

| Property | Type | Description | Example |
|----------|------|-------------|---------|
| `symbol` | String | Stock ticker (unique key) | `AAPL` |
| `name` | String | Company name | `Apple Inc.` |

**Cypher Example:**
```cypher
MATCH (c:Company {symbol: 'AAPL'})
RETURN c.name
```

#### Sector Node

Represents an industry sector.

| Property | Type | Description | Example |
|----------|------|-------------|---------|
| `name` | String | Sector name (unique key) | `Technology` |

**Cypher Example:**
```cypher
MATCH (s:Sector)
RETURN s.name
```

### Relationship Types

#### HOLDS Relationship

Connects Fund to Company (portfolio holdings).

| Property | Type | Description | Example |
|----------|------|-------------|---------|
| `weight` | Float | Portfolio weight | `0.072` |
| `as_of_date` | String | Data reference date | `2025-02-28` |

**Pattern:** `(Fund)-[:HOLDS {weight, as_of_date}]->(Company)`

**Cypher Example:**
```cypher
// Find top holdings of VOO
MATCH (f:Fund {symbol: 'VOO'})-[h:HOLDS]->(c:Company)
RETURN c.symbol, c.name, h.weight
ORDER BY h.weight DESC
LIMIT 10
```

#### INVESTS_IN_SECTOR Relationship

Connects Fund to Sector (allocation weights).

| Property | Type | Description | Example |
|----------|------|-------------|---------|
| `weight` | Float | Allocation weight | `0.31` |

**Pattern:** `(Fund)-[:INVESTS_IN_SECTOR {weight}]->(Sector)`

**Cypher Example:**
```cypher
// Find sector allocation of QQQ
MATCH (f:Fund {symbol: 'QQQ'})-[r:INVESTS_IN_SECTOR]->(s:Sector)
RETURN s.name, r.weight
ORDER BY r.weight DESC
```

### Graph Statistics (Current Data)

| Metric | Count |
|--------|-------|
| Fund nodes | 50 |
| Company nodes | 76 |
| Sector nodes | 15 |
| HOLDS edges | 141 |
| INVESTS_IN_SECTOR edges | 142 |

### Sample Queries

**Find funds that hold a specific company:**
```cypher
MATCH (f:Fund)-[h:HOLDS]->(c:Company {symbol: 'NVDA'})
RETURN f.symbol, f.name, h.weight
ORDER BY h.weight DESC
```

**Find common holdings between two funds:**
```cypher
MATCH (f1:Fund {symbol: 'VOO'})-[:HOLDS]->(c:Company)<-[:HOLDS]-(f2:Fund {symbol: 'QQQ'})
RETURN c.symbol, c.name
```

**Find funds with highest Technology allocation:**
```cypher
MATCH (f:Fund)-[r:INVESTS_IN_SECTOR]->(s:Sector {name: 'Technology'})
RETURN f.symbol, f.name, r.weight
ORDER BY r.weight DESC
LIMIT 10
```

**Network exploration - 2-hop from a fund:**
```cypher
MATCH path = (f:Fund {symbol: 'VGT'})-[*1..2]-(n)
RETURN path
LIMIT 50
```

---

## Milvus Vector Schema (Future)

Milvus is designed for vector similarity search on text-based data. Currently not populated for fund data, but schema is defined for future use.

### Collection: `fund_documents`

| Field | Type | Description |
|-------|------|-------------|
| `id` | VARCHAR(64) | Document ID (primary key) |
| `content` | VARCHAR(65535) | Text content for embedding |
| `embedding` | FLOAT_VECTOR(384) | Vector embedding |
| `symbol` | VARCHAR(32) | Associated fund symbol |
| `doc_type` | VARCHAR(32) | Document type |
| `source` | VARCHAR(256) | Data source |
| `published_at` | VARCHAR(32) | Publication date |
| `collected_at` | VARCHAR(32) | Collection timestamp |

### Planned Document Types

| Type | Source | Use Case |
|------|--------|----------|
| `fund_description` | Fund prospectus | Search by investment strategy |
| `news` | Financial news | Current events affecting funds |
| `analyst_report` | Research reports | Qualitative analysis |
| `earnings_summary` | Earnings calls | Company performance insights |

---

## Data Category Summary

### By Database Target

| Data Category | PostgreSQL | Neo4j | Milvus |
|---------------|------------|-------|--------|
| Fund basic info | ✅ `fund_info` | ✅ `Fund` node | — |
| Performance metrics | ✅ `fund_performance` | — | — |
| Risk metrics | ✅ `fund_risk_metrics` | — | — |
| Holdings | ✅ `fund_holdings` | ✅ `HOLDS` edge | — |
| Sector allocation | ✅ `fund_sector_allocation` | ✅ `INVESTS_IN_SECTOR` edge | — |
| Fund flows | ✅ `fund_flows` | — | — |
| Company info | — | ✅ `Company` node | — |
| Sector info | — | ✅ `Sector` node | — |
| Text descriptions | — | — | 🔜 `fund_documents` |

### By Data Format

| Format | Database | Examples |
|--------|----------|----------|
| Tabular/Row | PostgreSQL | Returns, ratios, dollar amounts |
| Graph/Network | Neo4j | Fund→Company, Fund→Sector |
| Vector/Embedding | Milvus | Descriptions, news, reports |

### By Query Pattern

| Query Type | Best Database | Example |
|------------|---------------|---------|
| Filter & aggregate | PostgreSQL | "Funds with expense ratio < 0.1%" |
| Relationship traversal | Neo4j | "Companies held by multiple funds" |
| Similarity search | Milvus | "Funds similar to VOO by strategy" |
| Time series | PostgreSQL | "Performance trend over 5 years" |
| Path finding | Neo4j | "Connection between AAPL and Technology sector" |

---

## References

- [data-manager-agent.md](data-manager-agent.md) — Data Manager Agent design and CLI commands
- [backend.md](backend.md) — System architecture
- [file-structure.md](file-structure.md) — Code structure
