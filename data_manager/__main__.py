"""CLI entry point for data_manager.

Usage:
    python -m data_manager collect --symbols NVDA,AAPL --date 2024-01-15
    python -m data_manager collect --symbols NVDA --tasks stock_data,fundamentals
    python -m data_manager global-news --date 2024-01-15
    python -m data_manager distribute --symbol NVDA
    python -m data_manager distribute --all
    python -m data_manager status --symbol NVDA
    python -m data_manager list
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import warnings
from datetime import datetime

# Suppress urllib3/OpenSSL warning before imports that load it (e.g. requests in collector).
warnings.filterwarnings("ignore", message=".*urllib3 v2 only supports OpenSSL.*")
warnings.filterwarnings("ignore", message=".*LibreSSL.*")

from config.config import load_config
from data_manager.backend_cli import add_backend_subcommands
from data_manager.collector import DataCollector
from data_manager.distributor import DataDistributor
from data_manager.tasks import COLLECTION_TASKS
from data_manager.report_extractor import (
    extract_one_pdf,
    write_artifact_json,
)
from data_manager.doctor import run_doctor, format_doctor_report


def cmd_collect(args: argparse.Namespace) -> int:
    """Execute collect command."""
    collector = DataCollector(data_dir=args.data_dir)

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    if not symbols:
        print("Error: No symbols provided", file=sys.stderr)
        return 1

    task_types = None
    if args.tasks:
        task_types = [t.strip() for t in args.tasks.split(",") if t.strip()]

    as_of_date = args.date or datetime.now().strftime("%Y-%m-%d")

    print(f"Collecting data for {len(symbols)} symbol(s) as of {as_of_date}...")
    if task_types:
        print(f"Tasks: {', '.join(task_types)}")
    output_format = getattr(args, "format", "json")
    if output_format != "json":
        print(f"Output format: {output_format} (JSON always saved for pipeline)")

    download_reports = not getattr(args, "no_reports", False)
    batch = collector.collect_batch(
        symbols,
        as_of_date,
        task_types,
        output_format=output_format,
        download_reports=download_reports,
    )

    print(f"\nResults:")
    print(f"  Total success: {batch.total_success}")
    print(f"  Total failed: {batch.total_failed}")

    for symbol, result in batch.results.items():
        print(f"\n  {symbol}:")
        print(f"    Success: {', '.join(result.success) or 'none'}")
        if result.failed:
            print(f"    Failed: {', '.join(result.failed)}")
        if result.errors:
            for task, error in result.errors.items():
                print(f"      {task}: {error}")

    if args.json:
        output = {
            "as_of_date": batch.as_of_date,
            "total_success": batch.total_success,
            "total_failed": batch.total_failed,
            "results": {
                sym: {
                    "success": r.success,
                    "failed": r.failed,
                    "files": r.files,
                    "errors": r.errors,
                }
                for sym, r in batch.results.items()
            },
        }
        print(f"\nJSON output:")
        print(json.dumps(output, indent=2))

    return 0 if batch.total_failed == 0 else 1


def cmd_global_news(args: argparse.Namespace) -> int:
    """Execute global-news command."""
    collector = DataCollector(data_dir=args.data_dir)
    as_of_date = args.date or datetime.now().strftime("%Y-%m-%d")

    print(f"Collecting global news as of {as_of_date}...")

    result = collector.collect_global_news(as_of_date)

    if result.success:
        print(f"Success: {result.files}")
        return 0
    else:
        print(f"Failed: {result.errors}")
        return 1


def cmd_status(args: argparse.Namespace) -> int:
    """Execute status command."""
    collector = DataCollector(data_dir=args.data_dir)
    symbol = args.symbol.strip().upper() if args.symbol else None

    files = collector.list_collected_files(symbol)

    if not files:
        print(f"No data files found" + (f" for {symbol}" if symbol else ""))
        return 0

    print(f"Collected files" + (f" for {symbol}" if symbol else "") + ":")
    for f in files:
        print(
            f"  {f['filename']}: {f['task_type']} ({f['as_of_date']}) - {f['collected_at']}"
        )

    return 0


def cmd_list_tasks(args: argparse.Namespace) -> int:
    """Execute list command to show available tasks."""
    print("Available collection tasks:")
    for task in COLLECTION_TASKS:
        status = "enabled" if task.enabled else "disabled"
        print(f"  {task.task_type}: {task.tool_name} [{status}]")
    print(f"  global_news: market_tool.get_global_news [enabled]")
    return 0


def cmd_consolidate(args: argparse.Namespace) -> int:
    """Execute consolidate command to merge cn_fund_all CSV into daily + static tables."""
    from data_manager.consolidation import consolidate_csv, consolidate_date_range

    data_dir = getattr(args, "data_dir", None) or "datasets/raw"
    output = getattr(args, "output", "both") or "both"
    dry_run = getattr(args, "dry_run", False)

    if getattr(args, "date_from", None) and getattr(args, "date_to", None):
        results = consolidate_date_range(
            data_dir, args.date_from, args.date_to, output=output, dry_run=dry_run
        )
        for date_str, r in results.items():
            print(f"  {date_str}: {r.files_processed} files -> {r.output_files}")
            if r.errors:
                for e in r.errors:
                    print(f"    Error: {e}")
        return 0 if all(not r.errors for r in results.values()) else 1

    date_str = args.date or datetime.now().strftime("%Y-%m-%d")
    print(f"Consolidating cn_fund_all CSV for {date_str}...")
    result = consolidate_csv(data_dir, date_str, output=output, dry_run=dry_run)

    print(f"  Processed: {result.files_processed} fund(s)")
    for fname, count in result.output_files.items():
        print(f"  Wrote {fname}: {count} rows")
    if result.errors:
        for e in result.errors:
            print(f"  Error: {e}")
        return 1
    if dry_run:
        print("  (dry-run, no files written)")
    return 0


def cmd_distribute_funds(args: argparse.Namespace) -> int:
    """Execute distribute-funds command."""
    distributor = DataDistributor(
        data_dir=args.data_dir,
        processed_dir=args.processed_dir,
        failed_dir=args.failed_dir,
    )

    funds_dir = args.funds_dir

    if args.file:
        print(f"Distributing fund file: {args.file}")
        batch = distributor.distribute_fund_file(
            args.file,
            load_mode=args.load_mode,
            fresh_scope=args.fresh_scope,
        )
    else:
        print(f"Distributing all fund files from {funds_dir}...")
        batch = distributor.distribute_funds_dir(
            funds_dir,
            load_mode=args.load_mode,
            fresh_scope=args.fresh_scope,
        )

    print(f"\nResults:")
    print(f"  Total files: {batch.total_files}")
    print(f"  Success: {batch.success_count}")
    print(f"\nDatabase writes:")
    print(f"  PostgreSQL rows: {batch.postgres_rows}")
    print(f"  Neo4j nodes: {batch.neo4j_nodes}")
    print(f"  Neo4j edges: {batch.neo4j_edges}")
    print(f"  Milvus docs: {batch.milvus_docs}")

    return 0


def cmd_distribute(args: argparse.Namespace) -> int:
    """Execute distribute command."""
    distributor = DataDistributor(
        data_dir=args.data_dir,
        processed_dir=args.processed_dir,
        failed_dir=args.failed_dir,
    )

    move_after = not args.no_move

    if args.all:
        print(f"Distributing all pending files from {args.data_dir}...")
        batch = distributor.distribute_pending(move_after=move_after)
    elif args.symbol:
        symbol = args.symbol.strip().upper()
        print(f"Distributing files for {symbol}...")
        batch = distributor.distribute_symbol(symbol, args.date, move_after=move_after)
    elif args.file:
        print(f"Distributing file: {args.file}")
        result = distributor.distribute_file(args.file, move_after=move_after)
        batch = None
    else:
        print("Error: Specify --symbol, --all, or --file", file=sys.stderr)
        return 1

    if batch:
        print(f"\nResults:")
        print(f"  Total files: {batch.total_files}")
        print(f"  Success: {batch.success_count}")
        print(f"  Failed: {batch.failed_count}")
        print(f"\nDatabase writes:")
        print(f"  PostgreSQL rows: {batch.postgres_rows}")
        print(f"  Neo4j nodes: {batch.neo4j_nodes}")
        print(f"  Neo4j edges: {batch.neo4j_edges}")
        print(f"  Milvus docs: {batch.milvus_docs}")

        if args.verbose:
            print(f"\nDetails:")
            for r in batch.results:
                status = "OK" if r.success else "FAILED"
                print(f"  [{status}] {r.filepath}")
                if r.postgres:
                    print(f"    PostgreSQL: {r.postgres}")
                if r.neo4j:
                    print(f"    Neo4j: {r.neo4j}")
                if r.milvus:
                    print(f"    Milvus: {r.milvus}")
                if r.errors:
                    for err in r.errors:
                        print(f"    Error: {err}")

        return 0 if batch.failed_count == 0 else 1
    else:
        status = "OK" if result.success else "FAILED"
        print(f"\n[{status}] {result.filepath}")
        if result.postgres:
            print(f"  PostgreSQL: {result.postgres}")
        if result.neo4j:
            print(f"  Neo4j: {result.neo4j}")
        if result.milvus:
            print(f"  Milvus: {result.milvus}")
        if result.errors:
            for err in result.errors:
                print(f"  Error: {err}")
        return 0 if result.success else 1


def cmd_extract_reports(args: argparse.Namespace) -> int:
    """Extract CN fund report PDFs into normalized JSON artifacts."""
    # Align naming: CN domain uses fund_id; keep --symbol alias.
    fund_id = (getattr(args, "fund_id", None) or getattr(args, "symbol", None) or "").strip()
    as_of_date = args.date or datetime.now().strftime("%Y-%m-%d")

    data_dir = args.data_dir or "datasets/raw"
    ingestion_root = os.path.join(data_dir, "ingestion", "cn_fund_all", as_of_date)
    if not os.path.isdir(ingestion_root):
        print(f"Error: ingestion directory not found: {ingestion_root}", file=sys.stderr)
        return 1

    fund_ids: list[str] = []
    if getattr(args, "all", False):
        fund_ids = sorted([d for d in os.listdir(ingestion_root) if os.path.isdir(os.path.join(ingestion_root, d))])
    else:
        if not fund_id:
            print("Error: specify --fund-id/--symbol or use --all", file=sys.stderr)
            return 1
        fund_ids = [fund_id]

    extractor_version = getattr(args, "extractor_version", None) or "v1"
    allow_fallback = bool(getattr(args, "allow_fallback", False))
    include_tables = bool(getattr(args, "include_tables", True))
    total = 0
    ok = 0
    failed = 0

    for fid in fund_ids:
        reports_dir = os.path.join(ingestion_root, fid, "reports")
        if not os.path.isdir(reports_dir):
            continue
        out_dir = os.path.join(ingestion_root, fid, "reports_extracted")
        os.makedirs(out_dir, exist_ok=True)

        for fname in os.listdir(reports_dir):
            if not fname.lower().endswith(".pdf"):
                continue
            total += 1
            pdf_path = os.path.join(reports_dir, fname)
            try:
                artifact = extract_one_pdf(
                    pdf_path=pdf_path,
                    fund_id=fid,
                    as_of_date=as_of_date,
                    extractor_version=extractor_version,
                    allow_fallback=allow_fallback,
                    include_tables=include_tables,
                )
                report_id = str(artifact.get("metadata", {}).get("report_id") or "").strip() or os.path.splitext(fname)[0]

                out_path = os.path.join(out_dir, f"{report_id}.json")
                write_artifact_json(artifact, out_path)
                ok += 1
            except Exception as e:
                failed += 1
                print(f"[FAILED] {pdf_path}: {e}", file=sys.stderr)

    print(f"Extract reports for {as_of_date}: total={total}, ok={ok}, failed={failed}")
    return 0 if failed == 0 else 1


def main(argv: list[str] | None = None) -> int:
    """Main entry point."""
    load_config()
    parser = argparse.ArgumentParser(
        prog="data_manager",
        description="OpenFund-AI data management: collect/distribute data and run backend maintenance commands.",
    )
    parser.add_argument(
        "--data-dir",
        default="datasets/raw",
        help="Root directory for data files (default: datasets/raw)",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    add_backend_subcommands(subparsers)

    # collect command
    collect_parser = subparsers.add_parser(
        "collect", help="Collect data for one or more symbols"
    )
    collect_parser.add_argument(
        "--symbols", "-s", required=True, help="Comma-separated list of symbols"
    )
    collect_parser.add_argument(
        "--date",
        "-d",
        help="Reference date (yyyy-mm-dd), defaults to today",
    )
    collect_parser.add_argument(
        "--tasks",
        "-t",
        help="Comma-separated list of task types (default: all)",
    )
    collect_parser.add_argument(
        "--format",
        "-f",
        choices=["json", "csv", "both"],
        default="json",
        help="Output format: json (default), csv, or both. CSV only for cn_fund_* tasks.",
    )
    collect_parser.add_argument(
        "--no-reports",
        action="store_true",
        help="Skip downloading quarterly/annual report PDFs (cn_fund_all only)",
    )
    collect_parser.add_argument(
        "--json", action="store_true", help="Output results as JSON"
    )

    # global-news command
    global_parser = subparsers.add_parser(
        "global-news", help="Collect global market news"
    )
    global_parser.add_argument(
        "--date",
        "-d",
        help="Reference date (yyyy-mm-dd), defaults to today",
    )

    # status command
    status_parser = subparsers.add_parser(
        "status", help="Show status of collected data"
    )
    status_parser.add_argument(
        "--symbol", "-s", help="Filter by symbol (optional)"
    )

    # list command
    subparsers.add_parser("list", help="List available collection tasks")

    # doctor command
    subparsers.add_parser("doctor", help="Diagnose local environment for data_manager")

    # consolidate command
    consolidate_parser = subparsers.add_parser(
        "consolidate",
        help="Consolidate cn_fund_all raw CSV into daily + static tables",
    )
    consolidate_parser.add_argument(
        "--date", "-d",
        help="Reference date (yyyy-mm-dd), defaults to today",
    )
    consolidate_parser.add_argument(
        "--date-from",
        help="Start date for range (use with --date-to)",
    )
    consolidate_parser.add_argument(
        "--date-to",
        help="End date for range (use with --date-from)",
    )
    consolidate_parser.add_argument(
        "--output", "-o",
        choices=["daily", "static", "both"],
        default="both",
        help="Output: daily, static, or both (default: both)",
    )
    consolidate_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List files only, do not write",
    )
    consolidate_parser.set_defaults(func=cmd_consolidate)

    # distribute command
    dist_parser = subparsers.add_parser(
        "distribute", help="Distribute collected data to databases"
    )
    dist_parser.add_argument(
        "--symbol", "-s", help="Distribute files for a specific symbol"
    )
    dist_parser.add_argument(
        "--all", "-a", action="store_true", help="Distribute all pending files"
    )
    dist_parser.add_argument(
        "--file", "-f", help="Distribute a specific file"
    )
    dist_parser.add_argument(
        "--date", "-d", help="Filter by date (yyyy-mm-dd)"
    )
    dist_parser.add_argument(
        "--processed-dir",
        default="datasets/processed",
        help="Directory for processed files (default: datasets/processed)",
    )
    dist_parser.add_argument(
        "--failed-dir",
        default="datasets/failed",
        help="Directory for failed files (default: datasets/failed)",
    )
    dist_parser.add_argument(
        "--no-move",
        action="store_true",
        help="Don't move files after processing",
    )
    dist_parser.add_argument(
        "--verbose", "-v", action="store_true", help="Show detailed output"
    )

    # distribute-funds command
    dist_funds_parser = subparsers.add_parser(
        "distribute-funds", help="Distribute fund data files to databases"
    )
    dist_funds_parser.add_argument(
        "--funds-dir",
        default="datasets",
        help="Directory containing fund data files (default: datasets)",
    )
    dist_funds_parser.add_argument(
        "--file", "-f", help="Distribute a specific fund file"
    )
    dist_funds_parser.add_argument(
        "--load-mode",
        choices=["existing", "fresh"],
        default="existing",
        help="Load behavior: existing=upsert into current DB, fresh=purge old rows then reload",
    )
    dist_funds_parser.add_argument(
        "--fresh-scope",
        choices=["symbols", "all"],
        default="symbols",
        help='When --load-mode fresh: symbols=purge only symbols in file, all=purge all fund data first',
    )
    dist_funds_parser.add_argument(
        "--processed-dir",
        default="datasets/processed",
        help="Directory for processed files (default: datasets/processed)",
    )
    dist_funds_parser.add_argument(
        "--failed-dir",
        default="datasets/failed",
        help="Directory for failed files (default: datasets/failed)",
    )

    # extract-reports command (CN fund PDF reports)
    extract_parser = subparsers.add_parser(
        "extract-reports",
        help="Extract CN fund report PDFs (annual/quarterly) into normalized JSON artifacts",
    )
    extract_parser.add_argument(
        "--date",
        "-d",
        help="Reference date (yyyy-mm-dd), defaults to today",
    )
    extract_parser.add_argument(
        "--fund-id",
        help="CN fund id (e.g. 001235). Use with --date. Mutually exclusive with --all.",
    )
    extract_parser.add_argument(
        "--symbol",
        help="Alias of --fund-id (kept for compatibility with other commands).",
    )
    extract_parser.add_argument(
        "--all",
        action="store_true",
        help="Process all funds under datasets/raw/ingestion/cn_fund_all/<date>/",
    )
    extract_parser.add_argument(
        "--extractor-version",
        default="v1",
        help="Extractor version tag written into artifact metadata (default: v1)",
    )
    extract_parser.add_argument(
        "--allow-fallback",
        action="store_true",
        help="If Docling fails to import/parse, fall back to plain text extraction (requires pypdf).",
    )
    extract_parser.add_argument(
        "--no-include-tables",
        action="store_true",
        help="Disable table extraction into JSON content.tables.",
    )

    args = parser.parse_args(argv)

    func = getattr(args, "func", None)
    if callable(func):
        return func(args)

    if args.command == "collect":
        return cmd_collect(args)
    elif args.command == "global-news":
        return cmd_global_news(args)
    elif args.command == "status":
        return cmd_status(args)
    elif args.command == "list":
        return cmd_list_tasks(args)
    elif args.command == "consolidate":
        return cmd_consolidate(args)
    elif args.command == "distribute":
        return cmd_distribute(args)
    elif args.command == "distribute-funds":
        return cmd_distribute_funds(args)
    elif args.command == "extract-reports":
        # argparse provides no_include_tables; convert to explicit positive flag used by cmd.
        setattr(args, "include_tables", not bool(getattr(args, "no_include_tables", False)))
        return cmd_extract_reports(args)
    elif args.command == "doctor":
        report = format_doctor_report(run_doctor())
        print(report)
        # Non-zero exit if critical checks failed
        if "FAIL" in report:
            return 1
        return 0
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
