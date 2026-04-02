# Data Extraction Design Document

Formal design for extracting structured and retrievable data assets from fund PDF reports (annual/quarterly) in the Data Manager offline pipeline.

> Related docs:
> - Product and runtime context: [backend.md](../workflow/02_planning/backend.md)
> - Data Manager architecture: [data-manager-agent.md](data-manager-agent.md)
> - Fund schema reference: [fund-data-schema.md](fund-data-schema.md)
> - Current draft source: [data-extraction](../data-extraction)

---

## 1. Overview

### 1.1 Problem

The existing pipeline can download report PDFs into local ingestion folders, but PDF content is not yet converted into normalized assets for:

1. semantic retrieval (Milvus),
2. structured reporting/query (PostgreSQL),
3. relationship reasoning (Neo4j).

As a result, report intelligence is underutilized in downstream analysis.

### 1.2 Objective

Introduce a Data Manager extraction capability that transforms PDF reports into a standard intermediate artifact—**including retrieval-oriented chunk units and metadata** suitable for agent RAG (§6)—and distributes it to the three databases through the existing `classifier -> transformer -> distributor` flow.

### 1.3 Scope

In scope:

1. Offline extraction flow in `data_manager` only.
2. New extraction task contract and data model.
3. Storage mapping for PostgreSQL, Neo4j, Milvus.
4. CLI design and phased rollout.

Out of scope (this phase):

1. Changes to realtime `/chat` orchestration.
2. Distributed processing and advanced scheduler mechanics.
3. Full-fidelity reconstruction of all complex PDF tables.

---

## 2. Design Principles

1. **Contract-first:** Reuse existing `task_type + metadata + content` conventions.
2. **Incremental delivery:** Ship a minimal stable version first (V1), then improve quality.
3. **Idempotency:** Re-runs must not create duplicate facts or vectors.
4. **Traceability:** Every extracted artifact must include source and extractor version.
5. **Replaceable parser layer:** Parser implementation can evolve without breaking downstream schemas.

---

## 3. Integration with Existing Data Manager

### 3.1 Position in Current Pipeline

```text
collect (already downloads reports/*.pdf)
    -> extract-reports (new)
        parse -> normalize -> chunk -> retrieval enrichment -> signals
    -> generated extraction JSON artifacts
    -> distribute (existing)
    -> PostgreSQL / Neo4j / Milvus
```

The **retrieval enrichment** step materializes retrieval-oriented chunks and metadata defined in §6; it may be minimal in Phase V1 until table-derived units are enabled.

### 3.2 Responsibilities by Component

1. **Collector stage**: Ensures PDF files are locally available.
2. **Extractor stage (new)**: Produces normalized report artifacts and applies the **retrieval-oriented layer** (§6) so Milvus-bound content is semantically and metadata-aligned for downstream agents.
3. **Classifier stage**: Routes extraction task outputs to target databases.
4. **Transformer stage**: Converts normalized content to DB-specific payloads.
5. **Distributor stage**: Performs idempotent writes via existing MCP tools.

---

## 4. Extraction Task Contract

### 4.1 New Task Type

- `cn_fund_report_extract`

### 4.2 Standard Artifact Shape

```json
{
  "metadata": {
    "fund_id": "001235",
    "task_type": "cn_fund_report_extract",
    "as_of_date": "2026-03-20",
    "collected_at": "2026-03-24T10:30:00Z",
    "source": "pdf_report_extractor",
    "report_id": "AN202503311649442687",
    "report_type": "annual",
    "report_date": "2025-12-31",
    "extractor_version": "v1",
    "parser_name": "docling",
    "parser_version": "2.64.x"
  },
  "content": {
    "sections": [
      {
        "section_id": "strategy",
        "section_title_raw": "Investment Strategy",
        "text": "...",
        "summary": "..."
      }
    ],
    "chunks": [
      {
        "chunk_id": "AN202503311649442687-strategy-0001",
        "chunk_kind": "narrative",
        "text": "...",
        "fund_id": "001235",
        "section_id": "strategy",
        "chunk_index": 1,
        "report_id": "AN202503311649442687",
        "report_type": "annual",
        "report_date": "2025-12-31",
        "extractor_version": "v1",
        "parser_name": "docling",
        "parser_version": "2.64.x"
      }
    ],
    "signals": {
      "strategy": "...",
      "risk": "...",
      "sector_preference": ["Technology", "Healthcare"],
      "market_view": "...",
      "style": "growth"
    }
  }
}
```

### 4.3 Required Metadata Fields

1. `fund_id`
2. `task_type`
3. `report_id`
4. `report_type`
5. `report_date`
6. `collected_at`
7. `source`
8. `extractor_version`
9. `parser_name` — **V1 fixed value:** `docling` (identifies which parser produced the raw blocks; enables A/B tests and future non-Docling parsers).
10. `parser_version` — **V1 pinned range:** `2.64.x` (Docling minor version is pinned for reproducibility; see §5.1).

Per-chunk objects in `content.chunks` MUST include **`chunk_kind`** when those objects are indexed for retrieval; see §6.5.

---

## 5. Processing Flow Specification

### 5.0 Parser selection (V1 — provisional)

**V1 default / temporary choice:** [Docling](https://github.com/docling-project/docling) is the **canonical parser implementation** for Phase V1.

**V1 pinned version:** Docling **2.64.x** (recommend dependency range `>=2.64,<2.65`). This is treated as an implementation constraint so extraction output remains stable enough for validation and regression. The architecture remains **parser-abstracted** so V2+ can add alternatives (OCR-heavy PDFs, vendor-specific layouts) without changing the downstream artifact contract.

| Phase | Parser (planned) | Notes |
|-------|------------------|-------|
| **V1** | **Docling** | Primary path; map Docling document structure into internal blocks, then shared normalize/chunk/signal pipeline. |
| V2+ | TBD | Optional second parser behind the same `Parser` interface; selection via config or `metadata.parser_name`. |

**Non-goals for V1 Docling path:** Perfect table extraction and scanned-page OCR are **not** required for V1; treat table-like regions as text where Docling exposes them, and defer high-fidelity tables to Phase V3.

### 5.1 Parse

Input: report PDF path.  
Output: **internal** `ParsedDocument` structure: ordered list of logical blocks `{ kind, text, optional: page, source_ref }` where `kind` is one of `heading`, `paragraph`, `table_text` (implementation-defined; must be serializable for debugging).

**V1 implementation:** Use Docling’s document API to walk the converted document and emit blocks. Exact API calls are left to the implementation, but the **contract to Normalize** is: stable reading order and preserved heading hierarchy where Docling provides it.

**Docling → internal blocks (reference mapping for implementers):**

1. Map Docling **section titles / headings** to `kind=heading` blocks (`text` = title string).
2. Map **body text** (paragraphs, list items) to `kind=paragraph` blocks; concatenate or split per implementation policy, but preserve order.
3. Map **tables** to `kind=table_text` when Docling exports tabular content as text or markdown-like rows; do not assume a fixed schema in V1.
4. If Docling exposes **page numbers** or **provenance**, attach minimal `page` / `source_ref` on each block for audit and debugging (optional but recommended).

**Dependency posture (implementation guidance):**

1. Add Docling as an **optional extra** (e.g. `pip install -e ".[report-extract]"` or equivalent) so environments without PDF extraction still install the core repo.
2. Pin Docling to **2.64.x** when implementation lands. Recommended spec:
   - `docling>=2.64,<2.65`
   - (or a fully pinned exact version if you use a lockfile)
3. Persist `parser_version` in artifact metadata so you can audit which Docling minor version produced a given extraction output.
4. Bump `extractor_version` when parser version or mapping rules change materially.

**Installation example (implementation guidance):**

```bash
pip install "docling>=2.64,<2.65"
```

**Failure and fallback (V1):**

1. If Docling raises or returns unusable output for a PDF: record error in artifact or sidecar log, **skip** that file in the batch (per-file isolation).  
2. **Optional** V1 fallback (config-gated): plain text extraction (e.g. `pypdf`) **only** to unblock smoke runs — if enabled, set `metadata.parser_name` to e.g. `pypdf_fallback` and increment or suffix `extractor_version` so Milvus/Postgres rows remain auditable. Default for production-like runs: Docling only.

Requirements (unchanged):

1. Parser implementation must remain swappable behind a single `parse(pdf_path) -> ParsedDocument` (or equivalent) boundary.
2. Parser failures must be isolated per file.

### 5.2 Normalize

Normalization rules:

1. Section title mapping to canonical section IDs.
2. Noise removal (headers/footers/legal boilerplate/repeated paragraphs).
3. Short-paragraph merge for readability and embedding quality.
4. Preserve raw title in `section_title_raw`.

Canonical section IDs (V1):

- `objective`
- `strategy`
- `risk`
- `performance`
- `manager_view`
- `market_outlook`
- `other`

### 5.3 Chunking

Policy:

1. Split by section first.
2. Then split by length (recommended 600-900 chars).
3. Add small overlap (recommended 80-120 chars).

Refinements for **semantic boundaries** (paragraph / low-level headings before length splitting) are specified in §6.4.

Each chunk must carry filterable context (align with CN ingestion: use **`fund_id`**, not ticker `symbol`):

- `fund_id`, `report_id`, `report_type`, `report_date`, `section_id`, `chunk_index`, `extractor_version`, `parser_name`, **`chunk_kind`** (§6.5)

**Milvus / distributor note:** Existing `vector_tool.upsert_documents` may use a scalar field named `symbol` in some code paths; for CN report chunks, implementation should map **`fund_id` → that field** (or extend schema) so filters remain consistent. Document the chosen mapping in `fund-data-schema.md` when implemented.

### 5.4 Signal Extraction

V1 target fields:

1. `strategy`
2. `risk`
3. `sector_preference`
4. `market_view`
5. `style`

Behavior:

1. On extraction error, emit empty/default values plus error note.
2. Do not fail the entire report unless no valid section text exists.

---

## 6. Retrieval-Oriented Asset Layer

Parser output (including Docling) optimizes for **structural fidelity** relative to the source PDF. **Agent retrieval** (dense search, tool-filtered fetch, and citation) needs assets tuned for **semantic overlap with user language**, **metadata filtering**, and **traceable provenance**. This section defines a **retrieval-oriented layer**: rules and optional fields that sit on top of §5.2–§5.4 and feed Milvus-oriented payloads. It does **not** replace the canonical artifact contract in §4; it constrains how implementations derive **vector-bound units** and **extended scalars**.

### 6.1 Pipeline placement

```text
parse (§5.1)
  -> normalize (§5.2)
  -> primary chunking for prose (§5.3, refined by §6.4)
  -> retrieval enrichment (§6.4–§6.7): semantic splits, derived units, metadata
  -> signal extraction (§5.4)
  -> artifact JSON (§4.2)
  -> distribute -> Milvus / PostgreSQL / Neo4j (§7)
```

Implementations MAY combine “primary chunking” and “retrieval enrichment” in one internal pass if emitted artifacts are equivalent.

**Responsibility split:**

1. **Normalize** retains section assignment, raw titles, and table sources (e.g. `headers` / `rows` in `content.tables` where present).
2. **Primary chunking** produces **`chunk_kind: narrative`** units from continuous prose.
3. **Retrieval enrichment** adds **`table_derived`** and optional **`table_summary`** units (§6.6), and attaches **retrieval metadata** (§6.5, §6.7) for indexing.

### 6.2 Design principles

1. **Auditability:** Derived text must remain traceable to `report_id`, `section_id`, and a stable **`chunk_kind`**. Source tables SHOULD remain in the artifact for replay and regression.
2. **Template-first:** Prefer deterministic row-to-text templates (e.g. holdings weights) before defaulting to LLM paraphrase. If LLM rewrite becomes a default path for any stage, bump **`extractor_version`** and record the behavior in release notes.
3. **Determinism:** Same PDF inputs, parser version, and `extractor_version` MUST yield the same derived chunks (no nondeterministic prompts in the default pipeline).
4. **Filter-first metadata:** Every Milvus-target unit carries the §5.3 filter set plus **`chunk_kind`** (§6.6). Optional scalars (§6.7) MUST NOT be required for correctness of basic retrieval in V1.

### 6.3 Retrieval failure modes addressed

Without this layer, typical gaps are:

1. **Tables:** Embedding raw grids yields weak overlap with natural questions (e.g. user asks about “top holdings” while vectors encode isolated `"Name 8.5%"` cells).
2. **Chunks:** Length-only splits fracture sentences and mix themes within one embedding.
3. **Filters:** Sparse metadata limits section-specific precision.

### 6.4 Semantic chunking refinements

Extend §5.3 as follows (section boundaries remain primary):

1. Prefer split points at **paragraph** or **low-level heading** boundaries produced during normalize.
2. Apply target length (600–900 characters) and overlap (80–120 characters) **within** each semantic segment.
3. Avoid mid-sentence breaks unless a single paragraph exceeds the maximum length budget.

### 6.5 Retrieval unit kinds

Each chunk object in `content.chunks` that is intended for Milvus indexing MUST include:

| Field | Description |
|-------|-------------|
| `chunk_kind` | `narrative` (prose from §5.3 / §6.4) \| `table_derived` \| `table_summary` (extensible in `fund-data-schema.md`) |
| `text` | The string passed to the embedding model. For `table_derived`, this is **template-expanded natural language** with explicit topical context (e.g. holdings, sector allocation). |

All units MUST still carry the §5.3 context fields: `chunk_id`, `fund_id`, `section_id`, `chunk_index`, `report_id`, `report_type`, `report_date`, `extractor_version`, `parser_name`, `parser_version`.

**Semantics:**

- **`narrative`:** Default prose chunks.
- **`table_derived`:** One or more chunks synthesized from a table’s headers and rows using **deterministic** templates in early phases; section SHOULD reflect the table’s thematic placement (e.g. `strategy`, `performance`, or `other` when unknown).
- **`table_summary`:** Optional short abstract for high-recall retrieval; may be template- or model-generated in later phases.

**Uniqueness:** `chunk_index` (or `chunk_id`) MUST be unique per `(report_id, extractor_version)` across all `chunk_kind` values, or `chunk_id` MUST encode `chunk_kind` to avoid collisions. Document the chosen rule in `fund-data-schema.md`.

### 6.6 Table handling: three-way output

For each table retained in the artifact (structured `headers` + `rows`, or equivalent):

1. **Natural language for embedding (required once tables are indexed):** Emit at least one **`table_derived`** chunk so colloquial queries align with embeddings. Do not use **only** serialized grid JSON as the sole Milvus payload when templated prose is feasible.
2. **Structured records for PostgreSQL (phase-gated):** Map rows to typed JSON or relational columns when fund-schema mappings exist (align with §10.3). Keep structured storage separate from the embedded string.
3. **Optional `table_summary` chunk:** Concise paragraph per table or logical table group; recommended from Phase V2+ if LLM-backed summaries are introduced under version control.

### 6.7 Extended Milvus metadata (optional)

Beyond §7.3, implementations SHOULD add scalar fields as collection schema permits:

1. **`chunk_kind`** — filter narrative vs. table-derived hits.
2. **`content_year`** — integer derived from `report_date` for time-bounded queries.
3. **`importance`** — optional rule-based hint (e.g. elevate `strategy` / `risk` sections); avoid noisy auto-keyword fields in V1.

**Query expansion (non-normative for V1):** Prepending or concatenating synthetic user questions, or storing a second vector per chunk, MAY be adopted in a future `extractor_version`; embedding layout MUST be documented in `fund-data-schema.md` before production use.

### 6.8 Phase alignment

| Phase | Retrieval layer expectation |
|-------|----------------------------|
| **V1** | Narrative chunks + §5.3 metadata; `content.tables` MAY ship without `table_derived` Milvus rows until implemented. |
| **V2** | Semantic chunking (§6.4); optional `table_summary`; Neo4j from signals (§7.2). |
| **V3** | **`table_derived` required** for ingested tables sent to Milvus; structured row mapping to fund tables; quality monitoring. |

### 6.9 Non-goals

1. Replacing §4 artifacts with a raw Docling JSON graph as the Milvus source of truth.
2. Unbounded LLM rewrite of full reports without regression fixtures and version bumps.
3. Guaranteeing correct financial semantics for every arbitrary PDF table layout in early phases.

---

## 7. Storage Model by Database

### 7.1 PostgreSQL

Recommended new tables:

1. `cn_fund_report_sections`
2. `cn_fund_report_signals`

Suggested unique keys:

1. sections: `(fund_id, report_id, section_id)`
2. signals: `(fund_id, report_id)`

Minimum section columns:

- `fund_id`, `report_id`, `section_id`, `section_title_raw`, `section_text`, `section_summary`, `report_type`, `report_date`, `collected_at`, `extractor_version`

Minimum signal columns:

- `fund_id`, `report_id`, `strategy`, `risk`, `market_view`, `style`, `sector_preference_json`, `collected_at`, `extractor_version`

### 7.2 Neo4j

Recommended relationship model:

1. `(Fund)-[:REPORT_STYLE {report_id, report_date}]->(Style)`
2. `(Fund)-[:FOCUS_ON {report_id, report_date}]->(Theme)`

Constraints:

1. Use MERGE semantics for idempotency.
2. Only write explicit/defensible relationships from extracted signals.

### 7.3 Milvus

Storage granularity: chunk-level documents.

Document ID recommendation:

- `report_id-section_id-chunk_index`

Required filter dimensions:

1. `section_id`
2. `report_type`
3. `report_date`
4. `fund_id` (may be stored under Milvus field name `symbol` until schema is extended — see §5.3)
5. `report_id`
6. `parser_name` (recommended for debugging and regression)

This enables section-aware retrieval, time-constrained retrieval, and—when implemented—**`chunk_kind`**-aware filtering (§6.7).

---

## 8. CLI and File Layout

### 8.1 Proposed CLI

1. `python -m data_manager extract-reports --fund-id 001235 --date 2026-03-20`
2. `python -m data_manager extract-reports --all --date 2026-03-20`
3. `python -m data_manager extract-reports --symbol 001235 --date 2026-03-20` (backward-compatible alias)

CLI alignment notes:

1. Keep command style aligned with existing `data_manager` workflows (`collect`, `distribute`, and optional wrapper flows).
2. `extract-reports` should be treated as an offline stage command that integrates into the same background pipeline (not a realtime `/chat` entrypoint).
3. Prefer `--fund-id` as the primary argument name for CN domain consistency; `--symbol` can be kept as backward-compatible alias if needed.

### 8.2 Input/Output Paths

Input PDFs:

- `datasets/raw/ingestion/cn_fund_all/<date>/<fund_id>/reports/*.pdf`

Extraction artifacts:

- `datasets/raw/ingestion/cn_fund_all/<date>/<fund_id>/reports_extracted/<report_id>.json`

Path alignment notes:

1. Keep artifacts under `datasets/raw/ingestion/...` so extraction output follows the same raw-layer convention as ingestion.
2. `report_id` should be used in artifact filenames to support deterministic re-runs and idempotency checks.

---

## 9. Idempotency, Error Handling, and Auditability

### 9.1 Idempotency Key

Recommended unique identity for extraction artifacts:

- `(fund_id, report_id, extractor_version)`

### 9.2 Error Handling

1. Per-file failure isolation (batch continues).
2. Structured error payload for parse/extract failures.
3. Distributor-level partial success allowed when at least one target write succeeds.

### 9.3 Audit Fields

All records should preserve:

1. `source`
2. `collected_at`
3. `extractor_version`
4. `report_id`

---

## 10. Phased Delivery Plan

### 10.1 Phase V1 (Minimum Viable Extraction)

1. **Parse with Docling** (see §5.0) → internal blocks → normalize + chunk + minimal retrieval metadata (`chunk_kind: narrative` where indexed).
2. Generate `cn_fund_report_extract` artifacts (`metadata.parser_name: docling`, `extractor_version` set per release).
3. Write to PostgreSQL (sections/signals) and Milvus (chunks).
4. Verify end-to-end on one fund across multiple reports.

**Implementation checklist (for codegen / PR review):**

1. New module e.g. `data_manager/report_extraction/` (or flat `data_manager/report_extractor.py`) with: Docling-backed `parse`, section normalization, chunking, optional signal extract stub.
2. CLI `extract-reports` in `data_manager/__main__.py` wired to scan `reports/*.pdf` and write `reports_extracted/<report_id>.json`.
3. Extend `DataClassifier` / `DataTransformer` / `DataDistributor` + `schemas.py` for `cn_fund_report_extract` and new PG tables.
4. Optional dependency group in `pyproject.toml` for Docling.
5. Unit tests with **fixture PDF** or mocked `ParsedDocument` (no network); one integration test optional with Docling if CI allows.
6. When Milvus indexing is enabled, each indexed chunk carries **`chunk_kind`** per §6.5 (V1 may use only `narrative`).

### 10.2 Phase V2 (Structured Quality Enhancement)

1. Improve section mapping robustness.
2. Apply semantic chunking refinements (§6.4).
3. Add Neo4j relationship writes (§7.2).
4. Add section-level and report-level summaries; optional **`table_summary`** chunks (§6.6).

### 10.3 Phase V3 (Table-focused Enhancement)

1. Optional dedicated table parser integration for holdings/sector tables (in addition to Docling-derived tables).
2. Emit mandatory **`table_derived`** Milvus units for ingested tables (§6.6); map structured rows into existing fund schema tables.
3. Add extraction quality monitoring and alerts.

---

## 11. Acceptance Criteria

1. PDF reports can be converted into standard extraction JSON artifacts.
2. `distribute` can process `cn_fund_report_extract` outputs without custom one-off scripts.
3. V1 writes are successful for at least PostgreSQL + Milvus.
4. Re-running the same report with the same extractor version does not duplicate data.
5. Records are traceable through source/version/timestamps.
6. Indexed chunks declare **`chunk_kind`** and comply with §6.5–§6.7 as phases require.

---

## 12. Risks and Mitigations

1. **Heterogeneous PDF layouts**  
   Mitigation: parser abstraction + section fallback to `other`.

2. **Docling version / model drift**  
   Mitigation: pin Docling to **2.64.x** in optional extras; record `parser_name` + `parser_version` + `extractor_version`; maintain a small golden PDF set for regression.

3. **Extraction instability across versions**  
   Mitigation: explicit `extractor_version`, sample-based regression checks.

4. **Complex table parsing quality**  
   Mitigation: retain structured tables in the artifact; defer **`table_derived`** Milvus payloads to Phase V3 where needed (§6.6); optional dedicated table tooling in V3.

5. **Scanned PDFs / OCR**  
   Mitigation: out of scope for V1 Docling path; flag low text yield in metadata for later OCR phase.

6. **Cross-database consistency drift**  
   Mitigation: idempotent writes + batch result reconciliation.

---

## 13. Documentation Synchronization Requirements

When implementation starts, update:

1. `docs/data_prep/data-manager-agent.md` (new extract-reports flow)
2. `docs/data_prep/cn-fund-data-schema.md` (CN report extraction schema: sections/signals tables; `chunk_kind` and optional Milvus scalars per §6.7)
3. `docs/workflow/90_product/progress.md` (stage progress and commands)
4. `CHANGELOG.md` (notable feature release entry)

