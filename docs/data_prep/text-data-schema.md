# Text Data Schema (Milvus)

This document defines the Milvus text/vector data loaded from JSON files under `database/text_data` by [`scripts/data_loader.py`](../../scripts/data_loader.py), which builds documents and calls [`vector_tool.upsert_documents`](../../openfund_mcp/tools/vector_tool.py). Embeddings are computed at load time from **content** (not taken from JSON unless you extend the loader).

## Source of truth

| Item | Location |
|------|----------|
| Loader orchestration | [`scripts/data_loader.py`](../../scripts/data_loader.py) (`load_milvus_from_text_json`) |
| Persistence / search | [`openfund_mcp/tools/vector_tool.py`](../../openfund_mcp/tools/vector_tool.py) |
| Input directory (default) | `database/text_data` |
| Backend | Milvus (`MILVUS_URI`; collection `MILVUS_COLLECTION`, default `openfund_docs`) |

**Schema version:** 1.0 — documentation aligned with loader + `vector_tool` collection layout. Bump when the canonical field list, delete expression, or collection schema changes.

**Change policy:** Additive JSON fields are ignored unless `data_loader.py` is updated to map them. Changing primary storage fields (`id`, `content`, `fund_id`, `source`) or the loader-owned `source` value requires coordinated code + doc updates.

---

## Documented JSON vs stored documents

Source files are **JSON arrays** of objects. The loader **does not** persist arbitrary keys.

| Source JSON field | Used by loader? | Stored in Milvus? |
|-------------------|-----------------|-------------------|
| `id` | Yes (required for a row to be ingested) | Yes — primary key `id` (VARCHAR) |
| `content` | Yes — primary text; if missing, `title` is used as content | Yes — `content` |
| `title` | Yes — only as **fallback** when `content` is empty/absent | No separate field (text becomes `content`) |
| `fund_id` | Yes — optional | Yes — `fund_id` |
| `source` | **Overwritten** — loader sets `"loader"` for lifecycle | Yes — always `"loader"` for loader runs |
| Other keys (e.g. `category`, `embedding`) | **No** | **No** — not read by [`load_milvus_from_text_json`](../../scripts/data_loader.py) |

**Implication:** Extra columns in `sample_text.json` (such as `category` or precomputed `embedding`) are **not** loaded into Milvus by this pipeline; embeddings are **recomputed** from `content` via the configured sentence-transformers model in `vector_tool`.

---

## Load behavior

| Mode | Behavior |
|------|----------|
| `--load-mode existing` | Skipped if `MILVUS_URI` unset, no JSON files, or embedding model unavailable locally (unless `--milvus-force-download`). Otherwise merges all `*.json` arrays, builds docs, **upserts** via `vector_tool.upsert_documents`. |
| `--load-mode fresh-all` | Same preconditions; runs `vector_tool.delete_by_expr('source == "loader"')` then upserts rebuilt docs. |
| `--load-mode skip` | Milvus load skipped. |

CLI: [`scripts/data_loader.py`](../../scripts/data_loader.py) `--text-dir` (default `database/text_data`), `--milvus-force-download`.

---

## Loader limitations

| Limitation | Detail |
|------------|--------|
| Top-level shape | Each `*.json` file must be a **JSON array**. Non-array files are skipped (no rows loaded from that file). |
| Non-dict rows | Array elements that are not objects are skipped. |
| Loader-owned `source` | All ingested docs get `source == "loader"`; `fresh-all` deletes **only** those rows. Docs inserted by other tools with a different `source` are untouched by `fresh-all`. |
| No partial file merge | Loader does not merge `category` or custom metadata into Milvus without code changes. |
| Embedding model | Must be available locally unless `--milvus-force-download` (avoids hang on uncached models). |

---

## Reproducibility

| Mode | Determinism |
|------|-------------|
| `fresh-all` | After deleting `source == "loader"`, reload from sorted `*.json` paths and stable in-file order — **reproducible** given identical files, model, and `EMBEDDING_*` env. |
| `existing` | Upsert overwrites by `id` inside `vector_tool` (delete-by-id then insert). Re-running the same inputs should converge; concurrent writers outside the loader are not modeled. |

For repeatable pipelines, pin **JSON files**, **model name**, and **`EMBEDDING_DIM`** to match the collection.

---

## Input file contract

| Rule | Detail |
|------|--------|
| Location | `database/text_data/*.json` (or `--text-dir`) |
| Encoding | UTF-8 |
| Structure | **Array** of objects per file |
| Discovery | Sorted glob `*.json`; all files processed |

Rows require non-empty **`id`** (after `str()`) and non-empty **text** (`content` or `title`); otherwise the row is skipped.

---

## Milvus collection schema (vector_tool)

When the collection is created by [`_get_collection`](../../openfund_mcp/tools/vector_tool.py), fields are:

| Field | Type | Notes |
|-------|------|-------|
| `id` | VARCHAR (PK, max 64) | Document id from JSON |
| `content` | VARCHAR (max 65535) | Text embedded and stored |
| `embedding` | FLOAT_VECTOR, dim = `EMBEDDING_DIM` (default 384) | From `model.encode(content)` |
| `fund_id` | VARCHAR (max 256) | Optional |
| `source` | VARCHAR (max 256) | Loader sets `"loader"` |

Default collection name: **`openfund_docs`** (`MILVUS_COLLECTION`). New collections get an **IVF_FLAT** index on `embedding` with metric **IP** (inner product), `nlist=128` — created by `vector_tool`, not by `data_loader.py`.

---

## Environment and model gating

| Variable | Role |
|----------|------|
| `MILVUS_URI` | Required for real load; if unset, Milvus path is skipped. |
| `MILVUS_COLLECTION` | Collection name (default `openfund_docs`). |
| `EMBEDDING_MODEL` | Sentence-transformers model (default `sentence-transformers/all-MiniLM-L6-v2`). |
| `EMBEDDING_DIM` | Must match collection vector dim (default **384** for the default model). |

Local-only model check: [`can_load_embedding_model_locally`](../../scripts/data_loader.py) — use `--milvus-force-download` to allow download when not cached.

---

## Operational context

### Mock / sample data

The repo includes [`database/text_data/sample_text.json`](../../database/text_data/sample_text.json) as **sample/mock** content for verifying ingestion and retrieval. Extra keys in that file illustrate source-export shape but are **not** all persisted by the loader (see table above). This is intentional for the loader-first workflow.

### Freshness

Driven by how often you replace or regenerate JSON under `database/text_data`, not by Milvus alone.

---

## Data quality rules

- Empty `id` or no usable text → row skipped.
- `fund_id` omitted → stored as empty string.
- **`source` in JSON is not preserved** for loader runs — always `"loader"` for lifecycle and `fresh-all` deletion.

---

## Query and tooling patterns

Semantic search goes through **`vector_tool.search`** (MCP) with the configured collection; see [`agent-tools-reference.md`](../workflow/03_tools_and_mcp/agent-tools-reference.md). Example flow: embed query string, search by vector similarity, filter by `fund_id` or `source` if exposed by the tool.

---

## Minimal validation checks

After load, use MCP **`vector_tool`** helpers or Milvus SDK (when `MILVUS_URI` is set):

- **Count loader-owned docs:** filter `source == "loader"`.
- **Spot-check ids:** ensure expected `id` values from JSON appear in query results.

---

## Cross-links

- SQL / stats: [stats-data-schema.md](stats-data-schema.md)
- Neo4j bundle: [graph-data-schema.md](graph-data-schema.md)
- Loader-first overview and verification: [revision_plan.md](revision_plan.md)

---

## Document history

| Version | Notes |
|---------|--------|
| 1.0 | Expanded to match stats/graph operational style: JSON vs stored fields, load modes, limitations, reproducibility, Milvus schema, env gating, mock note, cross-links. |
