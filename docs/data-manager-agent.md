# Data Manager Agent

Code-aligned reference for `data_manager/*`.

## Entry Point

- CLI module: `python -m data_manager`
- Core subcommands:
  - `populate`
  - `sql`
  - `neo4j`
  - `milvus`
  - `collect`
  - `global-news`
  - `status`
  - `list`
  - `distribute`
  - `distribute-funds`

## Responsibilities

- Collect market/fund/company data to local files
- Transform data into backend-specific shapes
- Distribute into PostgreSQL, Neo4j, and Milvus
- Support operational maintenance (SQL/Cypher/Milvus CLI calls)

## `distribute-funds` Modes

- `--load-mode existing`: upsert into existing tables/graph
- `--load-mode fresh --fresh-scope symbols`: purge affected symbols first, then load
- `--load-mode fresh --fresh-scope all`: purge all fund tables first, then load

## Schema Authority

- PostgreSQL DDL and upsert templates: `data_manager/schemas.py`
- Transformer mappings: `data_manager/transformer.py`
- Distribution flow: `data_manager/distributor.py`

## Notes

- `populate` seeds baseline demo rows (NVDA-focused baseline) for enabled backends.
- `distribute-funds` is the main pipeline for `datasets/combined_funds.json`.
