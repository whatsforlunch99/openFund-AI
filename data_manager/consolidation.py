"""Consolidate cn_fund_all raw CSV into daily + static tables."""

from __future__ import annotations

import csv
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Section -> (output_group, section_key)
# daily.csv / static.csv 各含多张表，每张表有独立表头，无跨表空列
DAILY_SECTIONS = {"NAV": ("daily", "nav"), "RANK": ("daily", "rank")}
STATIC_SECTIONS = {
    "BASIC": ("static", "basic"),
    "FEE": ("static", "fee"),
    "HOLDINGS": ("static", "holdings"),
    "ANNOUNCEMENTS_DIVIDEND": ("static", "announcements_dividend"),
    "ANNOUNCEMENTS_REPORT": ("static", "announcements_report"),
    "ANNOUNCEMENTS_PERSONNEL": ("static", "announcements_personnel"),
    "ANNOUNCEMENTS_DISCLOSURE_CNINFO": ("static", "announcements_disclosure_cninfo"),
}
SECTION_MAP = {**DAILY_SECTIONS, **STATIC_SECTIONS}

# 同一文件内表的写入顺序
DAILY_ORDER = ["nav", "rank"]
STATIC_ORDER = ["basic", "fee", "holdings", "announcements_dividend", "announcements_report", "announcements_personnel", "announcements_disclosure_cninfo"]

# Regex to extract section name from "# 基础信息 (BASIC)" or "# 净值 (NAV)"
SECTION_HEADER_RE = re.compile(r"#\s+[^(]+\(([A-Za-z0-9_]+)\)")


def _parse_fund_csv(filepath: str) -> dict[str, list[dict]]:
    """Parse a single data.csv, return {section: [rows]}."""
    out: dict[str, list[dict]] = {}
    current_section: str | None = None
    current_header: list[str] | None = None

    with open(filepath, "r", encoding="utf-8-sig") as f:
        for line in f:
            line = line.rstrip("\n\r")
            if not line.strip():
                continue

            # Check for section header: # xxx (SECTION_NAME)
            m = SECTION_HEADER_RE.match(line)
            if m:
                section = m.group(1).upper().replace("-", "_")
                if section in SECTION_MAP:
                    current_section = section
                    current_header = None
                else:
                    current_section = None
                continue

            # Skip comment lines
            if line.strip().startswith("#"):
                continue

            if current_section is None:
                continue

            # First non-comment after section = header
            if current_header is None:
                current_header = [c.strip() for c in line.split(",")]
                out.setdefault(current_section, [])
                continue

            # Data row
            if current_header:
                cells = next(csv.reader([line]), [])
                row = {}
                for i, col in enumerate(current_header):
                    row[col] = cells[i] if i < len(cells) else ""
                out.setdefault(current_section, []).append(row)

    return out


def _merge_section_rows(rows: list[dict]) -> tuple[list[str], list[dict]]:
    """同一 section 内列并集（仅合并该 section 的列），返回 (columns, rows)。"""
    from data_manager.empty_markers import NOT_EXIST

    if not rows:
        return [], []

    all_cols: set[str] = set()
    for row in rows:
        all_cols.update(row.keys())

    preferred = ["fund_id", "as_of_date", "collected_at"]
    ordered = [c for c in preferred if c in all_cols]
    ordered += sorted(all_cols - set(preferred))

    merged = []
    for row in rows:
        out_row = {}
        for c in ordered:
            v = row.get(c, "")
            s = str(v).strip().replace("\n", " ").replace("\r", " ")
            out_row[c] = s if s else NOT_EXIST
        merged.append(out_row)

    return ordered, merged


@dataclass
class ConsolidationResult:
    """Result of a consolidation run."""

    as_of_date: str
    files_processed: int = 0
    output_files: dict[str, int] = field(default_factory=dict)  # file -> row count
    errors: list[str] = field(default_factory=list)


def consolidate_csv(
    data_dir: str,
    as_of_date: str,
    output: str = "both",
    dry_run: bool = False,
) -> ConsolidationResult:
    """
    Consolidate cn_fund_all data.csv into daily.csv and static.csv.

    Args:
        data_dir: Root data dir (e.g. datasets/raw).
        as_of_date: Date to consolidate (yyyy-mm-dd).
        output: "daily" | "static" | "both".
        dry_run: If True, only report what would be done.

    Returns:
        ConsolidationResult with files_processed, output_files, errors.
    """
    result = ConsolidationResult(as_of_date=as_of_date)
    base = os.path.join(data_dir, "ingestion", "cn_fund_all")
    date_dir = os.path.join(base, as_of_date)
    out_dir = os.path.join(base, "consolidated", as_of_date)

    if not os.path.isdir(date_dir):
        result.errors.append(f"Date directory not found: {date_dir}")
        return result

    # Collect rows by section (each section -> its own file, no cross-section column union)
    section_rows: dict[str, list[dict]] = {}

    for fund_id in sorted(os.listdir(date_dir)):
        fund_path = os.path.join(date_dir, fund_id)
        csv_path = os.path.join(fund_path, "data.csv")
        if not os.path.isfile(csv_path):
            continue

        try:
            sections = _parse_fund_csv(csv_path)
        except Exception as e:
            result.errors.append(f"{csv_path}: {e}")
            continue

        result.files_processed += 1

        for section, rows in sections.items():
            if section not in SECTION_MAP:
                continue
            out_group, out_name = SECTION_MAP[section]
            if output == "daily" and out_group != "daily":
                continue
            if output == "static" and out_group != "static":
                continue

            section_rows.setdefault(out_name, []).extend(rows)

    if dry_run:
        for group in ("daily", "static"):
            n = sum(len(section_rows.get(k, [])) for k in (DAILY_ORDER if group == "daily" else STATIC_ORDER))
            if n:
                result.output_files[f"{group}.csv"] = n
        return result

    os.makedirs(out_dir, exist_ok=True)

    # 移除旧版按 section 独立的文件，仅保留 daily.csv / static.csv
    for f in os.listdir(out_dir):
        if f.endswith(".csv") and f not in ("daily.csv", "static.csv"):
            try:
                os.remove(os.path.join(out_dir, f))
            except OSError:
                pass

    # 对 static 表：as_of_date/collected_at 移到文件头，表中不再重复
    STATIC_DROP_COLS = frozenset({"as_of_date", "collected_at"})

    def write_multi_table(
        filename: str,
        section_order: list[str],
        label: str,
        *,
        file_header_lines: list[str] | None = None,
        drop_cols: frozenset[str] | None = None,
    ) -> None:
        total = 0
        with open(os.path.join(out_dir, filename), "w", encoding="utf-8-sig", newline="") as f:
            if file_header_lines:
                for line in file_header_lines:
                    f.write(line if line.endswith("\n") else line + "\n")
                f.write("\n")
            first = True
            for section_key in section_order:
                rows = section_rows.get(section_key, [])
                if not rows:
                    continue
                cols, merged = _merge_section_rows(rows)
                if drop_cols:
                    cols = [c for c in cols if c not in drop_cols]
                    merged = [{k: v for k, v in r.items() if k not in drop_cols} for r in merged]
                if not first:
                    f.write("\n")
                f.write(f"# === {section_key.upper()} ===\n")
                writer = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
                writer.writeheader()
                for r in merged:
                    writer.writerow(r)
                total += len(merged)
                first = False
        if total:
            result.output_files[filename] = total
            logger.info("Wrote %s (%s) with %d rows", filename, label, total)

    if output in ("both", "daily"):
        write_multi_table("daily.csv", DAILY_ORDER, "nav+rank")
    if output in ("both", "static"):
        write_multi_table(
            "static.csv",
            STATIC_ORDER,
            "basic+fee+holdings+announcements",
            file_header_lines=[
                f"# as_of_date: {as_of_date}",
                f"# consolidated_at: {datetime.now(timezone.utc).isoformat()}",
            ],
            drop_cols=STATIC_DROP_COLS,
        )

    return result


def consolidate_date_range(
    data_dir: str,
    date_from: str,
    date_to: str,
    output: str = "both",
    dry_run: bool = False,
) -> dict[str, ConsolidationResult]:
    """Consolidate each date in the range."""
    from datetime import timedelta

    start = datetime.strptime(date_from, "%Y-%m-%d").date()
    end = datetime.strptime(date_to, "%Y-%m-%d").date()
    results = {}
    d = start
    while d <= end:
        date_str = d.strftime("%Y-%m-%d")
        results[date_str] = consolidate_csv(data_dir, date_str, output=output, dry_run=dry_run)
        d += timedelta(days=1)
    return results
