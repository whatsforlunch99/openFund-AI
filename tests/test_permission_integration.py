"""Integration tests for permission module with fund data.

Tests that permission tagging works with datasets/funds data and
that access_control metadata can be preserved during database distribution.
"""

import json
import os

import pytest

from permission.models import AccessControl, UserContext, CLEARANCE_HIERARCHY
from permission.policy import PolicyStore, PermissionPolicy
from permission.engine import PermissionEngine
from permission.audit import NullAuditLogger
from permission.filters import SQLFilter, CypherFilter, MilvusFilter


class TestPermissionWithFundData:
    """Test permission tagging with fund data files."""

    @pytest.fixture
    def engine(self):
        """Create permission engine with fund-specific policies."""
        store = PolicyStore()
        store.add_policy(
            PermissionPolicy(
                name="fund_public_data",
                source_pattern=r"^(yfinance|public_api|etf_com|morningstar_public).*",
                default_classification="PUBLIC",
                default_tenant="",
                default_roles=[],
                expiry_days=None,
            )
        )
        store.add_policy(
            PermissionPolicy(
                name="fund_premium_data",
                source_pattern=r"^(morningstar_premium|bloomberg|refinitiv).*",
                default_classification="CONFIDENTIAL",
                default_tenant="",
                default_roles=["premium_user", "analyst"],
                expiry_days=365,
            )
        )
        return PermissionEngine(store, NullAuditLogger())

    @pytest.fixture
    def fund_flows_data(self):
        """Load fund_flows_2025.json data."""
        path = "datasets/funds/fund_flows_2025.json"
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {
            "metadata": {
                "description": "Test fund flows",
                "as_of_date": "2025-02-28",
                "data_sources": ["ETF.com", "Morningstar"],
            },
            "top_fund_flows_2025": [
                {"symbol": "VOO", "name": "Vanguard S&P 500 ETF", "annual_inflow_billion": 137.7}
            ],
        }

    def test_tag_fund_data_public(self, engine, fund_flows_data):
        """Public market data gets PUBLIC classification."""
        tagged = engine.tag_data(
            data=fund_flows_data,
            source="etf_com_fund_flows",
            owner="data_manager",
        )

        assert "access_control" in tagged
        ac = tagged["access_control"]
        assert ac["classification"] == "PUBLIC"
        assert ac["classification_level"] == 0
        assert ac["source"] == "etf_com_fund_flows"
        assert ac["owner"] == "data_manager"

    def test_tag_fund_data_premium(self, engine):
        """Premium data gets CONFIDENTIAL classification."""
        premium_data = {
            "fund_id": "FUND_X",
            "analysis": "Proprietary analysis...",
        }
        tagged = engine.tag_data(
            data=premium_data,
            source="morningstar_premium_analysis",
            owner="analyst_001",
        )

        ac = tagged["access_control"]
        assert ac["classification"] == "CONFIDENTIAL"
        assert ac["classification_level"] == 2
        assert "premium_user" in ac["roles_allowed"] or "analyst" in ac["roles_allowed"]

    def test_access_control_in_fund_record(self, engine, fund_flows_data):
        """Each fund record can have individual access_control."""
        flows = fund_flows_data.get("top_fund_flows_2025", [])
        if not flows:
            pytest.skip("No fund flows data")

        tagged_funds = []
        for fund in flows:
            tagged = engine.tag_data(
                data=fund,
                source="etf_com_fund_flows",
                owner="data_manager",
            )
            tagged_funds.append(tagged)

        for fund in tagged_funds:
            assert "access_control" in fund
            assert fund["access_control"]["classification"] == "PUBLIC"

    def test_user_can_access_public_fund_data(self, engine, fund_flows_data):
        """Anonymous user can access PUBLIC fund data."""
        tagged = engine.tag_data(fund_flows_data, source="etf_com_fund_flows")
        ac = AccessControl.from_dict(tagged["access_control"])

        user = UserContext.anonymous()
        result = engine.evaluate(user, ac, action="read")

        assert result.allowed is True
        assert result.reason == "Public data"

    def test_user_cannot_access_premium_without_role(self, engine):
        """User without premium role cannot access CONFIDENTIAL data."""
        premium_data = {"analysis": "..."}
        tagged = engine.tag_data(premium_data, source="morningstar_premium_analysis")
        ac = AccessControl.from_dict(tagged["access_control"])

        user = UserContext(
            user_id="basic_user",
            tenant_id="default",
            roles=["basic_user"],
            clearance_level="INTERNAL",
        )
        result = engine.evaluate(user, ac, action="read")

        assert result.allowed is False

    def test_analyst_can_access_premium_data(self, engine):
        """Analyst can access CONFIDENTIAL fund data."""
        premium_data = {"analysis": "..."}
        tagged = engine.tag_data(
            premium_data,
            source="morningstar_premium_analysis",
            tenant_id="research_team",
        )
        ac = AccessControl.from_dict(tagged["access_control"])

        user = UserContext(
            user_id="analyst_001",
            tenant_id="research_team",
            roles=["analyst"],
            clearance_level="CONFIDENTIAL",
        )
        result = engine.evaluate(user, ac, action="read")

        assert result.allowed is True


class TestPermissionFiltersForFundData:
    """Test that permission filters work for fund data queries."""

    @pytest.fixture
    def engine(self):
        return PermissionEngine(PolicyStore(), NullAuditLogger())

    def test_sql_filter_for_fund_query(self, engine):
        """SQL filter can be applied to fund data queries."""
        user = UserContext(
            user_id="analyst_001",
            tenant_id="research_team",
            roles=["analyst", "premium_user"],
            clearance_level="CONFIDENTIAL",
        )

        sql_filter = engine.sql_filter(user)

        assert isinstance(sql_filter, SQLFilter)
        assert "classification" in sql_filter.clause
        assert "tenant_id" in sql_filter.clause
        assert "roles_allowed" in sql_filter.clause
        assert sql_filter.params["tenant_id"] == "research_team"
        assert "analyst" in sql_filter.params["roles"]

    def test_neo4j_filter_for_fund_graph(self, engine):
        """Neo4j filter can be applied to fund graph queries."""
        user = UserContext(
            user_id="u1",
            tenant_id="t1",
            roles=["analyst"],
            clearance_level="INTERNAL",
        )

        cypher_filter = engine.neo4j_filter(user)

        assert isinstance(cypher_filter, CypherFilter)
        assert "n.classification" in cypher_filter.clause
        assert "ANY(role IN $roles" in cypher_filter.clause
        assert cypher_filter.params["roles"] == ["analyst"]

    def test_milvus_filter_for_fund_search(self, engine):
        """Milvus filter can be applied to fund vector search."""
        user = UserContext(
            user_id="u1",
            tenant_id="t1",
            roles=["premium_user"],
            clearance_level="CONFIDENTIAL",
        )

        milvus_filter = engine.milvus_filter(user)

        assert isinstance(milvus_filter, MilvusFilter)
        assert "classification" in milvus_filter.expr
        assert "tenant_id" in milvus_filter.expr
        assert milvus_filter.post_filter is not None


class TestAccessControlSchemaForDatabases:
    """Test that AccessControl can be serialized for each database type."""

    def test_access_control_to_postgres_columns(self):
        """AccessControl can be converted to PostgreSQL column values."""
        ac = AccessControl(
            classification="INTERNAL",
            tenant_id="research_team",
            roles_allowed=["analyst"],
            users_allowed=["user_001"],
            source="yfinance",
            region="US",
            owner="data_manager",
        )

        d = ac.to_dict()

        assert d["classification"] == "INTERNAL"
        assert d["classification_level"] == 1
        assert d["tenant_id"] == "research_team"
        assert d["roles_allowed"] == ["analyst"]
        assert d["users_allowed"] == ["user_001"]
        assert d["source"] == "yfinance"
        assert d["region"] == "US"

    def test_access_control_to_neo4j_properties(self):
        """AccessControl can be converted to Neo4j node properties."""
        ac = AccessControl(
            classification="PUBLIC",
            source="etf_com",
        )

        d = ac.to_dict()

        assert "classification" in d
        assert "classification_level" in d
        assert "roles_allowed" in d
        assert isinstance(d["roles_allowed"], list)

    def test_access_control_to_milvus_metadata(self):
        """AccessControl can be converted to Milvus metadata fields."""
        ac = AccessControl(
            classification="CONFIDENTIAL",
            tenant_id="premium_team",
            roles_allowed=["premium_user"],
        )

        d = ac.to_dict()

        assert isinstance(d["classification"], str)
        assert isinstance(d["classification_level"], int)
        assert isinstance(d["tenant_id"], str)
        assert isinstance(d["roles_allowed"], list)


class TestFundDataWithAccessControl:
    """Test transforming fund data with access_control for distribution."""

    @pytest.fixture
    def engine(self):
        return PermissionEngine(PolicyStore(), NullAuditLogger())

    def test_fund_record_with_access_control_structure(self, engine):
        """Fund record with access_control has expected structure."""
        fund = {
            "symbol": "VOO",
            "name": "Vanguard S&P 500 ETF",
            "total_assets_billion": 500.0,
            "expense_ratio": 0.03,
        }

        tagged = engine.tag_data(fund, source="yfinance_fund_info")

        assert tagged["symbol"] == "VOO"
        assert tagged["name"] == "Vanguard S&P 500 ETF"
        assert "access_control" in tagged
        ac = tagged["access_control"]
        assert all(
            k in ac
            for k in [
                "classification",
                "classification_level",
                "tenant_id",
                "roles_allowed",
                "users_allowed",
                "source",
                "owner",
                "created_at",
            ]
        )

    def test_postgres_row_with_access_control_columns(self, engine):
        """PostgreSQL row includes access_control columns."""
        fund = {"symbol": "VOO", "name": "Vanguard S&P 500 ETF"}
        tagged = engine.tag_data(fund, source="yfinance")
        ac = tagged["access_control"]

        pg_row = {
            "symbol": tagged["symbol"],
            "name": tagged["name"],
            "classification": ac["classification"],
            "classification_level": ac["classification_level"],
            "tenant_id": ac["tenant_id"],
            "roles_allowed": json.dumps(ac["roles_allowed"]),
            "users_allowed": json.dumps(ac["users_allowed"]),
            "source": ac["source"],
            "region": ac["region"],
            "expiry_date": ac["expiry_date"],
            "owner": ac["owner"],
            "ac_created_at": ac["created_at"],
        }

        assert pg_row["classification"] == "PUBLIC"
        assert pg_row["classification_level"] == 0
        assert pg_row["roles_allowed"] == "[]"

    def test_neo4j_node_with_access_control_properties(self, engine):
        """Neo4j node includes access_control properties."""
        fund = {"symbol": "VOO", "name": "Vanguard S&P 500 ETF"}
        tagged = engine.tag_data(fund, source="yfinance")
        ac = tagged["access_control"]

        neo4j_node = {
            "label": "Fund",
            "symbol": tagged["symbol"],
            "name": tagged["name"],
            "classification": ac["classification"],
            "classification_level": ac["classification_level"],
            "tenant_id": ac["tenant_id"],
            "roles_allowed": ac["roles_allowed"],
            "users_allowed": ac["users_allowed"],
            "source": ac["source"],
        }

        assert neo4j_node["classification"] == "PUBLIC"
        assert neo4j_node["classification_level"] == 0
        assert neo4j_node["roles_allowed"] == []

    def test_milvus_doc_with_access_control_metadata(self, engine):
        """Milvus document includes access_control metadata."""
        fund = {"symbol": "VOO", "name": "Vanguard S&P 500 ETF"}
        tagged = engine.tag_data(fund, source="yfinance")
        ac = tagged["access_control"]

        milvus_doc = {
            "id": f"fund_{tagged['symbol']}",
            "content": f"Fund: {tagged['name']}",
            "classification": ac["classification"],
            "classification_level": ac["classification_level"],
            "tenant_id": ac["tenant_id"],
            "roles_allowed": json.dumps(ac["roles_allowed"]),
            "users_allowed": json.dumps(ac["users_allowed"]),
            "source": ac["source"],
        }

        assert milvus_doc["classification"] == "PUBLIC"
        assert milvus_doc["classification_level"] == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
