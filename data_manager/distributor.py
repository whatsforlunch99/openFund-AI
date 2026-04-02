"""DataDistributor: read local files and write to PostgreSQL, Neo4j, Milvus.

Uses MCP tools (sql_tool, kg_tool, vector_tool) to distribute collected data
to the appropriate databases based on classification rules.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from openfund_mcp.tools import sql_tool, kg_tool, vector_tool
from data_manager.classifier import DataClassifier
from data_manager.transformer import DataTransformer
from data_manager.schemas import POSTGRES_DDL, POSTGRES_UPSERT_TEMPLATES, NEO4J_CYPHER_TEMPLATES

logger = logging.getLogger(__name__)


@dataclass
class DistributionResult:
    """Result of distributing a single file."""

    filepath: str
    symbol: str
    task_type: str
    success: bool = True
    postgres: dict = field(default_factory=dict)
    neo4j: dict = field(default_factory=dict)
    milvus: dict = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


@dataclass
class BatchDistributionResult:
    """Result of batch distribution."""

    total_files: int = 0
    success_count: int = 0
    failed_count: int = 0
    results: list[DistributionResult] = field(default_factory=list)
    postgres_rows: int = 0
    neo4j_nodes: int = 0
    neo4j_edges: int = 0
    milvus_docs: int = 0


class DataDistributor:
    """Distribute local data files to various databases."""

    def __init__(
        self,
        data_dir: str = "datasets/raw",
        processed_dir: str = "datasets/processed",
        failed_dir: str = "datasets/failed",
    ):
        """
        Initialize DataDistributor.

        Args:
            data_dir: Directory containing raw data files.
            processed_dir: Directory to move successfully processed files.
            failed_dir: Directory to move failed files.
        """
        self.data_dir = data_dir
        self.processed_dir = processed_dir
        self.failed_dir = failed_dir
        self.classifier = DataClassifier()
        self._schema_initialized = False

        for d in [processed_dir, failed_dir]:
            os.makedirs(d, exist_ok=True)

    def _ensure_postgres_schema(self) -> bool:
        """Create PostgreSQL tables if they don't exist."""
        if self._schema_initialized:
            return True

        if not os.environ.get("DATABASE_URL"):
            logger.debug("DATABASE_URL not set, skipping PostgreSQL schema init")
            return False

        result = sql_tool.run_query(POSTGRES_DDL)
        if result.get("error"):
            logger.error("Failed to create PostgreSQL schema: %s", result["error"])
            return False

        self._schema_initialized = True
        logger.info("PostgreSQL schema initialized")
        return True

    def _read_data_file(self, filepath: str) -> dict | None:
        """Read and parse a data file."""
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error("Failed to read %s: %s", filepath, e)
            return None

    def _write_to_postgres(
        self, table: str, rows: list[dict]
    ) -> tuple[int, str | None]:
        """
        Write rows to PostgreSQL using UPSERT.

        Returns:
            Tuple of (rows_written, error_message).
        """
        if not rows:
            return 0, None

        if not os.environ.get("DATABASE_URL"):
            logger.debug("DATABASE_URL not set, skipping PostgreSQL write")
            return 0, "DATABASE_URL not set"

        self._ensure_postgres_schema()

        template = POSTGRES_UPSERT_TEMPLATES.get(table)
        if not template:
            return 0, f"No upsert template for table: {table}"

        # Row-by-row execution keeps failures isolated to bad records.
        written = 0
        for row in rows:
            result = sql_tool.run_query(template, row)
            if result.get("error"):
                logger.warning("PostgreSQL insert failed: %s", result["error"])
                continue
            written += 1

        return written, None

    def _write_to_neo4j(
        self, nodes: list[dict], edges: list[dict]
    ) -> tuple[int, int, str | None]:
        """
        Write nodes and edges to Neo4j.

        Returns:
            Tuple of (nodes_created, edges_created, error_message).
        """
        if not nodes and not edges:
            return 0, 0, None

        if not os.environ.get("NEO4J_URI"):
            logger.debug("NEO4J_URI not set, skipping Neo4j write")
            return 0, 0, "NEO4J_URI not set"

        nodes_created = 0
        edges_created = 0

        for node in nodes:
            label = node.get("label")
            if not label:
                continue

            if label == "Company":
                cypher = NEO4J_CYPHER_TEMPLATES["merge_company"]
                params = {
                    "symbol": node.get("symbol"),
                    "name": node.get("name"),
                    "market_cap": node.get("market_cap"),
                    "exchange": node.get("exchange"),
                    "currency": node.get("currency"),
                    "country": node.get("country"),
                    "city": node.get("city"),
                    "employees": node.get("employees"),
                    "website": node.get("website"),
                    "collected_at": node.get("collected_at"),
                }
            elif label == "Sector":
                cypher = NEO4J_CYPHER_TEMPLATES["merge_sector"]
                params = {"name": node.get("name")}
            elif label == "Industry":
                cypher = NEO4J_CYPHER_TEMPLATES["merge_industry"]
                params = {"name": node.get("name")}
            elif label == "Officer":
                cypher = NEO4J_CYPHER_TEMPLATES["merge_officer"]
                params = {"name": node.get("name"), "age": node.get("age")}
            elif label == "Fund":
                cypher = NEO4J_CYPHER_TEMPLATES["merge_fund"]
                params = {
                    "symbol": node.get("symbol"),
                    "name": node.get("name"),
                    "category": node.get("category"),
                    "index_tracked": node.get("index_tracked"),
                    "investment_style": node.get("investment_style"),
                    "total_assets_billion": node.get("total_assets_billion"),
                    "expense_ratio": node.get("expense_ratio"),
                    "collected_at": node.get("collected_at"),
                }
            else:
                result = kg_tool.bulk_create_nodes([node], label=label)
                if not result.get("error"):
                    nodes_created += result.get("created", 0)
                continue

            result = kg_tool.query_graph(cypher, params)
            if not result.get("error"):
                nodes_created += 1
            else:
                logger.warning("Neo4j node creation failed: %s", result["error"])

        for edge in edges:
            edge_type = edge.get("type")
            from_key = edge.get("from_key")
            to_key = edge.get("to_key")
            props = edge.get("properties", {})

            if edge_type == "IN_SECTOR":
                cypher = NEO4J_CYPHER_TEMPLATES["link_company_sector"]
                params = {"symbol": from_key, "sector_name": to_key}
            elif edge_type == "IN_INDUSTRY":
                cypher = NEO4J_CYPHER_TEMPLATES["link_company_industry"]
                params = {"symbol": from_key, "industry_name": to_key}
            elif edge_type == "HAS_OFFICER":
                cypher = NEO4J_CYPHER_TEMPLATES["link_company_officer"]
                params = {
                    "symbol": from_key,
                    "officer_name": to_key,
                    "title": props.get("title"),
                    "total_pay": props.get("total_pay"),
                }
            elif edge_type == "HOLDS":
                cypher = NEO4J_CYPHER_TEMPLATES["link_fund_holding"]
                params = {
                    "fund_symbol": from_key,
                    "holding_symbol": to_key,
                    "holding_name": props.get("holding_name", ""),
                    "weight": props.get("weight"),
                    "as_of_date": props.get("as_of_date", ""),
                }
            elif edge_type == "INVESTS_IN_SECTOR":
                cypher = NEO4J_CYPHER_TEMPLATES["link_fund_sector"]
                params = {
                    "symbol": from_key,
                    "sector_name": to_key,
                    "weight": props.get("weight"),
                }
            else:
                continue

            result = kg_tool.query_graph(cypher, params)
            if not result.get("error"):
                edges_created += 1
            else:
                logger.warning("Neo4j edge creation failed: %s", result["error"])

        return nodes_created, edges_created, None

    def _write_to_milvus(self, docs: list[dict]) -> tuple[int, str | None]:
        """
        Write documents to Milvus (with embedding).

        Returns:
            Tuple of (docs_indexed, error_message).
        """
        if not docs:
            return 0, None

        if not os.environ.get("MILVUS_URI"):
            logger.debug("MILVUS_URI not set, skipping Milvus write")
            return 0, "MILVUS_URI not set"

        milvus_docs = []
        for doc in docs:
            milvus_docs.append(
                {
                    "id": doc.get("id"),
                    "content": doc.get("content", ""),
                    "fund_id": doc.get("symbol", ""),
                    "source": doc.get("source", "data_manager"),
                }
            )

        result = vector_tool.upsert_documents(milvus_docs)
        if result.get("error"):
            return 0, result["error"]

        return result.get("upserted", 0), None

    def _move_file(self, filepath: str, dest_dir: str) -> str:
        """Move file to destination directory, preserving symbol subdirectory."""
        parts = filepath.replace("\\", "/").split("/")
        if len(parts) >= 2:
            symbol_dir = parts[-2]
            dest_symbol_dir = os.path.join(dest_dir, symbol_dir)
            os.makedirs(dest_symbol_dir, exist_ok=True)
            dest_path = os.path.join(dest_symbol_dir, parts[-1])
        else:
            dest_path = os.path.join(dest_dir, os.path.basename(filepath))

        shutil.move(filepath, dest_path)
        return dest_path

    def distribute_file(
        self, filepath: str, move_after: bool = True
    ) -> DistributionResult:
        """
        Distribute a single data file to target databases.

        Args:
            filepath: Path to the data file.
            move_after: Whether to move file to processed/failed dir after.

        Returns:
            DistributionResult with details.
        """
        data = self._read_data_file(filepath)
        if not data:
            result = DistributionResult(
                filepath=filepath,
                symbol="",
                task_type="",
                success=False,
                errors=["Failed to read file"],
            )
            if move_after:
                self._move_file(filepath, self.failed_dir)
            return result

        metadata = data.get("metadata", {})
        # CN domain prefers fund_id; keep backward compatibility with existing `symbol`.
        symbol = metadata.get("fund_id") or metadata.get("symbol", "")
        task_type = metadata.get("task_type", "")
        as_of_date = metadata.get("as_of_date", "")
        collected_at = metadata.get("collected_at", "")
        content = data.get("content", "")

        result = DistributionResult(
            filepath=filepath,
            symbol=symbol,
            task_type=task_type,
        )

        transformer = DataTransformer(collected_at=collected_at)

        # CN aggregated ingestion: split one payload into multiple curated writes.
        if task_type == "cn_fund_all":
            if not isinstance(content, dict):
                result.success = False
                result.errors.append("cn_fund_all content is not a dict")
                if move_after:
                    self._move_file(filepath, self.failed_dir)
                return result

            # Ensure schema exists before writes (graceful skip if DATABASE_URL unset).
            self._ensure_postgres_schema()

            fund_id = symbol
            # basic
            basic = content.get("basic")
            if isinstance(basic, dict) and not basic.get("error"):
                table, rows = transformer.to_postgres_rows("cn_fund_basic", fund_id, basic, as_of_date)
                if rows:
                    written, error = self._write_to_postgres(table, rows)
                    result.postgres.setdefault("tables", {})
                    result.postgres["tables"][table] = {"rows_written": written}
                    if error:
                        result.errors.append(f"PostgreSQL: {error}")
            # nav
            nav = content.get("nav")
            nav_items = []
            if isinstance(nav, dict) and not nav.get("error"):
                items = nav.get("items") or []
                fmt = str(nav.get("items_format") or "rows").strip().lower()
                if fmt == "columns" and isinstance(items, dict):
                    # Packed format: {nav_date: [...], nav: [...], nav_accumulated: [...]}
                    dates = items.get("nav_date") or []
                    navs = items.get("nav") or []
                    nav_accs = items.get("nav_accumulated") or []
                    if isinstance(dates, list) and isinstance(navs, list) and isinstance(nav_accs, list):
                        n = min(len(dates), len(navs), len(nav_accs))
                        nav_items = [
                            {"nav_date": dates[i], "nav": navs[i], "nav_accumulated": nav_accs[i], "source": "akshare"}
                            for i in range(n)
                        ]
                elif fmt == "triples" and isinstance(items, list):
                    # Packed triples: [[nav_date, nav, nav_accumulated], ...]
                    nav_items = []
                    for row in items:
                        if not isinstance(row, list) or len(row) < 2:
                            continue
                        nav_date = row[0]
                        nav_val = row[1] if len(row) >= 2 else None
                        nav_acc = row[2] if len(row) >= 3 else None
                        nav_items.append(
                            {
                                "nav_date": nav_date,
                                "nav": nav_val,
                                "nav_accumulated": nav_acc,
                                "source": "akshare",
                            }
                        )
                else:
                    nav_items = items if isinstance(items, list) else []
            if isinstance(nav_items, list) and nav_items:
                table, rows = transformer.to_postgres_rows("cn_fund_nav", fund_id, nav_items, as_of_date)
                if rows:
                    written, error = self._write_to_postgres(table, rows)
                    result.postgres.setdefault("tables", {})
                    result.postgres["tables"][table] = {"rows_written": written}
                    if error:
                        result.errors.append(f"PostgreSQL: {error}")

            # Note: fee/holdings/rank are returned by cn_fund_tool.get_all for raw replay,
            # but are not distributed into curated tables in this initial implementation.

            no_db_configured = all(err.endswith("not set") for err in result.errors)
            has_writes = bool(result.postgres.get("tables")) if isinstance(result.postgres, dict) else False
            result.success = (not result.errors) or has_writes or no_db_configured
            if move_after:
                self._move_file(filepath, self.processed_dir if result.success else self.failed_dir)
            return result

        # CN fund report extraction: split one payload into multiple curated writes.
        if task_type == "cn_fund_report_extract":
            if not isinstance(content, dict):
                result.success = False
                result.errors.append("cn_fund_report_extract content is not a dict")
                if move_after:
                    self._move_file(filepath, self.failed_dir)
                return result

            self._ensure_postgres_schema()

            fund_id = str(symbol)
            report_id = str(metadata.get("report_id") or content.get("report_id") or "").strip()
            report_type = str(metadata.get("report_type") or "").strip()
            report_date = str(metadata.get("report_date") or "").strip()
            extractor_version = str(metadata.get("extractor_version") or "").strip()
            parser_name = str(metadata.get("parser_name") or "").strip()
            parser_version = str(metadata.get("parser_version") or "").strip()

            # 1) Sections -> PostgreSQL
            sections = content.get("sections") or []
            if isinstance(sections, list) and sections:
                rows = []
                for sec in sections:
                    if not isinstance(sec, dict):
                        continue
                    rows.append(
                        {
                            "fund_id": fund_id,
                            "report_id": report_id,
                            "section_id": str(sec.get("section_id") or "other"),
                            "section_title_raw": sec.get("section_title_raw"),
                            "section_text": sec.get("text"),
                            "section_summary": sec.get("summary"),
                            "report_type": report_type,
                            "report_date": report_date,
                            "collected_at": transformer.collected_at,
                            "extractor_version": extractor_version,
                            "parser_name": parser_name,
                            "parser_version": parser_version,
                        }
                    )
                if rows:
                    written, error = self._write_to_postgres("cn_fund_report_sections", rows)
                    result.postgres.setdefault("tables", {})
                    result.postgres["tables"]["cn_fund_report_sections"] = {"rows_written": written}
                    if error:
                        result.errors.append(f"PostgreSQL: {error}")

            # 2) Signals -> PostgreSQL
            signals = content.get("signals") or {}
            if isinstance(signals, dict) and signals:
                row = {
                    "fund_id": fund_id,
                    "report_id": report_id,
                    "strategy": signals.get("strategy"),
                    "risk": signals.get("risk"),
                    "market_view": signals.get("market_view"),
                    "style": signals.get("style"),
                    "sector_preference_json": json.dumps(
                        signals.get("sector_preference") or [], ensure_ascii=False
                    ),
                    "report_type": report_type,
                    "report_date": report_date,
                    "collected_at": transformer.collected_at,
                    "extractor_version": extractor_version,
                    "parser_name": parser_name,
                    "parser_version": parser_version,
                }
                written, error = self._write_to_postgres("cn_fund_report_signals", [row])
                result.postgres.setdefault("tables", {})
                result.postgres["tables"]["cn_fund_report_signals"] = {"rows_written": written}
                if error:
                    result.errors.append(f"PostgreSQL: {error}")

            # 3) Chunks -> Milvus
            docs = transformer.to_milvus_docs(task_type, fund_id, content, as_of_date)
            if docs:
                indexed, error = self._write_to_milvus(docs)
                result.milvus = {"docs_indexed": indexed}
                if error:
                    result.errors.append(f"Milvus: {error}")

            no_db_configured = all(err.endswith("not set") for err in result.errors)
            has_writes = bool(result.postgres.get("tables")) or result.milvus.get("docs_indexed", 0) > 0
            result.success = (not result.errors) or has_writes or no_db_configured
            if move_after:
                self._move_file(filepath, self.processed_dir if result.success else self.failed_dir)
            return result

        classification = self.classifier.classify(task_type)

        if "postgres" in classification.targets:
            table, rows = transformer.to_postgres_rows(
                task_type, symbol, content, as_of_date
            )
            if rows:
                written, error = self._write_to_postgres(table, rows)
                result.postgres = {"table": table, "rows_written": written}
                if error:
                    result.errors.append(f"PostgreSQL: {error}")

        if "neo4j" in classification.targets:
            nodes, edges = transformer.to_neo4j_nodes_edges(
                task_type, symbol, content, as_of_date
            )
            if nodes or edges:
                nodes_created, edges_created, error = self._write_to_neo4j(nodes, edges)
                result.neo4j = {
                    "nodes_created": nodes_created,
                    "edges_created": edges_created,
                }
                if error:
                    result.errors.append(f"Neo4j: {error}")

        if "milvus" in classification.targets:
            docs = transformer.to_milvus_docs(task_type, symbol, content, as_of_date)
            if docs:
                indexed, error = self._write_to_milvus(docs)
                result.milvus = {"docs_indexed": indexed}
                if error:
                    result.errors.append(f"Milvus: {error}")

        # Success if: no fatal errors, or at least one DB write succeeded, or no DBs configured (graceful skip)
        no_db_configured = all(
            err.endswith("not set") for err in result.errors
        )
        has_writes = any([
            result.postgres.get("rows_written", 0) > 0,
            result.neo4j.get("nodes_created", 0) > 0,
            result.milvus.get("docs_indexed", 0) > 0,
        ])
        result.success = len(result.errors) == 0 or has_writes or no_db_configured

        if move_after:
            if result.success:
                self._move_file(filepath, self.processed_dir)
            else:
                self._move_file(filepath, self.failed_dir)

        return result

    def distribute_symbol(
        self, symbol: str, as_of_date: str | None = None, move_after: bool = True
    ) -> BatchDistributionResult:
        """
        Distribute all data files for a symbol.

        Args:
            symbol: Stock/fund symbol.
            as_of_date: Optional filter by date.
            move_after: Whether to move files after processing.

        Returns:
            BatchDistributionResult.
        """
        batch = BatchDistributionResult()

        # 1) Default behavior: datasets/raw/<SYMBOL>/*.json
        symbol_dir = os.path.join(self.data_dir, symbol.upper())
        if os.path.exists(symbol_dir):
            for filename in os.listdir(symbol_dir):
                if not filename.endswith(".json"):
                    continue

                if as_of_date and as_of_date not in filename:
                    continue

                filepath = os.path.join(symbol_dir, filename)
                batch.total_files += 1

                result = self.distribute_file(filepath, move_after=move_after)
                batch.results.append(result)

                if result.success:
                    batch.success_count += 1
                    batch.postgres_rows += result.postgres.get("rows_written", 0)
                    batch.neo4j_nodes += result.neo4j.get("nodes_created", 0)
                    batch.neo4j_edges += result.neo4j.get("edges_created", 0)
                    batch.milvus_docs += result.milvus.get("docs_indexed", 0)
                else:
                    batch.failed_count += 1

        # 2) CN report extraction artifacts:
        # datasets/raw/ingestion/cn_fund_all/<date>/<fund_id>/reports_extracted/*.json
        ingestion_root = os.path.join(self.data_dir, "ingestion", "cn_fund_all")
        if os.path.isdir(ingestion_root):
            date_dirs: list[str] = []
            if as_of_date:
                date_dirs = [as_of_date]
            else:
                date_dirs = [d for d in os.listdir(ingestion_root) if os.path.isdir(os.path.join(ingestion_root, d))]

            for date_dir in date_dirs:
                fund_dir = os.path.join(ingestion_root, date_dir, symbol.upper())
                extracted_dir = os.path.join(fund_dir, "reports_extracted")
                if not os.path.isdir(extracted_dir):
                    continue
                for fname in os.listdir(extracted_dir):
                    if not fname.endswith(".json"):
                        continue
                    filepath = os.path.join(extracted_dir, fname)
                    batch.total_files += 1
                    result = self.distribute_file(filepath, move_after=move_after)
                    batch.results.append(result)
                    if result.success:
                        batch.success_count += 1
                        if isinstance(result.postgres, dict) and "tables" in result.postgres:
                            for _t, v in (result.postgres.get("tables") or {}).items():
                                if isinstance(v, dict):
                                    batch.postgres_rows += int(v.get("rows_written") or 0)
                        else:
                            batch.postgres_rows += result.postgres.get("rows_written", 0)
                        batch.neo4j_nodes += result.neo4j.get("nodes_created", 0)
                        batch.neo4j_edges += result.neo4j.get("edges_created", 0)
                        batch.milvus_docs += result.milvus.get("docs_indexed", 0)
                    else:
                        batch.failed_count += 1

        return batch

    def distribute_pending(self, move_after: bool = True) -> BatchDistributionResult:
        """
        Distribute all pending data files in data_dir.

        Args:
            move_after: Whether to move files after processing.

        Returns:
            BatchDistributionResult.
        """
        batch = BatchDistributionResult()

        if not os.path.exists(self.data_dir):
            return batch

        # Scan ingestion/cn_fund_all/{date}/{fund_id}/data.json
        ingestion_cn = os.path.join(self.data_dir, "ingestion", "cn_fund_all")
        if os.path.isdir(ingestion_cn):
            for date_dir in os.listdir(ingestion_cn):
                date_path = os.path.join(ingestion_cn, date_dir)
                if not os.path.isdir(date_path):
                    continue
                for fund_id in os.listdir(date_path):
                    fund_path = os.path.join(date_path, fund_id)
                    data_json = os.path.join(fund_path, "data.json")
                    if os.path.isfile(data_json):
                        batch.total_files += 1
                        result = self.distribute_file(data_json, move_after=move_after)
                        batch.results.append(result)
                        if result.success:
                            batch.success_count += 1
                            batch.postgres_rows += result.postgres.get("rows_written", 0)
                            batch.neo4j_nodes += result.neo4j.get("nodes_created", 0)
                            batch.neo4j_edges += result.neo4j.get("edges_created", 0)
                            batch.milvus_docs += result.milvus.get("docs_indexed", 0)
                        else:
                            batch.failed_count += 1

                    # Also scan extracted report artifacts: reports_extracted/*.json
                    extracted_dir = os.path.join(fund_path, "reports_extracted")
                    if os.path.isdir(extracted_dir):
                        for fname in os.listdir(extracted_dir):
                            if not fname.endswith(".json"):
                                continue
                            fpath = os.path.join(extracted_dir, fname)
                            batch.total_files += 1
                            r2 = self.distribute_file(fpath, move_after=move_after)
                            batch.results.append(r2)
                            if r2.success:
                                batch.success_count += 1
                                # postgres may be multi-table for this task; count rows if present.
                                if isinstance(r2.postgres, dict) and "tables" in r2.postgres:
                                    for _t, v in (r2.postgres.get("tables") or {}).items():
                                        if isinstance(v, dict):
                                            batch.postgres_rows += int(v.get("rows_written") or 0)
                                else:
                                    batch.postgres_rows += r2.postgres.get("rows_written", 0)
                                batch.neo4j_nodes += r2.neo4j.get("nodes_created", 0)
                                batch.neo4j_edges += r2.neo4j.get("edges_created", 0)
                                batch.milvus_docs += r2.milvus.get("docs_indexed", 0)
                            else:
                                batch.failed_count += 1

        for entry in os.listdir(self.data_dir):
            entry_path = os.path.join(self.data_dir, entry)
            if not os.path.isdir(entry_path):
                continue

            for filename in os.listdir(entry_path):
                if not filename.endswith(".json"):
                    continue

                filepath = os.path.join(entry_path, filename)
                batch.total_files += 1

                result = self.distribute_file(filepath, move_after=move_after)
                batch.results.append(result)

                if result.success:
                    batch.success_count += 1
                    batch.postgres_rows += result.postgres.get("rows_written", 0)
                    batch.neo4j_nodes += result.neo4j.get("nodes_created", 0)
                    batch.neo4j_edges += result.neo4j.get("edges_created", 0)
                    batch.milvus_docs += result.milvus.get("docs_indexed", 0)
                else:
                    batch.failed_count += 1

        logger.info(
            "Distribution complete: %d files, %d success, %d failed",
            batch.total_files,
            batch.success_count,
            batch.failed_count,
        )
        logger.info(
            "  PostgreSQL: %d rows, Neo4j: %d nodes/%d edges, Milvus: %d docs",
            batch.postgres_rows,
            batch.neo4j_nodes,
            batch.neo4j_edges,
            batch.milvus_docs,
        )

        return batch

    def distribute_fund_file(
        self,
        filepath: str,
        move_after: bool = False,
        load_mode: str = "existing",
        fresh_scope: str = "symbols",
    ) -> BatchDistributionResult:
        """
        Distribute a fund data file (multiple funds in one file) to target databases.

        Fund files have a different structure: top-level keys are fund categories,
        each containing a list of fund objects with symbol, name, performance, etc.

        Args:
            filepath: Path to the fund data file.
            move_after: Whether to move file after processing (default False for fund files).
            load_mode: "existing" (upsert into existing DB) or "fresh" (delete old copies first).
            fresh_scope: When load_mode="fresh", "symbols" purges only symbols in this file,
                "all" purges all fund data tables before loading.

        Returns:
            BatchDistributionResult with details.
        """
        import json

        batch = BatchDistributionResult()

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.error("Failed to read fund file %s: %s", filepath, e)
            return batch

        # Resolve file-level defaults first; per-fund fields can override later.
        metadata = data.get("metadata", {})
        metadata_as_of_date = str(metadata.get("as_of_date") or "").strip()
        collected_at = (
            str(metadata.get("last_updated") or "").strip()
            or str(metadata.get("generated_at") or "").strip()
            or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        )

        transformer = DataTransformer(collected_at=collected_at)

        # Parse heterogeneous top-level structure into a flat list of fund dicts.
        funds_processed = []
        pending_funds: list[dict] = []
        for key, value in data.items():
            if key == "metadata":
                continue

            fund_list = value if isinstance(value, list) else [value]

            for fund in fund_list:
                if not isinstance(fund, dict):
                    continue

                symbol = fund.get("symbol")
                if not symbol:
                    continue

                pending_funds.append(fund)
                funds_processed.append(symbol)
        if load_mode == "fresh":
            # Fresh mode removes old copies before writing the new snapshot.
            self._purge_fund_data(
                symbols=sorted({str(f.get("symbol", "")).strip().upper() for f in pending_funds if f.get("symbol")}),
                scope=fresh_scope,
            )

        for fund in pending_funds:
            # Compute effective as_of_date per fund: fund-level > metadata-level > today.
            symbol = str(fund.get("symbol", "")).strip().upper()
            effective_as_of_date = (
                str(fund.get("as_of_date") or "").strip()
                or metadata_as_of_date
                or datetime.now(timezone.utc).strftime("%Y-%m-%d")
            )
            fund["as_of_date"] = effective_as_of_date

            # 1) Core fund profile rows + fund node.
            table, rows = transformer._transform_fund_info(symbol, fund)
            if rows:
                written, _ = self._write_to_postgres(table, rows)
                batch.postgres_rows += written

            nodes, edges = transformer._fund_info_to_neo4j(symbol, fund)
            if nodes:
                nodes_created, edges_created, _ = self._write_to_neo4j(nodes, edges)
                batch.neo4j_nodes += nodes_created
                batch.neo4j_edges += edges_created

            # 2) Time-series style single-row tables.
            if fund.get("performance"):
                fund_perf = {"performance": fund["performance"], "as_of_date": effective_as_of_date}
                table, rows = transformer._transform_fund_performance(symbol, fund_perf)
                if rows:
                    written, _ = self._write_to_postgres(table, rows)
                    batch.postgres_rows += written

            if fund.get("risk_metrics"):
                fund_risk = {"risk_metrics": fund["risk_metrics"], "as_of_date": effective_as_of_date}
                table, rows = transformer._transform_fund_risk(symbol, fund_risk)
                if rows:
                    written, _ = self._write_to_postgres(table, rows)
                    batch.postgres_rows += written

            # 3) Holdings and holdings graph edges.
            if fund.get("top_10_holdings"):
                holdings_data = {"top_10_holdings": fund["top_10_holdings"], "as_of_date": effective_as_of_date}
                table, rows = transformer._transform_fund_holdings(symbol, holdings_data)
                if rows:
                    written, _ = self._write_to_postgres(table, rows)
                    batch.postgres_rows += written

                nodes, edges = transformer._fund_holdings_to_neo4j(symbol, holdings_data)
                if nodes or edges:
                    nodes_created, edges_created, _ = self._write_to_neo4j(nodes, edges)
                    batch.neo4j_nodes += nodes_created
                    batch.neo4j_edges += edges_created

            # 4) Sector allocations and sector edges.
            if fund.get("sector_allocation") or fund.get("sector_distribution"):
                sectors = fund.get("sector_allocation") or fund.get("sector_distribution")
                sectors_data = {"sector_allocation": sectors, "as_of_date": effective_as_of_date}
                table, rows = transformer._transform_fund_sectors(symbol, sectors_data)
                if rows:
                    written, _ = self._write_to_postgres(table, rows)
                    batch.postgres_rows += written

                nodes, edges = transformer._fund_sectors_to_neo4j(symbol, sectors_data)
                if nodes or edges:
                    nodes_created, edges_created, _ = self._write_to_neo4j(nodes, edges)
                    batch.neo4j_nodes += nodes_created
                    batch.neo4j_edges += edges_created

            # 5) Flow statistics.
            if fund.get("fund_flows_2025") or fund.get("fund_flows"):
                flows_payload = fund.get("fund_flows_2025") or fund.get("fund_flows")
                flows_data = {"fund_flows_2025": flows_payload, "as_of_date": effective_as_of_date}
                table, rows = transformer._transform_fund_flows(symbol, flows_data)
                if rows:
                    written, _ = self._write_to_postgres(table, rows)
                    batch.postgres_rows += written

            # 6) Optional company fundamentals row.
            if fund.get("company_fundamentals"):
                cf = fund["company_fundamentals"]
                if isinstance(cf, dict):
                    cf_row = {
                        "symbol": symbol,
                        "as_of_date": str(cf.get("as_of_date") or "").strip() or effective_as_of_date,
                        "name": fund.get("name") or cf.get("name"),
                        "sector": cf.get("sector"),
                        "industry": cf.get("industry"),
                        "market_cap": cf.get("market_cap"),
                        "pe_ratio": cf.get("pe_ratio"),
                        "forward_pe": cf.get("forward_pe"),
                        "peg_ratio": cf.get("peg_ratio"),
                        "price_to_book": cf.get("price_to_book"),
                        "eps_ttm": cf.get("eps_ttm"),
                        "dividend_yield": cf.get("dividend_yield"),
                        "beta": cf.get("beta"),
                        "fifty_two_week_high": cf.get("fifty_two_week_high"),
                        "fifty_two_week_low": cf.get("fifty_two_week_low"),
                        "collected_at": str(cf.get("collected_at") or "").strip() or transformer.collected_at,
                    }
                    written, _ = self._write_to_postgres("company_fundamentals", [cf_row])
                    batch.postgres_rows += written

        batch.total_files = 1
        batch.success_count = 1 if funds_processed else 0

        logger.info(
            "Distributed fund file %s: %d funds processed, %d PostgreSQL rows, %d Neo4j nodes/%d edges",
            filepath,
            len(funds_processed),
            batch.postgres_rows,
            batch.neo4j_nodes,
            batch.neo4j_edges,
        )

        return batch

    def _purge_fund_data(self, symbols: list[str], scope: str = "symbols") -> None:
        """Delete previously loaded fund data before a fresh load.

        Args:
            symbols: Fund symbols from incoming data file.
            scope: "symbols" to purge only incoming symbols, "all" to purge all fund rows.
        """
        if not symbols and scope != "all":
            return

        # Purge relational rows first to avoid stale duplicates on fresh reload.
        if os.environ.get("DATABASE_URL"):
            if scope == "all":
                statements = [
                    "DELETE FROM fund_sector_allocation",
                    "DELETE FROM fund_holdings",
                    "DELETE FROM fund_flows",
                    "DELETE FROM fund_risk_metrics",
                    "DELETE FROM fund_performance",
                    "DELETE FROM fund_info",
                    "DELETE FROM company_fundamentals",
                ]
                for q in statements:
                    sql_tool.run_query(q)
            else:
                for symbol in symbols:
                    params = {"symbol": symbol}
                    sql_tool.run_query(
                        "DELETE FROM fund_sector_allocation WHERE symbol = %(symbol)s",
                        params,
                    )
                    sql_tool.run_query(
                        "DELETE FROM fund_holdings WHERE fund_symbol = %(symbol)s",
                        params,
                    )
                    sql_tool.run_query(
                        "DELETE FROM fund_flows WHERE symbol = %(symbol)s",
                        params,
                    )
                    sql_tool.run_query(
                        "DELETE FROM fund_risk_metrics WHERE symbol = %(symbol)s",
                        params,
                    )
                    sql_tool.run_query(
                        "DELETE FROM fund_performance WHERE symbol = %(symbol)s",
                        params,
                    )
                    sql_tool.run_query(
                        "DELETE FROM fund_info WHERE symbol = %(symbol)s",
                        params,
                    )
                    sql_tool.run_query(
                        "DELETE FROM company_fundamentals WHERE symbol = %(symbol)s",
                        params,
                    )

        # Purge graph nodes for affected funds (or all funds when scope=all).
        if os.environ.get("NEO4J_URI"):
            if scope == "all":
                kg_tool.query_graph("MATCH (f:Fund) DETACH DELETE f")
            else:
                for symbol in symbols:
                    kg_tool.query_graph(
                        "MATCH (f:Fund {symbol: $symbol}) DETACH DELETE f",
                        {"symbol": symbol},
                    )

        # Purge vector entries by fund_id; use tautology expr for full wipe.
        if os.environ.get("MILVUS_URI"):
            if scope == "all":
                vector_tool.delete_by_expr('fund_id != ""')
            else:
                for symbol in symbols:
                    vector_tool.delete_by_expr(f'fund_id == "{symbol}"')

    def distribute_funds_dir(
        self,
        funds_dir: str = "datasets",
        load_mode: str = "existing",
        fresh_scope: str = "symbols",
    ) -> BatchDistributionResult:
        """
        Distribute all fund data files in a directory.

        Args:
            funds_dir: Directory containing fund data files.

        Returns:
            BatchDistributionResult with combined results.
        """
        import os

        batch = BatchDistributionResult()

        if not os.path.exists(funds_dir):
            logger.warning("Funds directory not found: %s", funds_dir)
            return batch

        for filename in os.listdir(funds_dir):
            if not filename.endswith(".json"):
                continue

            filepath = os.path.join(funds_dir, filename)
            result = self.distribute_fund_file(
                filepath,
                load_mode=load_mode,
                fresh_scope=fresh_scope,
            )

            batch.total_files += result.total_files
            batch.success_count += result.success_count
            batch.postgres_rows += result.postgres_rows
            batch.neo4j_nodes += result.neo4j_nodes
            batch.neo4j_edges += result.neo4j_edges
            batch.milvus_docs += result.milvus_docs

        logger.info(
            "Funds distribution complete: %d files, %d PostgreSQL rows, %d Neo4j nodes/%d edges",
            batch.total_files,
            batch.postgres_rows,
            batch.neo4j_nodes,
            batch.neo4j_edges,
        )

        return batch
