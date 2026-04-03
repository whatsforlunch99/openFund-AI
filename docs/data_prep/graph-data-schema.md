# Graph Data Schema (Neo4j)

This document defines the Neo4j graph data loaded from the **normalized CSV bundle** under `database/graph_data/neo4j_export` by [`scripts/data_loader.py`](../../scripts/data_loader.py), which delegates import to [`kg_tool.load_graph_csvs_to_neo4j`](../../openfund_mcp/tools/kg_tool.py) after [`kg_tool.validate_graph_csv_bundle_for_neo4j`](../../openfund_mcp/tools/kg_tool.py). The graph **shape** (labels, relationship types, id conventions) comes from the bundle; the loader does not hardcode a domain ontology beyond the CSV contract.

## Source of truth

| Item | Location |
|------|----------|
| Loader orchestration | [`scripts/data_loader.py`](../../scripts/data_loader.py) (`load_neo4j_from_csv_bundle`) |
| Import / validation | [`openfund_mcp/tools/kg_tool.py`](../../openfund_mcp/tools/kg_tool.py) |
| Input directory (default) | `database/graph_data/neo4j_export` |
| Backend | Neo4j (`NEO4J_URI`; optional `NEO4J_USER`, `NEO4J_PASSWORD`, `NEO4J_DATABASE`) |

**Schema version:** 1.0 — documentation aligned with validation payload `schema: "normalized_bundle_v4"` from `validate_graph_csv_bundle_for_neo4j`. Bundle layout or validation rules may evolve with `kg_tool`; bump this note when the contract changes.

**Change policy:** Additive bundle fields or new relationship types are OK if they remain valid for the loader and validator. Breaking changes to required files, column names, or validation rules require updates to [`kg_tool.py`](../../openfund_mcp/tools/kg_tool.py) and this document together.

---

## Documented bundle vs runtime graph

The **required** unified-load contract is fixed in code:

- **Filenames:** `graph_nodes.csv` and `graph_relationships.csv` must exist under the bundle directory ([`load_graph_csvs_to_neo4j`](../../openfund_mcp/tools/kg_tool.py) with `output_dir` set).
- **Column names** for nodes and relationships are those consumed by `_load_unified_graph_nodes` and `_load_unified_graph_rels` (see [Bundle file contract](#bundle-file-contract)).
- **`:LABEL`** on nodes drives Neo4j labels (multiple labels separated by `;`); each token must match the identifier regex used in `kg_tool`.
- **`:TYPE`** on relationships must be a valid relationship type identifier or the row is skipped.

**The loader does not:**

- Add columns beyond the mapped node properties (`symbol`, `name`, `dataset`, `record_type`) from the node CSV in unified mode.
- Infer business meaning of labels or rel types—it **MERGE**s nodes and relationships as given.

**Optional file:** Some export pipelines also emit `category_inspection.csv` for human or QA review. That file is **not** read by `load_graph_csvs_to_neo4j` or by `validate_graph_csv_bundle_for_neo4j` (validation only requires the two CSVs above). Keep it if you use it outside the load path.

---

## Load behavior

| Mode | Behavior |
|------|----------|
| `--load-mode existing` | Skipped if `NEO4J_URI` unset. Otherwise runs `validate_graph_csv_bundle_for_neo4j`; on failure, **no write**. On success, **append** load via `load_graph_csvs_to_neo4j(..., mode="append", output_dir=...)`. |
| `--load-mode fresh-all` | Runs validation, then tries offline `neo4j-admin database import full` when `NEO4J_FRESH_IMPORT_MODE=auto|offline` (default `auto`). If offline import is unavailable/fails in `auto`, falls back to online wipe (`MATCH (n) DETACH DELETE n`) + append load. `offline` mode is strict: returns error instead of fallback. |
| `--load-mode skip` | Neo4j load skipped. |

CLI defaults: [`scripts/data_loader.py`](../../scripts/data_loader.py) `--neo4j-csv-dir` (default `database/graph_data/neo4j_export`).

---

## Loader limitations

| Limitation | Detail |
|------------|--------|
| Global wipe on `fresh-all` | Deletes **all** nodes and relationships in the database configured by `NEO4J_URI` / `NEO4J_DATABASE`—not symbol-scoped. |
| Offline import downtime | `neo4j-admin` full import requires stop/import/start; use for rebuild windows, not request-time operations. |
| Validation gate | Invalid bundle → **no** import (loader returns error status). |
| Node properties | Unified online load sets only `node_id`, `symbol`, `name`, `dataset`, `record_type`, and derives `id` from `symbol` or `node_id` ([`_load_unified_graph_nodes`](../../openfund_mcp/tools/kg_tool.py)). Extra CSV columns are not mapped unless the loader is extended. |
| Relationship mode | Online path supports only `mode="append"`; relationships are loaded in batches grouped by `:TYPE` to reduce Bolt round trips. |
| Mock / skip | If `NEO4J_URI` is unset, `kg_tool` may return mock success without persisting data. |

**Implication:** Treat the bundle + `kg_tool` source as the contract for what gets written, not an implied ETF-only or fund-only schema.

---

## Reproducibility

| Mode | Determinism |
|------|-------------|
| `fresh-all` | For a **fixed bundle** and **fixed loader/kg_tool version**, the graph is rebuilt from scratch after a full delete—highly reproducible. |
| `existing` | **MERGE** semantics: re-running the same bundle may update properties on matching `node_id`; order of operations can matter for duplicate keys within a single file. Concurrent writes outside the loader are not modeled. |

For repeatable pipelines, prefer a controlled **`fresh-all`** from pinned CSVs.

---

## Bundle file contract

### Required files

| File | Role |
|------|------|
| `graph_nodes.csv` | One row per node; Neo4j admin–style headers (see below). |
| `graph_relationships.csv` | One row per relationship; start/end ids and type. |

### `graph_nodes.csv`

Headers used by the unified loader (see [`_load_unified_graph_nodes`](../../openfund_mcp/tools/kg_tool.py)):

| Column | Role |
|--------|------|
| `node_id:ID` | Stable node identifier (required for non-skipped rows). |
| `:LABEL` | Label set; use `;` for multiple labels. Tokens must satisfy the loader’s identifier check. |
| `symbol` | Mapped to property `symbol` (also used to set `id` when non-empty). |
| `name` | Mapped to property `name`. |
| `dataset` | Mapped to property `dataset`. |
| `record_type` | Mapped to property `record_type`. |

Rows with empty `node_id:ID` are skipped.

### `graph_relationships.csv`

Headers used by [`_load_unified_graph_rels`](../../openfund_mcp/tools/kg_tool.py):

| Column | Role |
|--------|------|
| `:START_ID` | Must match an existing node `node_id` in the bundle (validator checks endpoint presence against collected ids). |
| `:END_ID` | Same. |
| `:TYPE` | Relationship type name; must match identifier regex or the row is skipped. |
| `source_field` | Optional; stored on the relationship when non-empty; validator may flag unknown `source_field` values relative to expected dimension relations. |

Rows with empty start, end, or type are skipped.

### Optional: `category_inspection.csv`

May appear in **export** output from graph tooling for inspection. It is **not** imported by `scripts/data_loader.py` / `load_graph_csvs_to_neo4j` and is **not** required by `validate_graph_csv_bundle_for_neo4j`.

---

## Validation contract

`validate_graph_csv_bundle_for_neo4j(output_dir, sample_limit=...)` returns `ok: false` with an `error` string if required files are missing. When successful, it returns counts and checks including (non-exhaustive):

- Duplicate `node_id:ID` rows in `graph_nodes.csv`
- Per-label duplicate id tallies (Record, Dataset, Tag, Currency, Dimension patterns)
- Non-canonical id samples (relative to project regex rules)
- Tag/currency quality warnings (e.g. overlong tag values, suspicious currency codes—samples capped by `sample_limit`)
- Relationship rows: missing start/end references, invalid `:TYPE` tokens, duplicate `(start, end, type, source_field)` keys, relationship type counts

Full logic: [`validate_graph_csv_bundle_for_neo4j`](../../openfund_mcp/tools/kg_tool.py). The validation result is attached to the loader’s JSON output under `neo4j.validation`.

---

## Node label categories (validator)

The validator buckets nodes by `:LABEL` for reporting. Common **families** in normalized bundles:

| Bucket | Notes |
|--------|--------|
| Record* | Record-style entities (labels starting with `Record` per project conventions). |
| Dataset | Dataset nodes. |
| Tag | Tag nodes (deduped categorical values in many pipelines). |
| Currency | Currency nodes. |
| Dimension | Dimension nodes. |

Exact labels and properties in your database depend on the bundle content—use `CALL db.labels()` or `kg_tool.get_graph_schema()` after load.

---

## Operational context

- **Freshness:** Driven by **how often you regenerate** `database/graph_data/neo4j_export`, not by Neo4j itself.
- **Timezones:** Only relevant if you store timestamps in node/edge properties from your export pipeline; the CSV contract above does not require a timestamp column.

---

## Data quality rules (loader)

- Empty `node_id:ID` → node row skipped.
- Empty `:START_ID`, `:END_ID`, or `:TYPE` → relationship row skipped.
- Invalid `:TYPE` (fails identifier regex) → relationship row skipped.
- Validation failures → **entire** Neo4j load aborted for that run (no partial write from the loader’s perspective).

---

## Recommended indexes and constraints (optional)

The loader **does not** create indexes or constraints. For large graphs, consider (in your deployment) constraints on `node_id` per label and indexes that match your Cypher access patterns—for example, if you always look up by `node_id`:

```cypher
-- Illustrative only; adjust labels to match your bundle.
CREATE CONSTRAINT record_node_id IF NOT EXISTS
FOR (n:Record) REQUIRE n.node_id IS UNIQUE;
```

Create only what your query workload needs; see Neo4j docs for syntax per edition.

---

## Common Cypher patterns

**Label inventory**

```cypher
CALL db.labels() YIELD label RETURN label ORDER BY label;
```

**Relationship types**

```cypher
CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType ORDER BY relationshipType;
```

**One-hop neighbors by `node_id`**

```cypher
MATCH (a {node_id: $id})-[r]-(b)
RETURN type(r), labels(b), b.node_id AS other_id
LIMIT 50;
```

**Counts by label**

```cypher
MATCH (n)
RETURN labels(n) AS lbls, count(*) AS n
ORDER BY n DESC;
```

---

## Minimal validation queries

After a successful load, sanity-check the database (expect zero rows where stated).

**Nodes missing `node_id` (should not happen if every merged node set `node_id`)**

```cypher
MATCH (n)
WHERE n.node_id IS NULL
RETURN count(*) AS missing_node_id;
```

**Duplicate `node_id` among nodes that expose it (should be zero if MERGE keys are unique)**

```cypher
MATCH (n)
WHERE n.node_id IS NOT NULL
WITH n.node_id AS nid, count(*) AS c
WHERE c > 1
RETURN nid, c;
```

---

## Cross-links

- SQL / stats CSV: [stats-data-schema.md](stats-data-schema.md)
- Milvus / text JSON: [text-data-schema.md](text-data-schema.md)
- Loader-first overview and verification commands: [revision_plan.md](revision_plan.md)

---

## Document history

| Version | Notes |
|---------|--------|
| 1.0 | Expanded to match stats-data-schema operational style: bundle contract, limitations, reproducibility, validation summary, Cypher patterns, optional indexes, cross-links. |
