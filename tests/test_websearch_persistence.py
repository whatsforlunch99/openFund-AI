"""Tests for WebSearcher JSON persistence and semantic dedupe."""

from __future__ import annotations

import json
from pathlib import Path

from util.websearch_persistence import _build_milvus_id, persist_websearch_news


def test_persist_skips_when_no_news(tmp_path: Path) -> None:
    out = tmp_path / "web_searched_data.json"
    res = persist_websearch_news(
        news_items=[],
        symbols_mentioned=["SPY"],
        search_timestamp="2026-04-13T00:00:00Z",
        output_path=str(out),
    )
    assert res["stored"] == 0
    assert res["skipped"] == 0
    assert not out.exists()


def test_persist_adds_required_fields(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "util.websearch_persistence._upsert_new_records_to_milvus",
        lambda rows: {"upserted": len(rows), "status": "ok"},
    )
    out = tmp_path / "web_searched_data.json"
    monkeypatch.setattr(
        "util.websearch_persistence._embed_text",
        lambda text: ([1.0, 0.0, 0.0] if "SPY" in text else [0.0, 1.0, 0.0]),
    )
    res = persist_websearch_news(
        news_items=[
            {
                "title": "SPY rises on policy update",
                "summary": "ETF inflows pick up",
                "url": "https://reuters.com/a",
                "domain": "reuters.com",
                "source": "Reuters",
            }
        ],
        symbols_mentioned=["SPY", "VTI"],
        search_timestamp="2026-04-13T00:00:00Z",
        output_path=str(out),
    )
    assert res["stored"] == 1
    assert isinstance(res.get("milvus"), dict)
    assert res["milvus"]["upserted"] == 1
    data = json.loads(out.read_text(encoding="utf-8"))
    assert isinstance(data, list) and len(data) == 1
    row = data[0]
    assert row["id"] == 1
    assert row["title"] == "SPY rises on policy update"
    assert row["category"] == "Web Search"
    assert row["symbols_mentioned"] == ["SPY", "VTI"]
    assert row["search_timestamp"] == "2026-04-13T00:00:00Z"
    assert isinstance(row["embedding"], list) and len(row["embedding"]) == 3


def test_persist_dedupes_by_embedding_similarity(monkeypatch, tmp_path: Path) -> None:
    out = tmp_path / "web_searched_data.json"
    vector_map = {
        "a": [1.0, 0.0, 0.0],
        "b": [0.99, 0.01, 0.0],  # cosine > 0.9 against "a"
        "c": [0.0, 1.0, 0.0],    # cosine low against "a"
    }

    def fake_embed(text: str):
        lowered = text.lower()
        if "alpha" in lowered:
            return vector_map["a"]
        if "beta" in lowered:
            return vector_map["b"]
        return vector_map["c"]

    monkeypatch.setattr("util.websearch_persistence._embed_text", fake_embed)
    monkeypatch.setattr(
        "util.websearch_persistence._upsert_new_records_to_milvus",
        lambda rows: {"upserted": len(rows), "status": "ok"},
    )

    first = persist_websearch_news(
        news_items=[{"title": "Alpha headline", "summary": "alpha content"}],
        symbols_mentioned=["SPY"],
        search_timestamp="2026-04-13T00:00:00Z",
        output_path=str(out),
    )
    second = persist_websearch_news(
        news_items=[{"title": "Beta headline", "summary": "beta content"}],
        symbols_mentioned=["SPY"],
        search_timestamp="2026-04-13T00:01:00Z",
        output_path=str(out),
    )
    third = persist_websearch_news(
        news_items=[{"title": "Gamma headline", "summary": "gamma content"}],
        symbols_mentioned=["SPY"],
        search_timestamp="2026-04-13T00:02:00Z",
        output_path=str(out),
    )

    assert first["stored"] == 1
    assert second["stored"] == 0
    assert second["skipped"] == 1
    assert third["stored"] == 1

    data = json.loads(out.read_text(encoding="utf-8"))
    assert len(data) == 2


def test_persist_upserts_new_rows_to_milvus(monkeypatch, tmp_path: Path) -> None:
    out = tmp_path / "web_searched_data.json"
    monkeypatch.setattr(
        "util.websearch_persistence._embed_text",
        lambda text: ([1.0, 0.0, 0.0] if "SPY" in text else [0.0, 1.0, 0.0]),
    )
    seen: list[dict] = []

    def fake_upsert(rows):
        seen.extend(rows)
        return {"upserted": len(rows), "status": "ok"}

    monkeypatch.setattr("util.websearch_persistence._upsert_new_records_to_milvus", fake_upsert)
    res = persist_websearch_news(
        news_items=[
            {"title": "SPY gains", "summary": "A"},
            {"title": "VTI gains", "summary": "B"},
        ],
        symbols_mentioned=["SPY", "VTI"],
        search_timestamp="2026-04-13T00:00:00Z",
        output_path=str(out),
    )
    assert res["stored"] == 2
    assert res["milvus"]["upserted"] == 2
    assert len(seen) == 2
    assert all(len(_build_milvus_id(d)) <= 64 for d in seen)
