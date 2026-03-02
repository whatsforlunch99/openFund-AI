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
import sys
from datetime import datetime

from config.config import load_config
from data_manager.backend_cli import add_backend_subcommands
from data_manager.collector import DataCollector
from data_manager.distributor import DataDistributor
from data_manager.tasks import COLLECTION_TASKS


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

    batch = collector.collect_batch(symbols, as_of_date, task_types)

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
    elif args.command == "distribute":
        return cmd_distribute(args)
    elif args.command == "distribute-funds":
        return cmd_distribute_funds(args)
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
