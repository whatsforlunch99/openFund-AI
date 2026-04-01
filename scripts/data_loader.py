#!/usr/bin/env python3
"""
Single-file data loader used by ./scripts/run.sh to populate:
- PostgreSQL: from database/stats_data/*.csv
- Neo4j: from database/graph_data/neo4j_export/*.csv
- Milvus: from database/text_data/*.json

Design goals:
- Idempotent "existing" mode (upsert/append semantics).
- Optional "fresh-all" mode (drop SQL tables, wipe Neo4j, delete Milvus docs).
- Env gating: skip components when their backing services are not configured.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

# #region agent log
_DEBUG_LOG_PATH = Path(__file__).resolve().parent.parent / ".cursor" / "debug-11fd1a.log"


def _agent_dbg(hypothesis_id: str, location: str, message: str, data: Optional[dict[str, Any]] = None) -> None:
    try:
        line = json.dumps(
            {
                "sessionId": "11fd1a",
                "hypothesisId": hypothesis_id,
                "location": location,
                "message": message,
                "data": data or {},
                "timestamp": int(time.time() * 1000),
            },
            default=str,
        )
        _DEBUG_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _DEBUG_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# #endregion


_IDENTIFIER_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def _quote_ident(ident: str) -> str:
    """
    Identifier helper for SQL statements.

    Important: we intentionally do *not* double-quote identifiers so Postgres folds
    them to lowercase. This keeps generated SQL simple (no mandatory `"quoteType"` quotes).
    """
    s = (ident or "").strip()
    if not s:
        return "col"
    s = s.lower()
    if not _IDENTIFIER_RE.match(s):
        s = re.sub(r"[^a-z0-9_]+", "_", s)
        if not s or not _IDENTIFIER_RE.match(s):
            s = "col"
    return s


def _safe_table_name(stem: str) -> str:
    """
    Turn a CSV stem (e.g. `yahoo_quote_metrics`) into a safe SQL table name.
    """
    s = (stem or "").strip().lower()
    s = re.sub(r"[^a-z0-9_]+", "_", s)
    if not s:
        s = "table"
    if not _IDENTIFIER_RE.match(s):
        # Ensure it starts with a letter/underscore.
        s = "t_" + re.sub(r"^[^a-z_]+", "", s)
        s = s or "t_table"
    return s


def _discover_stats_csvs(stats_dir: Path) -> list[Path]:
    if not stats_dir.exists() or not stats_dir.is_dir():
        return []
    return sorted([p for p in stats_dir.glob("*.csv") if p.is_file()])


def _read_csv_header(csv_path: Path) -> list[str]:
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        header = next(reader, [])
    return [h.strip() for h in header if h.strip()]


def _infer_sql_type(col: str) -> str:
    c = col.strip().lower()

    if c in {"date"} or c.endswith("_date") or c.endswith("_on"):
        return "DATE"
    if "timestamp" in c:
        return "TIMESTAMP"

    # Obvious identifiers / strings
    if any(
        token in c
        for token in (
            "symbol",
            "source_url",
            "url",
            "matched_name",
            "quote_type",
            "quotetype",
            "metric_source",
            "metric_group",
            "metric_name",
            "status",
            "currency",
            "index_id",
            "source",
        )
    ):
        return "TEXT"

    # Numeric-ish fields used in repo stats_data.
    numeric_tokens = (
        "price",
        "change",
        "percent",
        "prev_close",
        "open",
        "volume",
        "avg_volume",
        "beta",
        "pe_",
        "eps",
        "target",
        "day_low",
        "day_high",
        "week_52_low",
        "week_52_high",
        "bid_price",
        "bid_size",
        "ask_price",
        "ask_size",
        "forward_dividend",
        "forward_yield",
        "market_cap_intraday_parsed",
        "metric_value",
        "confidence",
        "level_",
        "total_return_level",
        "ma_",
        "rsi",
        "macd",
        "bb_",
        "stoch_",
    )
    if any(tok in c for tok in numeric_tokens):
        return "DOUBLE PRECISION"

    # Default conservative: keep as TEXT.
    return "TEXT"


def _infer_pk_columns(columns: list[str]) -> list[str]:
    cols_lower = {c.lower(): c for c in columns}

    # Quote metrics: (symbol, timestamp)
    if "symbol" in cols_lower and "timestamp" in cols_lower:
        return [cols_lower["symbol"], cols_lower["timestamp"]]
    # Timeseries: (symbol, date)
    if "symbol" in cols_lower and "date" in cols_lower:
        return [cols_lower["symbol"], cols_lower["date"]]
    # Fundamentals metrics: multiple rows per symbol at an as_of timestamp.
    if (
        "symbol" in cols_lower
        and "as_of_timestamp" in cols_lower
        and "metric_group" in cols_lower
        and "metric_name" in cols_lower
    ):
        return [
            cols_lower["symbol"],
            cols_lower["as_of_timestamp"],
            cols_lower["metric_group"],
            cols_lower["metric_name"],
        ]
    # If we at least have an as_of_timestamp, use it to avoid overwriting.
    if "symbol" in cols_lower and "as_of_timestamp" in cols_lower:
        return [cols_lower["symbol"], cols_lower["as_of_timestamp"]]

    # Index symbol map: (symbol)
    if "symbol" in cols_lower:
        return [cols_lower["symbol"]]

    # Fallback: use first column.
    return [columns[0]] if columns else ["id"]


def _parse_date(value: str) -> Optional[dt.date]:
    v = (value or "").strip()
    if not v or v == "--":
        return None
    try:
        return dt.date.fromisoformat(v)
    except ValueError:
        # Best-effort parse for non-iso dates.
        return None


def _parse_timestamp(value: str) -> Optional[dt.datetime]:
    v = (value or "").strip()
    if not v or v == "--":
        return None
    try:
        return dt.datetime.fromisoformat(v)
    except ValueError:
        return None


def _parse_double(value: str) -> Optional[float]:
    """
    Parse values like:
    - "3.737T" => 3.737e12
    - "51.899B" => 51.899e9
    - "--" / "" => None
    """
    v = (value or "").strip()
    if not v or v == "--":
        return None
    v = v.replace(",", "")
    suffix_mult = {"k": 1e3, "m": 1e6, "b": 1e9, "t": 1e12}
    last = v[-1].lower() if v else ""
    if last in suffix_mult:
        num = v[:-1].strip()
        try:
            return float(num) * suffix_mult[last]
        except ValueError:
            return None
    try:
        return float(v)
    except ValueError:
        return None


def _parse_value(value: str, sql_type: str) -> Any:
    if sql_type == "DATE":
        return _parse_date(value)
    if sql_type == "TIMESTAMP":
        return _parse_timestamp(value)
    if sql_type == "DOUBLE PRECISION":
        return _parse_double(value)
    # TEXT default
    v = (value or "").strip()
    return v if v and v != "--" else None


@dataclass(frozen=True)
class ColumnSpec:
    name: str
    sql_type: str


@dataclass(frozen=True)
class TableSpec:
    table_name: str
    csv_path: Path
    columns: list[ColumnSpec]
    pk_columns: list[str]

    def create_table_sql(self) -> str:
        cols_sql = ", ".join(
            f"{_quote_ident(c.name)} {c.sql_type}" for c in self.columns
        )
        pk_sql = ""
        if self.pk_columns:
            pk_sql = f", PRIMARY KEY ({', '.join(_quote_ident(c) for c in self.pk_columns)})"
        return f"CREATE TABLE IF NOT EXISTS {_quote_ident(self.table_name)} ({cols_sql}{pk_sql});"

    def drop_table_sql(self) -> str:
        return f"DROP TABLE IF EXISTS {_quote_ident(self.table_name)} CASCADE;"

    def upsert_sql(self) -> str:
        all_cols = [c.name for c in self.columns]
        non_pk = [c for c in all_cols if c not in set(self.pk_columns)]
        placeholders = ", ".join(["%s"] * len(all_cols))
        if not non_pk:
            # If there's nothing besides the PK, use DO NOTHING.
            conflict = f"ON CONFLICT ({', '.join(_quote_ident(c) for c in self.pk_columns)}) DO NOTHING"
            return (
                f"INSERT INTO {_quote_ident(self.table_name)} ({', '.join(_quote_ident(c) for c in all_cols)}) "
                f"VALUES ({placeholders}) {conflict}"
            )

        set_clause = ", ".join(
            f"{_quote_ident(c)} = EXCLUDED.{_quote_ident(c)}" for c in non_pk
        )
        return (
            f"INSERT INTO {_quote_ident(self.table_name)} ({', '.join(_quote_ident(c) for c in all_cols)}) "
            f"VALUES ({placeholders}) "
            f"ON CONFLICT ({', '.join(_quote_ident(c) for c in self.pk_columns)}) DO UPDATE SET {set_clause}"
        )


def _build_table_specs(stats_dir: Path) -> list[TableSpec]:
    specs: list[TableSpec] = []
    for csv_path in _discover_stats_csvs(stats_dir):
        stem = csv_path.stem
        table_name = _safe_table_name(stem)
        columns = _read_csv_header(csv_path)
        if not columns:
            continue
        pk = _infer_pk_columns(columns)
        col_specs = [ColumnSpec(name=c, sql_type=_infer_sql_type(c)) for c in columns]
        specs.append(
            TableSpec(
                table_name=table_name,
                csv_path=csv_path,
                columns=col_specs,
                pk_columns=pk,
            )
        )
    return specs


def _iter_csv_rows(csv_path: Path, columns: list[str]) -> Iterable[list[str]]:
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            yield [row.get(c, "") for c in columns]


def _postgres_connect() -> tuple[Any | None, str | None]:
    url = os.environ.get("DATABASE_URL")
    if not url:
        return None, None
    try:
        import psycopg2  # type: ignore[import-untyped]
    except ImportError:
        return None, "PostgreSQL driver not installed. Run: pip install -e '.[backends]'"

    try:
        _agent_dbg("H1", "data_loader._postgres_connect", "before psycopg2.connect", {"url_host": url.split("@")[-1][:80] if "@" in url else "local"})
        conn = psycopg2.connect(url)
        _agent_dbg("H1", "data_loader._postgres_connect", "after psycopg2.connect", {})
        return (conn, None)
    except Exception as e:
        return None, f"PostgreSQL connection failed: {e}"


def load_sql_from_stats(stats_dir: Path, load_mode: str) -> dict[str, Any]:
    if load_mode == "skip":
        return {"sql": {"skipped": True}}
    if not os.environ.get("DATABASE_URL"):
        return {"sql": {"skipped": True, "reason": "DATABASE_URL not set"}}

    _agent_dbg("H1", "data_loader.load_sql_from_stats", "entering sql load", {"stats_dir": str(stats_dir)})
    conn, conn_err = _postgres_connect()
    if conn is None:
        return {"sql": {"skipped": True, "reason": conn_err or "PostgreSQL unavailable"}}

    import psycopg2  # type: ignore[import-untyped]

    specs = _build_table_specs(stats_dir)
    if not specs:
        conn.close()
        return {"sql": {"skipped": True, "reason": f"No CSVs found in {stats_dir}"}}

    table_names = [s.table_name for s in specs]
    out: dict[str, Any] = {"tables": table_names, "stats_dir": str(stats_dir)}

    try:
        with conn:
            with conn.cursor() as cur:
                if load_mode == "fresh-all":
                    for spec in specs:
                        cur.execute(spec.drop_table_sql())

                for spec in specs:
                    cur.execute(spec.create_table_sql())

                    cols = [c.name for c in spec.columns]
                    upsert_sql = spec.upsert_sql()
                    inserted = 0
                    batch: list[tuple[Any, ...]] = []
                    pk_set = set(spec.pk_columns)

                    for values in _iter_csv_rows(spec.csv_path, cols):
                        row_dict = dict(zip(cols, values))
                        pk_ok = True
                        for pk_col in spec.pk_columns:
                            if not (row_dict.get(pk_col) or "").strip():
                                pk_ok = False
                                break
                        if not pk_ok:
                            continue

                        parsed = tuple(
                            _parse_value(str(v or ""), c.sql_type)
                            for v, c in zip(values, spec.columns)
                        )
                        batch.append(parsed)
                        if len(batch) >= 500:
                            # executemany keeps the loader compatible with stdlib psycopg2 installs.
                            # (Avoid execute_values dependency variations.)
                            cur.executemany(upsert_sql, batch)
                            inserted += len(batch)
                            batch = []

                    if batch:
                        cur.executemany(upsert_sql, batch)
                        inserted += len(batch)

                    out[spec.table_name] = {"rows_upserted": inserted}
        return {"sql": out, "status": "ok"}
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        return {"sql": {"error": str(e), "tables": table_names}, "status": "error"}
    finally:
        try:
            conn.close()
        except Exception:
            pass


def load_neo4j_from_csv_bundle(neo4j_csv_dir: Path, load_mode: str) -> dict[str, Any]:
    if load_mode == "skip":
        return {"neo4j": {"skipped": True}}
    if not os.environ.get("NEO4J_URI"):
        return {"neo4j": {"skipped": True, "reason": "NEO4J_URI not set"}}

    out: dict[str, Any] = {}

    # Bundle mode uses output_dir graph_nodes.csv and graph_relationships.csv.
    _agent_dbg("H2", "data_loader.load_neo4j", "before import kg_tool", {})
    from openfund_mcp.tools import kg_tool

    _agent_dbg("H2", "data_loader.load_neo4j", "before validate_graph_csv_bundle", {"dir": str(neo4j_csv_dir)})
    validation = kg_tool.validate_graph_csv_bundle_for_neo4j(
        str(neo4j_csv_dir), sample_limit=20
    )
    out["validation"] = validation
    _agent_dbg("H2", "data_loader.load_neo4j", "after validate", {"ok": validation.get("ok")})
    if validation.get("ok") is False and validation.get("error"):
        # Validation error: avoid doing a write when inputs are invalid.
        return {"neo4j": out, "status": "error", "error": validation.get("error")}

    if load_mode == "fresh-all":
        # "fresh-all" semantics: wipe the entire graph, then append-load.
        wipe = "MATCH (n) DETACH DELETE n"
        out["wipe_result"] = kg_tool.query_graph(wipe)

    _agent_dbg("H2", "data_loader.load_neo4j", "before load_graph_csvs_to_neo4j", {})
    res = kg_tool.load_graph_csvs_to_neo4j(
        nodes_csv="",
        relationships_csv="",
        mode="append",
        output_dir=str(neo4j_csv_dir),
    )
    _agent_dbg("H2", "data_loader.load_neo4j", "after load_graph_csvs_to_neo4j", {"err": (res or {}).get("error") if isinstance(res, dict) else None})
    out["load_result"] = res
    return {"neo4j": out, "status": "ok"}


def can_load_embedding_model_locally(model_name: str) -> bool:
    """
    Avoid embedding-model downloads during loader runs.
    """
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore[import-untyped]
    except ImportError:
        return False

    try:
        SentenceTransformer(model_name, local_files_only=True)
        return True
    except Exception:
        return False


def load_milvus_from_text_json(text_dir: Path, load_mode: str, *, force_download: bool = False) -> dict[str, Any]:
    if load_mode == "skip":
        return {"milvus": {"skipped": True}}
    if not os.environ.get("MILVUS_URI"):
        return {"milvus": {"skipped": True, "reason": "MILVUS_URI not set"}}

    from openfund_mcp.tools import vector_tool

    embed_model = os.environ.get("EMBEDDING_MODEL", vector_tool.DEFAULT_EMBEDDING_MODEL)
    if not force_download and not can_load_embedding_model_locally(embed_model):
        return {
            "milvus": {
                "skipped": True,
                "reason": "Embedding model not available locally (to avoid download hang).",
                "model_name": embed_model,
            }
        }

    # Convert all JSON array objects into Milvus docs.
    # Repo currently uses sample_text.json with content objects containing
    # {id, title, content, category}.
    json_paths = sorted([p for p in text_dir.glob("*.json") if p.is_file()])
    if not json_paths:
        return {"milvus": {"skipped": True, "reason": f"No JSON files in {text_dir}"}}

    docs: list[dict[str, Any]] = []
    for p in json_paths:
        with p.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            continue
        for r in data:
            if not isinstance(r, dict):
                continue
            doc_id = r.get("id")
            content = r.get("content") or r.get("title") or ""
            if not doc_id or not content:
                continue
            docs.append(
                {
                    "id": str(doc_id),
                    "content": str(content),
                    "fund_id": str(r.get("fund_id", "") or ""),
                    # Loader-owned docs so `fresh-all` can delete deterministically.
                    "source": "loader",
                }
            )

    if load_mode == "fresh-all":
        # Delete loader-owned docs then upsert.
        vector_tool.delete_by_expr('source == "loader"')

    _agent_dbg("H3", "data_loader.load_milvus", "calling upsert_documents", {"n_docs": len(docs)})
    res = vector_tool.upsert_documents(docs)
    _agent_dbg("H3", "data_loader.load_milvus", "after upsert_documents", {})
    return {"milvus": {"docs_count": len(docs), "upsert_result": res}, "status": "ok"}


def _map_run_funds_to_loader_mode(load_funds: str) -> str:
    """
    Backward compat for ./scripts/run.sh:
    - existing -> existing
    - fresh-all -> fresh-all
    - fresh-symbols -> existing (no symbol-scoped refresh supported in this loader)
    - skip -> skip
    """
    lf = (load_funds or "").strip()
    if lf == "fresh-all":
        return "fresh-all"
    if lf in {"existing", "fresh-symbols"}:
        return "existing"
    return "skip" if lf == "skip" else "existing"


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="OpenFund-AI data loader (SQL/Neo4j/Milvus).")
    ap.add_argument(
        "--load-mode",
        default="existing",
        choices=["existing", "fresh-all", "skip"],
        help="Idempotency mode.",
    )
    ap.add_argument(
        "--stats-dir",
        default=str(Path("database") / "stats_data"),
        help="Directory containing PostgreSQL stats CSVs.",
    )
    ap.add_argument(
        "--text-dir",
        default=str(Path("database") / "text_data"),
        help="Directory containing Milvus text JSON documents.",
    )
    ap.add_argument(
        "--neo4j-csv-dir",
        default=str(Path("database") / "graph_data" / "neo4j_export"),
        help="Directory containing graph_nodes.csv / graph_relationships.csv.",
    )
    ap.add_argument(
        "--milvus-force-download",
        action="store_true",
        help="Allow embedding-model download if not cached locally.",
    )
    args = ap.parse_args(argv)

    stats_dir = Path(args.stats_dir)
    text_dir = Path(args.text_dir)
    neo4j_csv_dir = Path(args.neo4j_csv_dir)

    overall: dict[str, Any] = {"load_mode": args.load_mode}

    _agent_dbg("H0", "data_loader.main", "start loader", {"load_mode": args.load_mode})
    sql_res = load_sql_from_stats(stats_dir, args.load_mode)
    _agent_dbg("H1", "data_loader.main", "sql phase done", {"keys": list(sql_res.keys()) if isinstance(sql_res, dict) else str(type(sql_res))})
    overall["sql"] = sql_res

    _agent_dbg("H2", "data_loader.main", "before neo4j phase", {})
    neo4j_res = load_neo4j_from_csv_bundle(neo4j_csv_dir, args.load_mode)
    _agent_dbg("H2", "data_loader.main", "neo4j phase done", {"status": neo4j_res.get("status") if isinstance(neo4j_res, dict) else None})
    overall["neo4j"] = neo4j_res

    _agent_dbg("H3", "data_loader.main", "before milvus phase", {})
    milvus_res = load_milvus_from_text_json(
        text_dir, args.load_mode, force_download=args.milvus_force_download
    )
    _agent_dbg("H3", "data_loader.main", "milvus phase done", {})
    overall["milvus"] = milvus_res

    print(json.dumps(overall, indent=2, default=str))

    # If all backends are skipped, still return 0.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

