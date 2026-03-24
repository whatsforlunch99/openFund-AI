#!/usr/bin/env python3
"""Collect cn_fund_all for each fund ID listed in a fundid file.

Reads fund IDs from a file (one per line), then calls the cn_fund_all
collection task for each. Date and report download are configurable.

Usage:
    python scripts/collect_cn_fund_all.py
    python scripts/collect_cn_fund_all.py --date 2026-03-20 --no-reports
    python scripts/collect_cn_fund_all.py --fundid-file path/to/fundid
"""

from __future__ import annotations

import argparse
import os
import sys


def _project_root() -> str:
    """Return project root (parent of scripts/)."""
    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(scripts_dir)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Collect cn_fund_all for each fund ID in a file",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--fundid-file",
        "-f",
        default=None,
        help="Path to fundid file (default: datasets/raw/ingestion/cn_fund_all/fundid)",
    )
    parser.add_argument(
        "--date",
        "-d",
        default=None,
        help="Reference date yyyy-mm-dd (default: today)",
    )
    parser.add_argument(
        "--no-reports",
        action="store_true",
        help="Skip downloading quarterly/annual report PDFs",
    )
    parser.add_argument(
        "--format",
        choices=["json", "csv", "both"],
        default="both",
        help="Output format (default: both)",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Root data directory (default: datasets/raw)",
    )
    args = parser.parse_args()

    root = _project_root()
    data_dir = args.data_dir or os.path.join(root, "datasets", "raw")
    fundid_path = args.fundid_file or os.path.join(
        data_dir, "ingestion", "cn_fund_all", "fundid"
    )

    if not os.path.isfile(fundid_path):
        print(f"Error: fundid file not found: {fundid_path}", file=sys.stderr)
        return 1

    fund_ids: list[str] = []
    with open(fundid_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            fund_ids.append(line)

    if not fund_ids:
        print(f"Error: No fund IDs in {fundid_path}", file=sys.stderr)
        return 1

    from datetime import datetime

    from data_manager.collector import DataCollector

    as_of_date = args.date or datetime.now().strftime("%Y-%m-%d")
    download_reports = not args.no_reports

    print(f"Collecting cn_fund_all for {len(fund_ids)} fund(s) as of {as_of_date}")
    print(f"  fundid file: {fundid_path}")
    print(f"  download reports: {download_reports}")
    print(f"  format: {args.format}")

    collector = DataCollector(data_dir=data_dir)
    batch = collector.collect_batch(
        fund_ids,
        as_of_date,
        task_types=["cn_fund_all"],
        output_format=args.format,
        download_reports=download_reports,
    )

    print(f"\nResults: {batch.total_success} success, {batch.total_failed} failed")
    for symbol, result in batch.results.items():
        status = "ok" if not result.failed else "FAILED"
        print(f"  {symbol}: {status}")
        if result.errors:
            for task, err in result.errors.items():
                print(f"    {task}: {err}")

    return 0 if batch.total_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
