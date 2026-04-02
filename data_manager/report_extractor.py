"""Report extraction for CN fund PDF reports (V1).

This module implements the V1 extraction stage described in
`docs/data_prep/data-extraction.md`.

Key properties:
 - Parser: Docling 2.64.x (optional dependency)
 - Output: standard JSON artifact with `task_type=cn_fund_report_extract`
 - Downstream: consumed by DataDistributor via existing classify/transform/write flow
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

DOC_TASK_TYPE = "cn_fund_report_extract"
DEFAULT_EXTRACTOR_VERSION = "v1"
DOC_PARSER_NAME = "docling"
DOC_PARSER_VERSION = "2.64.x"
FALLBACK_PARSER_NAME = "pypdf_fallback"

# Retrieval-oriented chunk kinds (see docs/data_prep/data-extraction.md §6).
CHUNK_KIND_NARRATIVE = "narrative"
CHUNK_KIND_TABLE_DERIVED = "table_derived"
CHUNK_KIND_TABLE_SUMMARY = "table_summary"

# Chunk kinds produced from PDF tables (used when merging / re-attaching tables).
_TABLE_RETRIEVAL_KINDS = frozenset({CHUNK_KIND_TABLE_DERIVED, CHUNK_KIND_TABLE_SUMMARY})


@dataclass(frozen=True)
class Block:
    """One logical content block produced by the parser adapter."""

    kind: str  # "heading" | "paragraph" | "table_text"
    text: str
    page: int | None = None
    source_ref: str | None = None


@dataclass(frozen=True)
class ExtractedTable:
    """A parsed markdown-like table extracted from report text."""

    table_index: int
    headers: list[str]
    rows: list[list[str]]
    source: str = "docling_markdown"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


_SECTION_PATTERNS: list[tuple[str, list[str]]] = [
    ("objective", ["投资目标", "投资目的", "基金目标"]),
    (
        "strategy",
        [
            "投资策略",
            "投资组合策略",
            "投资策略及运作分析",
            "运作分析",
            "投资策略分析",
            "目标基金产品说明",
            "产品说明",
        ],
    ),
    ("risk", ["风险提示", "风险揭示", "风险因素", "风险分析", "重要提示", "风险收益特征"]),
    (
        "performance",
        [
            "业绩表现",
            "业绩回顾",
            "业绩比较",
            "业绩归因",
            "主要财务指标",
            "净值增长率",
            "基金份额净值",
            "基金净值表现",
        ],
    ),
    ("manager_view", ["基金经理", "基金经理观点", "基金经理报告", "基金经理陈述"]),
    ("market_outlook", ["市场展望", "后市展望", "市场观点"]),
    ("fund_profile", ["基金基本情况", "基金产品概况", "目标基金基本情况", "基金产品资料概要"]),
]

_HEADING_PREFIX_RE = re.compile(
    r"^\s*((第[一二三四五六七八九十百零\d]+[章节部分]|[一二三四五六七八九十]+[、.．)]|[（(][一二三四五六七八九十\d]+[)）]))\s*"
)


def normalize_section_title(title: str) -> str:
    """Map a raw heading title to a canonical section_id."""
    t = (title or "").strip()
    t = t.replace("\u3000", " ")
    # Remove common heading prefixes to improve matching.
    t = re.sub(r"^\s*§\s*\d+\s*", "", t)
    t = re.sub(r"^\s*\d+(\.\d+)*\s*", "", t)
    t = re.sub(r"^\s*[（(]\d+[)）]\s*", "", t)
    t = re.sub(r"^\s*[一二三四五六七八九十]+[、.．)]\s*", "", t)
    t = re.sub(r"^\s*第[一二三四五六七八九十百零\d]+[章节部分]\s*", "", t)
    t = t.strip()
    if not t:
        return "other"
    for section_id, keywords in _SECTION_PATTERNS:
        for kw in keywords:
            if kw in t:
                return section_id
    return "other"


def merge_short_paragraphs(lines: list[str], *, min_chars: int = 50) -> list[str]:
    """Merge short paragraphs to reduce fragmentation."""
    merged: list[str] = []
    buf: list[str] = []
    buf_len = 0

    def flush() -> None:
        nonlocal buf, buf_len
        if buf:
            merged.append("\n".join(buf).strip())
        buf = []
        buf_len = 0

    for ln in lines:
        s = (ln or "").strip()
        if not s:
            flush()
            continue
        if buf_len < min_chars:
            buf.append(s)
            buf_len += len(s)
            continue
        flush()
        buf.append(s)
        buf_len = len(s)

    flush()
    return [m for m in merged if m]


def chunk_text(
    text: str,
    *,
    target_chars: int = 800,
    overlap_chars: int = 120,
    min_chunk_chars: int = 200,
) -> list[str]:
    """Chunk text with overlap for embedding."""
    t = (text or "").strip()
    if not t:
        return []
    if len(t) <= target_chars:
        return [t]

    chunks: list[str] = []
    i = 0
    n = len(t)
    while i < n:
        j = min(i + target_chars, n)
        chunk = t[i:j].strip()
        if chunk and (len(chunk) >= min_chunk_chars or not chunks):
            chunks.append(chunk)
        if j >= n:
            break
        i = max(0, j - overlap_chars)

    return chunks


def chunk_text_semantic(
    text: str,
    *,
    target_chars: int = 800,
    overlap_chars: int = 120,
    min_chunk_chars: int = 200,
) -> list[str]:
    """Split on paragraph boundaries first, then apply length/overlap within each segment."""
    t = (text or "").strip()
    if not t:
        return []
    paragraphs = [p.strip() for p in t.split("\n\n") if p.strip()]
    if not paragraphs:
        return chunk_text(t, target_chars=target_chars, overlap_chars=overlap_chars, min_chunk_chars=min_chunk_chars)

    segments: list[str] = []
    buf: list[str] = []
    buf_len = 0

    def flush_buf() -> None:
        nonlocal buf, buf_len
        if buf:
            segments.append("\n\n".join(buf))
        buf = []
        buf_len = 0

    for p in paragraphs:
        plen = len(p)
        if buf_len + plen + (2 if buf else 0) <= max(target_chars, min_chunk_chars * 2) and buf_len < target_chars:
            buf.append(p)
            buf_len += plen + (2 if len(buf) > 1 else 0)
            continue
        flush_buf()
        buf = [p]
        buf_len = plen

    flush_buf()

    out: list[str] = []
    for seg in segments:
        out.extend(
            chunk_text(
                seg,
                target_chars=target_chars,
                overlap_chars=overlap_chars,
                min_chunk_chars=min_chunk_chars,
            )
        )
    return out


def _content_year(report_date: str) -> int | None:
    s = (report_date or "").strip()
    if len(s) >= 4 and s[:4].isdigit():
        return int(s[:4])
    return None


def _importance_for_section(section_id: str) -> str:
    if section_id in ("strategy", "risk"):
        return "high"
    return "normal"


def _infer_table_section_id(headers: list[str]) -> str:
    joined = " ".join(headers)
    if any(
        k in joined
        for k in ("股票", "证券", "持仓", "重仓", "资产支持证券", "权证", "债券代码")
    ):
        return "performance"
    if any(k in joined for k in ("行业", "板块", "券种", "品种")):
        return "strategy"
    return "other"


def _table_topic_cn(section_id: str) -> str:
    if section_id == "performance":
        return "组合持仓或资产配置"
    if section_id == "strategy":
        return "行业、券种或板块结构"
    return "报告运营与财务数据"


def _table_raw_char_count(table: ExtractedTable) -> int:
    """Approximate size of tabular payload (for summary length policy)."""
    n = sum(len(str(x)) for x in table.headers)
    for r in table.rows:
        n += sum(len(str(c)) for c in r)
    return n


def _table_summary_text(
    table: ExtractedTable,
    *,
    fund_id: str,
    report_date: str,
) -> str:
    """Very short gist for retrieval; detail stays in rows + table_derived chunks."""
    h = [str(x or "").strip() for x in table.headers]
    if not h:
        return ""
    section_id = _infer_table_section_id(h)
    topic = _table_topic_cn(section_id)
    n = len(table.rows)
    ncol = len(h)
    if ncol <= 4:
        cols = "、".join(h)
    else:
        cols = "、".join(h[:3]) + f"等{ncol}列"

    who = f"基金{fund_id}"
    if report_date:
        who += f"·{report_date}"

    # One structural line (always short).
    core = f"【表】{who} 第{table.table_index}表「{topic}」{n}行 {cols}"

    if n == 0:
        return core + "。"

    raw = _table_raw_char_count(table)

    # Small tables: inline full content once; avoid summary longer than the grid.
    if raw <= 200:
        bits: list[str] = []
        for row in table.rows[:20]:
            cells = (list(row) + [""] * ncol)[:ncol]
            line = "·".join(str(c).strip() for c in cells if str(c).strip())
            if line:
                bits.append(line)
        body = " | ".join(bits) if bits else ""
        return f"{core}：{body}。" if body else core + "。"

    # Larger tables: at most two example pairs; no closing essay.
    tail = ""
    if ncol >= 2:
        ex: list[str] = []
        for row in table.rows[:2]:
            cells = (list(row) + [""] * ncol)[:ncol]
            a = str(cells[0]).strip()
            b = str(cells[1]).strip() if len(cells) > 1 else ""
            if not a:
                continue
            ex.append(f"{a}/{b}" if b else a)
        if ex:
            tail = " 例:" + "、".join(ex)
            if n > 2:
                tail += "…"
    return core + tail + "。"


def table_summary_chunks(
    tables: list[ExtractedTable],
    *,
    fund_id: str,
    report_id: str,
    report_type: str,
    report_date: str,
    extractor_version: str,
    parser_name: str,
    parser_version: str,
) -> list[dict[str, Any]]:
    """One concise chunk per table for high-recall retrieval."""
    if not tables:
        return []
    cy = _content_year(report_date)
    out: list[dict[str, Any]] = []
    base_idx = 200_000

    for t in tables:
        text = _table_summary_text(t, fund_id=fund_id, report_date=report_date)
        if not text.strip():
            continue
        section_id = _infer_table_section_id(t.headers)
        importance = (
            "high" if section_id in ("performance", "strategy") else "normal"
        )
        idx = base_idx + t.table_index * 10 + 1
        row: dict[str, Any] = {
            "chunk_id": f"{report_id}-ts{t.table_index:03d}-0001",
            "chunk_kind": CHUNK_KIND_TABLE_SUMMARY,
            "text": text,
            "fund_id": fund_id,
            "section_id": section_id,
            "chunk_index": idx,
            "report_id": report_id,
            "report_type": report_type,
            "report_date": report_date,
            "extractor_version": extractor_version,
            "parser_name": parser_name,
            "parser_version": parser_version,
            "table_index": t.table_index,
            "importance": importance,
        }
        if cy is not None:
            row["content_year"] = cy
        out.append(row)
    return out


def _table_rows_to_prose(
    headers: list[str],
    rows: list[list[str]],
    *,
    fund_id: str,
    report_date: str,
    table_index: int,
    max_rows: int = 80,
) -> str:
    """Deterministic natural-language expansion for embedding (template-first)."""
    h = [str(x or "").strip() for x in headers]
    if not h:
        return ""
    intro = f"基金{fund_id}"
    if report_date:
        intro += f"在报告日{report_date}"
    intro += f"的披露表格（第{table_index}表）"
    intro += f"，列包括：{'、'.join(h)}。逐行摘要："
    parts: list[str] = []
    for row in rows[:max_rows]:
        cells = (list(row) + [""] * len(h))[: len(h)]
        # Two-column name + metric (common for holdings)
        if len(h) >= 2 and len(cells) >= 2 and cells[0].strip():
            parts.append(f"{cells[0].strip()}的{h[1]}为{cells[1].strip()}。")
            continue
        pairs: list[str] = []
        for i, name in enumerate(h):
            if i < len(cells) and str(cells[i]).strip():
                pairs.append(f"{name}为{str(cells[i]).strip()}")
        if pairs:
            parts.append("，".join(pairs) + "。")
    if not parts:
        return ""
    return intro + "".join(parts)


def table_derived_chunks(
    tables: list[ExtractedTable],
    *,
    fund_id: str,
    report_id: str,
    report_type: str,
    report_date: str,
    extractor_version: str,
    parser_name: str,
    parser_version: str,
    target_chars: int = 1000,
    overlap_chars: int = 100,
) -> list[dict[str, Any]]:
    """Build table_derived retrieval chunks from structured tables."""
    if not tables:
        return []
    cy = _content_year(report_date)
    out: list[dict[str, Any]] = []
    base_idx = 100_000  # avoid colliding with per-section narrative chunk_index

    for t in tables:
        section_id = _infer_table_section_id(t.headers)
        prose = _table_rows_to_prose(
            t.headers,
            t.rows,
            fund_id=fund_id,
            report_date=report_date,
            table_index=t.table_index,
        )
        if not prose.strip():
            continue
        text_pieces = chunk_text(
            prose,
            target_chars=target_chars,
            overlap_chars=overlap_chars,
            min_chunk_chars=80,
        )
        for i, piece in enumerate(text_pieces, start=1):
            idx = base_idx + t.table_index * 1_000 + i
            out.append(
                {
                    "chunk_id": f"{report_id}-td{t.table_index:03d}-{i:04d}",
                    "chunk_kind": CHUNK_KIND_TABLE_DERIVED,
                    "text": piece,
                    "fund_id": fund_id,
                    "section_id": section_id,
                    "chunk_index": idx,
                    "report_id": report_id,
                    "report_type": report_type,
                    "report_date": report_date,
                    "extractor_version": extractor_version,
                    "parser_name": parser_name,
                    "parser_version": parser_version,
                    "table_index": t.table_index,
                    "importance": _importance_for_section(section_id),
                    **({"content_year": cy} if cy is not None else {}),
                }
            )
    return out


def _serialized_tables_for_content(
    tables: list[ExtractedTable],
    *,
    fund_id: str = "",
    report_date: str = "",
) -> list[dict[str, Any]]:
    table_items: list[dict[str, Any]] = []
    for t in tables:
        normalized_rows: list[list[str]] = []
        for r in t.rows:
            normalized_rows.append((r + [""] * len(t.headers))[: len(t.headers)])
        summary = _table_summary_text(t, fund_id=fund_id, report_date=report_date)
        table_items.append(
            {
                "table_index": t.table_index,
                "source": t.source,
                "n_cols": len(t.headers),
                "n_rows": len(t.rows),
                "headers": t.headers,
                "rows": normalized_rows,
                "retrieval_summary": summary,
            }
        )
    return table_items


def blocks_to_sections(blocks: Iterable[Block]) -> list[dict[str, Any]]:
    """Convert ordered blocks into section objects."""
    sections: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    def ensure_current() -> dict[str, Any]:
        nonlocal current
        if current is None:
            current = {
                "section_id": "other",
                "section_title_raw": "Other",
                "text": "",
                "summary": "",
            }
            sections.append(current)
        return current

    def maybe_inline_heading(text: str) -> tuple[bool, str, str]:
        """Detect heading-like paragraph lines from markdown/plain text output.

        Returns (is_heading, heading_title, remaining_text_after_heading).
        """
        s = (text or "").strip()
        if not s:
            return False, "", ""

        # Heuristic 1: explicit section keyword in a short line.
        sec = normalize_section_title(s)
        if sec != "other" and len(s) <= 50:
            return True, s, ""

        # Heuristic 2: Chinese enumerated heading prefix + keyword or very short body.
        m = _HEADING_PREFIX_RE.match(s)
        if m:
            title = s
            mapped = normalize_section_title(title)
            # Only split when this numbered heading can be mapped.
            if mapped == "other":
                return False, "", ""
            # Split by first separator when there is substantial trailing text.
            for sep in ("：", ":", "。"):
                if sep in s:
                    left, right = s.split(sep, 1)
                    if len(left.strip()) <= 50:
                        title = left.strip()
                        rest = right.strip()
                        return True, title, rest
            if len(s) <= 60:
                return True, s, ""

        return False, "", ""

    for b in blocks:
        if b.kind == "heading":
            title = (b.text or "").strip()
            section_id = normalize_section_title(title)
            current = {
                "section_id": section_id,
                "section_title_raw": title or "Untitled",
                "text": "",
                "summary": "",
            }
            sections.append(current)
            continue

        if b.kind in ("paragraph", "table_text"):
            is_h, h_title, rest = maybe_inline_heading(b.text or "")
            if is_h:
                section_id = normalize_section_title(h_title)
                current = {
                    "section_id": section_id,
                    "section_title_raw": h_title or "Untitled",
                    "text": "",
                    "summary": "",
                }
                sections.append(current)
                if rest:
                    current["text"] = (current["text"] + "\n" + rest).strip()
                continue

            cur = ensure_current()
            cur["text"] = (cur["text"] + "\n" + (b.text or "")).strip()
            continue

    # Cleanup: merge short paragraphs inside each section.
    for sec in sections:
        raw = (sec.get("text") or "").strip()
        if not raw:
            continue
        parts = [p.strip() for p in raw.split("\n")]
        merged = merge_short_paragraphs(parts, min_chars=50)
        sec["text"] = "\n\n".join(merged).strip()

    return [s for s in sections if (s.get("text") or "").strip()]


def sections_to_chunks(
    *,
    fund_id: str,
    report_id: str,
    report_type: str,
    report_date: str,
    extractor_version: str,
    parser_name: str,
    parser_version: str,
    sections: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    cy = _content_year(report_date)
    for sec in sections:
        section_id = str(sec.get("section_id") or "other")
        text = str(sec.get("text") or "")
        importance = _importance_for_section(section_id)
        for idx, ct in enumerate(
            chunk_text_semantic(
                text,
                target_chars=800,
                overlap_chars=120,
                min_chunk_chars=200,
            ),
            start=1,
        ):
            row: dict[str, Any] = {
                "chunk_id": f"{report_id}-{section_id}-{idx:04d}",
                "chunk_kind": CHUNK_KIND_NARRATIVE,
                "text": ct,
                "fund_id": fund_id,
                "section_id": section_id,
                "chunk_index": idx,
                "report_id": report_id,
                "report_type": report_type,
                "report_date": report_date,
                "extractor_version": extractor_version,
                "parser_name": parser_name,
                "parser_version": parser_version,
                "importance": importance,
            }
            if cy is not None:
                row["content_year"] = cy
            chunks.append(row)
    return chunks


def extract_signals(sections: list[dict[str, Any]]) -> dict[str, Any]:
    """V1: lightweight/stub signal extraction (no LLM).

We keep it deterministic and safe; implementations may upgrade later.
"""
    by_id: dict[str, str] = {}
    for sec in sections:
        sid = str(sec.get("section_id") or "other")
        if sid not in by_id:
            by_id[sid] = str(sec.get("text") or "").strip()

    def _preview(s: str, n: int = 1200) -> str:
        s = (s or "").strip()
        return s[:n]

    return {
        "strategy": _preview(by_id.get("strategy", "")),
        "risk": _preview(by_id.get("risk", "")),
        "sector_preference": [],
        "market_view": _preview(by_id.get("market_outlook", "")),
        "style": "",
    }


def build_artifact(
    *,
    fund_id: str,
    as_of_date: str,
    report_id: str,
    report_type: str = "unknown",
    report_date: str = "",
    extractor_version: str = DEFAULT_EXTRACTOR_VERSION,
    parser_name: str = DOC_PARSER_NAME,
    parser_version: str = DOC_PARSER_VERSION,
    blocks: Iterable[Block],
    tables: list[ExtractedTable] | None = None,
) -> dict[str, Any]:
    fund_id = str(fund_id).strip()
    report_id = str(report_id).strip()
    as_of_date = str(as_of_date).strip()
    tables_list = list(tables) if tables is not None else []

    sections = blocks_to_sections(blocks)
    chunks = sections_to_chunks(
        fund_id=fund_id,
        report_id=report_id,
        report_type=report_type,
        report_date=report_date,
        extractor_version=extractor_version,
        parser_name=parser_name,
        parser_version=parser_version,
        sections=sections,
    )
    if tables_list:
        chunks.extend(
            table_summary_chunks(
                tables_list,
                fund_id=fund_id,
                report_id=report_id,
                report_type=report_type,
                report_date=report_date,
                extractor_version=extractor_version,
                parser_name=parser_name,
                parser_version=parser_version,
            )
        )
        chunks.extend(
            table_derived_chunks(
                tables_list,
                fund_id=fund_id,
                report_id=report_id,
                report_type=report_type,
                report_date=report_date,
                extractor_version=extractor_version,
                parser_name=parser_name,
                parser_version=parser_version,
            )
        )
    signals = extract_signals(sections)

    content: dict[str, Any] = {
        "sections": sections,
        "chunks": chunks,
        "signals": signals,
    }
    if tables_list:
        content["tables"] = _serialized_tables_for_content(
            tables_list,
            fund_id=fund_id,
            report_date=report_date,
        )

    return {
        "metadata": {
            # Compatibility: DataDistributor historically reads `symbol`.
            "symbol": fund_id,
            "fund_id": fund_id,
            "task_type": DOC_TASK_TYPE,
            "as_of_date": as_of_date,
            "collected_at": _utc_now_iso(),
            "source": "pdf_report_extractor",
            "report_id": report_id,
            "report_type": report_type,
            "report_date": report_date,
            "extractor_version": extractor_version,
            "parser_name": parser_name,
            "parser_version": parser_version,
        },
        "content": content,
    }


def _import_docling() -> Any:
    try:
        import docling  # type: ignore

        return docling
    except Exception as e:  # pragma: no cover
        raise RuntimeError(
            'Docling is required for the default parser path. Install: pip install "docling>=2.64,<2.65"'
        ) from e


def _docling_import_diagnostics(err: Exception) -> str:
    msg = str(err)
    # Common on Windows when torch cannot load its DLL dependencies.
    if "WinError 1114" in msg or "Error loading" in msg and "torch" in msg:
        return (
            "Docling import failed because PyTorch could not load (WinError 1114). "
            "This usually happens when using an unsupported Python version for torch "
            "(your environment shows Python 3.14 in site-packages) or missing VC++ runtime. "
            "Recommended: use Python 3.11/3.12 (project requires >=3.11) and install a compatible CPU torch, "
            "then reinstall Docling 2.64.x."
        )
    return f"Docling import failed: {err}"


def _export_markdown_via_docling(pdf_path: str) -> str:
    """Run Docling once and return markdown (or plain text) for the PDF."""
    _import_docling()

    try:
        from docling.document_converter import DocumentConverter  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError(_docling_import_diagnostics(e)) from e

    converter = DocumentConverter()
    res = converter.convert(pdf_path)

    doc = getattr(res, "document", None) or getattr(res, "doc", None) or res

    md = None
    for attr in ("export_to_markdown", "to_markdown", "export_markdown"):
        fn = getattr(doc, attr, None)
        if callable(fn):
            md = fn()
            break

    if not isinstance(md, str) or not md.strip():
        for attr in ("export_to_text", "to_text", "export_text"):
            fn = getattr(doc, attr, None)
            if callable(fn):
                md = fn()
                break

    if not isinstance(md, str) or not md.strip():
        raise RuntimeError("Docling produced empty output for PDF.")
    return md


def _parse_pdf_to_blocks_and_tables_docling(pdf_path: str) -> tuple[list[Block], list[ExtractedTable]]:
    md = _export_markdown_via_docling(pdf_path)
    return _markdown_to_blocks_and_tables(md)


def parse_pdf_with_docling(pdf_path: str) -> list[Block]:
    """Parse a PDF using Docling and map to internal blocks.

This function is intentionally conservative: it tries to export a markdown/text
representation and then relies on simple heading detection.
"""
    blocks, _tables = _parse_pdf_to_blocks_and_tables_docling(pdf_path)
    return blocks


def parse_pdf_with_pypdf(pdf_path: str) -> list[Block]:
    """Fallback parser: extract plain text with pypdf.

    This is only intended as a config-gated fallback to unblock local runs
    when Docling cannot be imported due to heavy dependencies.
    """
    try:
        from pypdf import PdfReader  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError(
            'pypdf fallback requested but not installed. Install: pip install "pypdf>=4"'
        ) from e

    reader = PdfReader(pdf_path)
    blocks: list[Block] = []
    for i, page in enumerate(reader.pages, start=1):
        txt = page.extract_text() or ""
        for para in txt.splitlines():
            s = para.strip()
            if not s:
                blocks.append(Block(kind="paragraph", text="", page=i))
                continue
            blocks.append(Block(kind="paragraph", text=s, page=i))
    return blocks


def _is_markdown_table_line(line: str) -> bool:
    s = line.strip()
    # Basic markdown table line guard.
    return "|" in s and s.count("|") >= 2


def _is_markdown_separator_row(cells: list[str]) -> bool:
    # Examples: --- | :---: | ---:
    if not cells:
        return False
    for c in cells:
        s = c.strip().replace(":", "").replace("-", "")
        if s:
            return False
    return True


def _split_md_row(line: str) -> list[str]:
    # Keep simple parser for V1 (good enough for most report tables).
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _markdown_to_blocks_and_tables(md: str) -> tuple[list[Block], list[ExtractedTable]]:
    lines = md.splitlines()
    blocks: list[Block] = []
    tables: list[ExtractedTable] = []

    i = 0
    table_idx = 0
    n = len(lines)
    while i < n:
        ln = lines[i].strip()
        if not ln:
            blocks.append(Block(kind="paragraph", text=""))
            i += 1
            continue
        if ln.startswith("#"):
            title = ln.lstrip("#").strip()
            if title:
                blocks.append(Block(kind="heading", text=title))
            i += 1
            continue

        # Detect markdown table cluster
        if _is_markdown_table_line(ln):
            cluster: list[str] = []
            j = i
            while j < n and _is_markdown_table_line(lines[j].strip()):
                cluster.append(lines[j].strip())
                j += 1

            if len(cluster) >= 2:
                header_cells = _split_md_row(cluster[0])
                sep_cells = _split_md_row(cluster[1])
                if _is_markdown_separator_row(sep_cells):
                    data_rows = [_split_md_row(r) for r in cluster[2:]]
                    if header_cells and data_rows:
                        table_idx += 1
                        tables.append(
                            ExtractedTable(
                                table_index=table_idx,
                                headers=header_cells,
                                rows=data_rows,
                            )
                        )
                        # Keep a compact textual representation in blocks for RAG continuity.
                        preview_rows = [" | ".join(header_cells)] + [
                            " | ".join(r[: len(header_cells)]) for r in data_rows[:20]
                        ]
                        blocks.append(Block(kind="table_text", text="\n".join(preview_rows)))
                        i = j
                        continue

            # Not a valid markdown table after checks -> treat as normal paragraph
            blocks.append(Block(kind="paragraph", text=ln))
            i += 1
            continue

        blocks.append(Block(kind="paragraph", text=ln))
        i += 1

    return blocks, tables


def extract_tables_from_pdf_with_docling(pdf_path: str) -> list[ExtractedTable]:
    """Parse PDF with Docling and return markdown-detected tables (single conversion)."""
    _, tables = _parse_pdf_to_blocks_and_tables_docling(pdf_path)
    return tables


_REPORT_ID_RE = re.compile(r"^(AN\d+)\.pdf$", re.IGNORECASE)


def extract_one_pdf(
    *,
    pdf_path: str,
    fund_id: str,
    as_of_date: str,
    extractor_version: str = DEFAULT_EXTRACTOR_VERSION,
    allow_fallback: bool = False,
    include_tables: bool = True,
) -> dict[str, Any]:
    fname = os.path.basename(pdf_path)
    m = _REPORT_ID_RE.match(fname)
    report_id = m.group(1) if m else os.path.splitext(fname)[0]

    parser_name = DOC_PARSER_NAME
    parser_version = DOC_PARSER_VERSION
    tables: list[ExtractedTable] = []
    try:
        blocks, tables = _parse_pdf_to_blocks_and_tables_docling(pdf_path)
    except Exception:
        if not allow_fallback:
            raise
        blocks = parse_pdf_with_pypdf(pdf_path)
        tables = []
        parser_name = FALLBACK_PARSER_NAME
        parser_version = ""

    if not include_tables:
        tables = []

    return build_artifact(
        fund_id=fund_id,
        as_of_date=as_of_date,
        report_id=report_id,
        extractor_version=extractor_version,
        parser_name=parser_name,
        parser_version=parser_version,
        blocks=blocks,
        tables=tables,
    )


def add_table_metadata(
    artifact: dict[str, Any],
    *,
    tables: list[ExtractedTable],
) -> dict[str, Any]:
    """Attach extracted table data and merge table_derived chunks (legacy helper).

    Prefer passing ``tables`` into :func:`build_artifact` / :func:`extract_one_pdf`
    with ``include_tables=True`` to avoid duplicate Docling runs.
    """
    content = artifact.setdefault("content", {})
    meta = artifact.get("metadata") or {}
    fid = str(meta.get("fund_id") or meta.get("symbol") or "")
    rd = str(meta.get("report_date") or "")
    content["tables"] = _serialized_tables_for_content(
        tables,
        fund_id=fid,
        report_date=rd,
    )
    chunks_extra = table_summary_chunks(
        tables,
        fund_id=fid,
        report_id=str(meta.get("report_id") or ""),
        report_type=str(meta.get("report_type") or "unknown"),
        report_date=rd,
        extractor_version=str(meta.get("extractor_version") or DEFAULT_EXTRACTOR_VERSION),
        parser_name=str(meta.get("parser_name") or DOC_PARSER_NAME),
        parser_version=str(meta.get("parser_version") or DOC_PARSER_VERSION),
    ) + table_derived_chunks(
        tables,
        fund_id=fid,
        report_id=str(meta.get("report_id") or ""),
        report_type=str(meta.get("report_type") or "unknown"),
        report_date=rd,
        extractor_version=str(meta.get("extractor_version") or DEFAULT_EXTRACTOR_VERSION),
        parser_name=str(meta.get("parser_name") or DOC_PARSER_NAME),
        parser_version=str(meta.get("parser_version") or DOC_PARSER_VERSION),
    )
    existing = content.get("chunks")
    if isinstance(existing, list):
        kept = [
            c
            for c in existing
            if not isinstance(c, dict) or c.get("chunk_kind") not in _TABLE_RETRIEVAL_KINDS
        ]
        kept.extend(chunks_extra)
        content["chunks"] = kept
    else:
        content["chunks"] = chunks_extra
    return artifact


def write_artifact_json(artifact: dict[str, Any], out_path: str) -> None:
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(artifact, f, ensure_ascii=False, indent=2)

