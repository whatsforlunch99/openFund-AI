from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest


def _import_data_loader():
    repo_root = Path(__file__).resolve().parents[1]
    loader_path = repo_root / "scripts" / "data_loader.py"
    spec = importlib.util.spec_from_file_location("data_loader", loader_path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


DATA_LOADER = _import_data_loader()


def test_table_name_and_column_derivation_from_stats_csv_stems() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    stats_dir = repo_root / "database" / "stats_data"

    specs = DATA_LOADER._build_table_specs(stats_dir)
    table_names = {s.table_name for s in specs}
    assert "yahoo_quote_metrics" in table_names
    assert "yahoo_fundamentals_metrics" in table_names
    assert "yahoo_timeseries" in table_names
    assert "index_symbol_map" in table_names

    # Loader lowercases/normalizes identifiers; index_symbol_map has `quoteType` in CSV.
    idx_spec = next(s for s in specs if s.table_name == "index_symbol_map")
    create_sql = idx_spec.create_table_sql().lower()
    assert " quotetype " in create_sql or " quotetype," in create_sql


def test_neo4j_existing_mode_calls_append_only(monkeypatch: pytest.MonkeyPatch) -> None:
    from openfund_mcp.tools.graph import tool as kg_tool

    repo_root = Path(__file__).resolve().parents[1]
    neo4j_dir = repo_root / "database" / "graph_data" / "neo4j_export"

    monkeypatch.setenv("NEO4J_URI", "bolt://localhost:7687")

    called: dict[str, Any] = {}

    def _validate(*args, **kwargs):  # type: ignore[no-untyped-def]
        called["validate"] = {"args": args, "kwargs": kwargs}
        return {"ok": True}

    def _load_graph(*args, **kwargs):  # type: ignore[no-untyped-def]
        called["load_graph"] = {"args": args, "kwargs": kwargs}
        return {"ok": True}

    def _query_graph(*args, **kwargs):  # type: ignore[no-untyped-def]
        called["wipe_called"] = True
        return {"rows": []}

    monkeypatch.setattr(kg_tool, "validate_graph_csv_bundle_for_neo4j", _validate)
    monkeypatch.setattr(kg_tool, "load_graph_csvs_to_neo4j", _load_graph)
    monkeypatch.setattr(kg_tool, "query_graph", _query_graph)

    out = DATA_LOADER.load_neo4j_from_csv_bundle(neo4j_dir, load_mode="existing")
    assert out["status"] == "ok"
    assert "wipe_called" not in called
    assert "load_graph" in called
    assert called["load_graph"]["kwargs"]["mode"] == "append"
    assert Path(called["load_graph"]["kwargs"]["output_dir"]) == neo4j_dir


def test_neo4j_fresh_all_wipes_then_appends(monkeypatch: pytest.MonkeyPatch) -> None:
    from openfund_mcp.tools.graph import tool as kg_tool

    repo_root = Path(__file__).resolve().parents[1]
    neo4j_dir = repo_root / "database" / "graph_data" / "neo4j_export"

    monkeypatch.setenv("NEO4J_URI", "bolt://localhost:7687")
    monkeypatch.setenv("NEO4J_FRESH_IMPORT_MODE", "online")

    order: list[str] = []

    def _validate(*args, **kwargs):  # type: ignore[no-untyped-def]
        order.append("validate")
        return {"ok": True}

    def _wipe(*args, **kwargs):  # type: ignore[no-untyped-def]
        order.append("wipe")
        # Ensure DETACH DELETE is used for full wipe.
        assert "DETACH DELETE" in (args[0] if args else "") or "DETACH DELETE" in (kwargs.get("cypher") or "")
        return {"rows": []}

    def _load_graph(*args, **kwargs):  # type: ignore[no-untyped-def]
        order.append("load")
        return {"ok": True}

    monkeypatch.setattr(kg_tool, "validate_graph_csv_bundle_for_neo4j", _validate)
    monkeypatch.setattr(kg_tool, "query_graph", _wipe)
    monkeypatch.setattr(kg_tool, "load_graph_csvs_to_neo4j", _load_graph)

    out = DATA_LOADER.load_neo4j_from_csv_bundle(neo4j_dir, load_mode="fresh-all")
    assert out["status"] == "ok"
    assert order == ["validate", "wipe", "load"]


def test_milvus_fresh_all_deletes_loader_source_and_upserts(monkeypatch: pytest.MonkeyPatch) -> None:
    from openfund_mcp.tools.vector import tool as vector_tool

    repo_root = Path(__file__).resolve().parents[1]
    text_dir = repo_root / "database" / "text_data"

    monkeypatch.setenv("MILVUS_URI", "http://localhost:19530")

    # Avoid model availability checks / downloads.
    monkeypatch.setattr(DATA_LOADER, "can_load_embedding_model_locally", lambda _m: True)

    calls: dict[str, Any] = {}

    def _delete_by_expr(expr: str, collection_name: str | None = None):  # type: ignore[no-untyped-def]
        calls["delete_expr"] = expr
        return {"deleted": 123}

    def _upsert_documents(docs: list[dict[str, Any]]):  # type: ignore[no-untyped-def]
        calls["docs"] = docs
        return {"upserted": len(docs), "status": "ok"}

    monkeypatch.setattr(vector_tool, "delete_by_expr", _delete_by_expr)
    monkeypatch.setattr(vector_tool, "upsert_documents", _upsert_documents)

    out = DATA_LOADER.load_milvus_from_text_json(text_dir, load_mode="fresh-all")
    assert out["status"] == "ok"
    assert calls["delete_expr"] == 'source == "loader"'
    assert calls["docs"], "expected at least one parsed milvus doc from sample_text.json"
    assert all(d.get("source") == "loader" for d in calls["docs"])
    assert all("id" in d and "content" in d for d in calls["docs"])


def test_sql_env_gating_skips_when_database_url_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    stats_dir = repo_root / "database" / "stats_data"

    monkeypatch.delenv("DATABASE_URL", raising=False)
    out = DATA_LOADER.load_sql_from_stats(stats_dir, load_mode="existing")
    assert out["sql"]["skipped"] is True
    assert "DATABASE_URL" in out["sql"]["reason"]


def test_neo4j_db_name_parsing_from_uri() -> None:
    assert DATA_LOADER._neo4j_db_name_from_uri("bolt://localhost:7687") == "neo4j"
    assert DATA_LOADER._neo4j_db_name_from_uri("neo4j://localhost:7687") == "neo4j"
    assert DATA_LOADER._neo4j_db_name_from_uri("neo4j://localhost:7687/neo4j") == "neo4j"
    assert DATA_LOADER._neo4j_db_name_from_uri("neo4j+s://db.example.com/prod") == "prod"

