"""DataDistributor: read local files and write to PostgreSQL, Neo4j, Milvus.

Uses MCP tools (sql_tool, kg_tool, vector_tool) to distribute collected data
to the appropriate databases based on classification rules.

Supports optional permission tagging via PermissionEngine for access control.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from mcp.tools import sql_tool, kg_tool, vector_tool
from data_manager.classifier import DataClassifier
from data_manager.transformer import DataTransformer
from data_manager.schemas import POSTGRES_DDL, POSTGRES_UPSERT_TEMPLATES, NEO4J_CYPHER_TEMPLATES

logger = logging.getLogger(__name__)


def _get_permission_engine():
    """Lazy-load permission engine to avoid circular imports."""
    try:
        from permission.engine import get_permission_engine
        return get_permission_engine()
    except ImportError:
        return None


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
        enable_permissions: bool = True,
    ):
        """
        Initialize DataDistributor.

        Args:
            data_dir: Directory containing raw data files.
            processed_dir: Directory to move successfully processed files.
            failed_dir: Directory to move failed files.
            enable_permissions: Whether to apply permission tagging (default True).
        """
        self.data_dir = data_dir
        self.processed_dir = processed_dir
        self.failed_dir = failed_dir
        self.classifier = DataClassifier()
        self._schema_initialized = False
        self._milvus_checked = False
        self._milvus_available = False
        self.enable_permissions = enable_permissions
        self._permission_engine = None
        if enable_permissions:
            self._permission_engine = _get_permission_engine()

        for d in [processed_dir, failed_dir]:
            os.makedirs(d, exist_ok=True)

    def _tag_data_with_permissions(
        self, data: dict, source: str, owner: str = "data_manager"
    ) -> dict | None:
        """Apply permission tags to data if engine is available.

        Returns:
            access_control dict if permissions enabled, else None.
        """
        if not self._permission_engine:
            return None
        tagged = self._permission_engine.tag_data(data, source=source, owner=owner)
        return tagged.get("access_control")

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

        if self._milvus_checked and not self._milvus_available:
            return 0, "Milvus not available (cached)"

        if not self._milvus_checked:
            self._milvus_checked = True
            health = vector_tool.health_check()
            if not health.get("ok"):
                error_msg = health.get("error", "Milvus not available")
                logger.info("Milvus not available: %s, skipping Milvus writes", error_msg)
                self._milvus_available = False
                return 0, error_msg
            self._milvus_available = True

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
        symbol = metadata.get("symbol", "")
        task_type = metadata.get("task_type", "")
        as_of_date = metadata.get("as_of_date", "")
        collected_at = metadata.get("collected_at", "")
        content = data.get("content", "")

        result = DistributionResult(
            filepath=filepath,
            symbol=symbol,
            task_type=task_type,
        )

        classification = self.classifier.classify(task_type)
        transformer = DataTransformer(collected_at=collected_at)

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
        symbol_dir = os.path.join(self.data_dir, symbol.upper())
        if not os.path.exists(symbol_dir):
            return BatchDistributionResult()

        batch = BatchDistributionResult()

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
        self, filepath: str, move_after: bool = False
    ) -> BatchDistributionResult:
        """
        Distribute a fund data file (multiple funds in one file) to target databases.

        Fund files have a different structure: top-level keys are fund categories,
        each containing a list of fund objects with symbol, name, performance, etc.

        Args:
            filepath: Path to the fund data file.
            move_after: Whether to move file after processing (default False for fund files).

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

        metadata = data.get("metadata", {})
        as_of_date = metadata.get("as_of_date", "")
        collected_at = metadata.get("last_updated", self.classifier.__class__.__name__)
        data_sources = metadata.get("data_sources", [])

        source_name = "fund_data"
        if data_sources:
            source_name = "_".join(s.lower().replace(".", "_").replace(" ", "_") for s in data_sources[:2])

        access_control = self._tag_data_with_permissions(
            data=metadata,
            source=source_name,
            owner="data_manager",
        )

        transformer = DataTransformer(collected_at=collected_at, access_control=access_control)

        funds_processed = []
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

                funds_processed.append(symbol)
                fund["as_of_date"] = as_of_date

                table, rows = transformer._transform_fund_info(symbol, fund)
                if rows:
                    written, _ = self._write_to_postgres(table, rows)
                    batch.postgres_rows += written

                nodes, edges = transformer._fund_info_to_neo4j(symbol, fund)
                if nodes:
                    nodes_created, edges_created, _ = self._write_to_neo4j(nodes, edges)
                    batch.neo4j_nodes += nodes_created
                    batch.neo4j_edges += edges_created

                if fund.get("performance"):
                    fund_perf = {"performance": fund["performance"], "as_of_date": as_of_date}
                    table, rows = transformer._transform_fund_performance(symbol, fund_perf)
                    if rows:
                        written, _ = self._write_to_postgres(table, rows)
                        batch.postgres_rows += written

                if fund.get("risk_metrics"):
                    fund_risk = {"risk_metrics": fund["risk_metrics"], "as_of_date": as_of_date}
                    table, rows = transformer._transform_fund_risk(symbol, fund_risk)
                    if rows:
                        written, _ = self._write_to_postgres(table, rows)
                        batch.postgres_rows += written

                if fund.get("top_10_holdings"):
                    holdings_data = {"top_10_holdings": fund["top_10_holdings"], "as_of_date": as_of_date}
                    table, rows = transformer._transform_fund_holdings(symbol, holdings_data)
                    if rows:
                        written, _ = self._write_to_postgres(table, rows)
                        batch.postgres_rows += written

                    nodes, edges = transformer._fund_holdings_to_neo4j(symbol, holdings_data)
                    if nodes or edges:
                        nodes_created, edges_created, _ = self._write_to_neo4j(nodes, edges)
                        batch.neo4j_nodes += nodes_created
                        batch.neo4j_edges += edges_created

                if fund.get("sector_allocation") or fund.get("sector_distribution"):
                    sectors = fund.get("sector_allocation") or fund.get("sector_distribution")
                    sectors_data = {"sector_allocation": sectors, "as_of_date": as_of_date}
                    table, rows = transformer._transform_fund_sectors(symbol, sectors_data)
                    if rows:
                        written, _ = self._write_to_postgres(table, rows)
                        batch.postgres_rows += written

                    nodes, edges = transformer._fund_sectors_to_neo4j(symbol, sectors_data)
                    if nodes or edges:
                        nodes_created, edges_created, _ = self._write_to_neo4j(nodes, edges)
                        batch.neo4j_nodes += nodes_created
                        batch.neo4j_edges += edges_created

                if fund.get("fund_flows_2025"):
                    flows_data = {"fund_flows_2025": fund["fund_flows_2025"], "as_of_date": as_of_date}
                    table, rows = transformer._transform_fund_flows(symbol, flows_data)
                    if rows:
                        written, _ = self._write_to_postgres(table, rows)
                        batch.postgres_rows += written

                milvus_docs = transformer.fund_to_milvus_doc(symbol, fund)
                if milvus_docs:
                    indexed, _ = self._write_to_milvus(milvus_docs)
                    batch.milvus_docs += indexed

        batch.total_files = 1
        batch.success_count = 1 if funds_processed else 0

        logger.info(
            "Distributed fund file %s: %d funds processed, %d PostgreSQL rows, %d Neo4j nodes/%d edges, %d Milvus docs",
            filepath,
            len(funds_processed),
            batch.postgres_rows,
            batch.neo4j_nodes,
            batch.neo4j_edges,
            batch.milvus_docs,
        )

        return batch

    def distribute_funds_dir(
        self, funds_dir: str = "datasets/funds"
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
            result = self.distribute_fund_file(filepath)

            batch.total_files += result.total_files
            batch.success_count += result.success_count
            batch.postgres_rows += result.postgres_rows
            batch.neo4j_nodes += result.neo4j_nodes
            batch.neo4j_edges += result.neo4j_edges
            batch.milvus_docs += result.milvus_docs

        logger.info(
            "Funds distribution complete: %d files, %d PostgreSQL rows, %d Neo4j nodes/%d edges, %d Milvus docs",
            batch.total_files,
            batch.postgres_rows,
            batch.neo4j_nodes,
            batch.neo4j_edges,
            batch.milvus_docs,
        )

        return batch
