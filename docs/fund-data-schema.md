# Fund Data Schema

This summary matches the PostgreSQL DDL in `data_manager/schemas.py`.

## Fund Tables

- `fund_info`
- `fund_performance`
- `fund_risk_metrics`
- `fund_holdings`
- `fund_sector_allocation`
- `fund_flows`

## Related Tables Used by the Same Pipeline

- `company_fundamentals`
- `stock_ohlcv`
- `financial_statements`
- `insider_transactions`
- `technical_indicators`

## Key Uniqueness Constraints

- `fund_info`: `(symbol, as_of_date)`
- `fund_performance`: `(symbol, as_of_date)`
- `fund_risk_metrics`: `(symbol, as_of_date)`
- `fund_holdings`: `(fund_symbol, holding_symbol, as_of_date)`
- `fund_sector_allocation`: `(symbol, sector, as_of_date)`
- `fund_flows`: `(symbol, period, as_of_date)`
- `company_fundamentals`: `(symbol, as_of_date)`

## Write Semantics

- Distributor uses UPSERT templates (`ON CONFLICT`) for idempotent loads.
- Fresh load mode purges old rows first (`symbols` or `all` scope), then rewrites snapshots.
