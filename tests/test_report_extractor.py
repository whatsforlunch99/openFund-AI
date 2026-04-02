from __future__ import annotations

from data_manager.report_extractor import (
    CHUNK_KIND_NARRATIVE,
    CHUNK_KIND_TABLE_DERIVED,
    CHUNK_KIND_TABLE_SUMMARY,
    Block,
    ExtractedTable,
    build_artifact,
    table_derived_chunks,
)


def test_build_artifact_basic_shape() -> None:
    blocks = [
        Block(kind="heading", text="投资策略"),
        Block(kind="paragraph", text="本基金主要投资于……"),
        Block(kind="heading", text="风险提示"),
        Block(kind="paragraph", text="本基金存在市场风险……"),
    ]

    art = build_artifact(
        fund_id="001235",
        as_of_date="2026-03-20",
        report_id="AN123",
        blocks=blocks,
    )

    assert art["metadata"]["task_type"] == "cn_fund_report_extract"
    assert art["metadata"]["fund_id"] == "001235"
    assert art["metadata"]["parser_name"] == "docling"
    assert art["metadata"]["parser_version"] == "2.64.x"

    content = art["content"]
    assert isinstance(content["sections"], list)
    assert isinstance(content["chunks"], list)
    assert isinstance(content["signals"], dict)

    # section ids are normalized
    sec_ids = {s["section_id"] for s in content["sections"]}
    assert "strategy" in sec_ids
    assert "risk" in sec_ids

    # chunk metadata is present (retrieval layer)
    ch0 = content["chunks"][0]
    for k in (
        "chunk_id",
        "chunk_kind",
        "text",
        "fund_id",
        "section_id",
        "chunk_index",
        "report_id",
        "extractor_version",
        "parser_name",
        "parser_version",
        "importance",
    ):
        assert k in ch0
    assert ch0["chunk_kind"] == CHUNK_KIND_NARRATIVE


def test_table_derived_chunks_from_extracted_table() -> None:
    t = ExtractedTable(
        table_index=1,
        headers=["股票名称", "占基金资产净值比例"],
        rows=[["宁德时代", "8.5%"], ["贵州茅台", "7.0%"]],
    )
    chunks = table_derived_chunks(
        [t],
        fund_id="001235",
        report_id="AN999",
        report_type="annual",
        report_date="2025-12-31",
        extractor_version="v1",
        parser_name="docling",
        parser_version="2.64.x",
    )
    assert len(chunks) >= 1
    assert chunks[0]["chunk_kind"] == CHUNK_KIND_TABLE_DERIVED
    assert "001235" in chunks[0]["text"]
    assert "宁德时代" in chunks[0]["text"]
    assert chunks[0]["chunk_id"].startswith("AN999-td001-")


def test_build_artifact_includes_table_chunks_when_tables_passed() -> None:
    blocks = [
        Block(kind="heading", text="投资策略"),
        Block(kind="paragraph", text="本基金主要投资于……"),
    ]
    tables = [
        ExtractedTable(
            table_index=1,
            headers=["证券名称", "占比"],
            rows=[["测试证券", "1.2%"]],
        )
    ]
    art = build_artifact(
        fund_id="001235",
        as_of_date="2026-03-20",
        report_id="AN777",
        blocks=blocks,
        tables=tables,
    )
    kinds = {c["chunk_kind"] for c in art["content"]["chunks"]}
    assert CHUNK_KIND_NARRATIVE in kinds
    assert CHUNK_KIND_TABLE_SUMMARY in kinds
    assert CHUNK_KIND_TABLE_DERIVED in kinds
    assert "tables" in art["content"]
    assert len(art["content"]["tables"]) == 1
    tab0 = art["content"]["tables"][0]
    assert "retrieval_summary" in tab0
    assert "【表】" in tab0["retrieval_summary"]
    summary_chunks = [c for c in art["content"]["chunks"] if c["chunk_kind"] == CHUNK_KIND_TABLE_SUMMARY]
    assert len(summary_chunks) == 1
    assert summary_chunks[0]["chunk_id"].startswith("AN777-ts001-")

