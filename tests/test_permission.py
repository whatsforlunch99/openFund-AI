"""Tests for permission management module.

Covers AccessControl, UserContext, PermissionEngine, PolicyStore,
AuditLogger, filters, and masking.
"""

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import pytest

from permission.models import (
    AccessControl,
    UserContext,
    PermissionResult,
    CLEARANCE_HIERARCHY,
)
from permission.policy import (
    PermissionPolicy,
    PolicyStore,
    DEFAULT_POLICIES,
)
from permission.audit import AuditLogger, AuditRecord, NullAuditLogger
from permission.filters import (
    SQLFilter,
    CypherFilter,
    MilvusFilter,
    escape_milvus_string,
    parse_json_array,
)
from permission.engine import PermissionEngine
from permission.masking import (
    MaskingRule,
    mask_value,
    apply_masking,
    DEFAULT_MASKING_RULES,
)


class TestAccessControl:
    """Tests for AccessControl dataclass."""

    def test_default_values(self):
        """AccessControl has sensible defaults."""
        ac = AccessControl()
        assert ac.classification == "PUBLIC"
        assert ac.classification_level == 0
        assert ac.tenant_id == ""
        assert ac.roles_allowed == []
        assert ac.users_allowed == []
        assert ac.created_at != ""

    def test_classification_level_sync(self):
        """classification_level is synced from classification."""
        ac = AccessControl(classification="CONFIDENTIAL")
        assert ac.classification_level == 2

        ac2 = AccessControl(classification="RESTRICTED", classification_level=0)
        assert ac2.classification_level == 3

    def test_is_expired(self):
        """is_expired correctly detects expiration."""
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()

        ac_expired = AccessControl(expiry_date=past)
        assert ac_expired.is_expired() is True

        ac_valid = AccessControl(expiry_date=future)
        assert ac_valid.is_expired() is False

        ac_no_expiry = AccessControl()
        assert ac_no_expiry.is_expired() is False

    def test_to_dict_from_dict(self):
        """Round-trip serialization works."""
        ac = AccessControl(
            classification="INTERNAL",
            tenant_id="test_tenant",
            roles_allowed=["analyst"],
            users_allowed=["user1"],
            source="test",
        )
        d = ac.to_dict()
        ac2 = AccessControl.from_dict(d)

        assert ac2.classification == ac.classification
        assert ac2.classification_level == ac.classification_level
        assert ac2.tenant_id == ac.tenant_id
        assert ac2.roles_allowed == ac.roles_allowed


class TestUserContext:
    """Tests for UserContext dataclass."""

    def test_default_values(self):
        """UserContext has sensible defaults."""
        user = UserContext(user_id="u1", tenant_id="t1")
        assert user.roles == []
        assert user.attributes == {}
        assert user.clearance_level == "PUBLIC"

    def test_get_clearance_numeric(self):
        """get_clearance_numeric returns correct value."""
        user = UserContext(user_id="u1", tenant_id="t1", clearance_level="CONFIDENTIAL")
        assert user.get_clearance_numeric() == 2

    def test_anonymous(self):
        """anonymous() creates minimal permission context."""
        user = UserContext.anonymous()
        assert user.user_id == "anonymous"
        assert user.tenant_id == "default"
        assert user.clearance_level == "PUBLIC"
        assert "public_user" in user.roles

    def test_to_dict_from_dict(self):
        """Round-trip serialization works."""
        user = UserContext(
            user_id="u1",
            tenant_id="t1",
            roles=["analyst", "admin"],
            clearance_level="RESTRICTED",
        )
        d = user.to_dict()
        user2 = UserContext.from_dict(d)

        assert user2.user_id == user.user_id
        assert user2.roles == user.roles
        assert user2.clearance_level == user.clearance_level


class TestPermissionPolicy:
    """Tests for PermissionPolicy."""

    def test_matches_source(self):
        """matches() correctly evaluates regex patterns."""
        policy = PermissionPolicy(
            name="test",
            source_pattern=r"^yfinance.*",
            default_classification="PUBLIC",
        )
        assert policy.matches("yfinance_stock_data") is True
        assert policy.matches("bloomberg_data") is False

    def test_to_dict_from_dict(self):
        """Round-trip serialization works."""
        policy = PermissionPolicy(
            name="test_policy",
            source_pattern=r"^test_.*",
            default_classification="INTERNAL",
            default_roles=["analyst"],
            expiry_days=30,
        )
        d = policy.to_dict()
        policy2 = PermissionPolicy.from_dict(d)

        assert policy2.name == policy.name
        assert policy2.default_classification == policy.default_classification
        assert policy2.default_roles == policy.default_roles


class TestPolicyStore:
    """Tests for PolicyStore."""

    def test_load_defaults(self):
        """PolicyStore loads default policies."""
        store = PolicyStore()
        policies = store.list_policies()
        assert len(policies) >= len(DEFAULT_POLICIES)

    def test_match_policy(self):
        """match_policy finds correct policy."""
        store = PolicyStore()
        
        policy = store.match_policy("yfinance_stock_data")
        assert policy is not None
        assert policy.name == "public_market_data"

        policy2 = store.match_policy("internal_research_note")
        assert policy2 is not None
        assert policy2.name == "internal_research"

    def test_add_remove_policy(self):
        """add_policy and remove_policy work."""
        store = PolicyStore(load_defaults=False)
        
        policy = PermissionPolicy(name="custom", source_pattern=".*")
        store.add_policy(policy)
        
        assert store.get_policy("custom") is not None
        
        store.remove_policy("custom")
        assert store.get_policy("custom") is None

    def test_load_from_file(self):
        """load_from_file loads policies from JSON."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            policies = [
                {
                    "name": "file_policy",
                    "source_pattern": "^file_.*",
                    "default_classification": "CONFIDENTIAL",
                }
            ]
            json.dump(policies, f)
            f.flush()
            
            store = PolicyStore(load_defaults=False)
            count = store.load_from_file(f.name)
            
            assert count == 1
            assert store.get_policy("file_policy") is not None
            
        os.unlink(f.name)


class TestAuditLogger:
    """Tests for AuditLogger."""

    def test_disabled_logger_no_op(self):
        """Disabled logger does nothing."""
        logger = AuditLogger(enabled=False)
        user = UserContext(user_id="u1", tenant_id="t1")
        resource = AccessControl()
        
        logger.log_access(user, resource, "read", True)
        assert len(logger._buffer) == 0

    def test_enabled_logger_buffers(self):
        """Enabled logger buffers records."""
        logger = AuditLogger(enabled=True, buffer_size=10)
        user = UserContext(user_id="u1", tenant_id="t1")
        resource = AccessControl(classification="PUBLIC")
        
        logger.log_access(user, resource, "read", True, reason="test")
        assert len(logger._buffer) == 1
        assert logger._buffer[0].user_id == "u1"
        assert logger._buffer[0].allowed is True

    def test_flush_writes_to_file(self):
        """flush() writes records to file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "test.log")
            logger = AuditLogger(enabled=True, file_path=log_path)
            user = UserContext(user_id="u1", tenant_id="t1")
            resource = AccessControl()
            
            logger.log_access(user, resource, "read", True)
            logger.flush()
            
            assert os.path.exists(log_path)
            with open(log_path) as f:
                lines = f.readlines()
                assert len(lines) == 1
                record = json.loads(lines[0])
                assert record["user_id"] == "u1"

    def test_null_logger(self):
        """NullAuditLogger is always no-op."""
        logger = NullAuditLogger()
        user = UserContext(user_id="u1", tenant_id="t1")
        resource = AccessControl()
        
        logger.log_access(user, resource, "read", True)
        assert logger.flush() == 0


class TestFilters:
    """Tests for filter utilities."""

    def test_escape_milvus_string(self):
        """escape_milvus_string escapes special characters."""
        assert escape_milvus_string('test"value') == 'test\\"value'
        assert escape_milvus_string("test\\path") == "test\\\\path"
        assert escape_milvus_string("") == ""

    def test_parse_json_array(self):
        """parse_json_array handles various inputs."""
        assert parse_json_array('["a", "b"]') == ["a", "b"]
        assert parse_json_array([]) == []
        assert parse_json_array(["a", "b"]) == ["a", "b"]
        assert parse_json_array("[]") == []
        assert parse_json_array("null") == []
        assert parse_json_array("invalid") == []

    def test_sql_filter_with_alias(self):
        """SQLFilter.with_alias adds table prefix."""
        sql_filter = SQLFilter(
            clause="classification = 'PUBLIC' AND tenant_id = %(tenant_id)s",
            params={"tenant_id": "t1"},
        )
        aliased = sql_filter.with_alias("t")
        assert "t.classification" in aliased.clause
        assert "t.tenant_id" in aliased.clause

    def test_cypher_filter_with_node_var(self):
        """CypherFilter.with_node_var changes node variable."""
        cypher_filter = CypherFilter(
            clause="n.classification = 'PUBLIC'",
            params={},
        )
        renamed = cypher_filter.with_node_var("node")
        assert "node.classification" in renamed.clause
        assert "n.classification" not in renamed.clause


class TestPermissionEngine:
    """Tests for PermissionEngine."""

    @pytest.fixture
    def engine(self):
        """Create test engine with null audit logger."""
        return PermissionEngine(PolicyStore(), NullAuditLogger())

    def test_evaluate_public_data(self, engine):
        """PUBLIC data accessible to anyone."""
        user = UserContext(user_id="u1", tenant_id="t1", roles=[], clearance_level="PUBLIC")
        resource = AccessControl(classification="PUBLIC")
        
        result = engine.evaluate(user, resource)
        assert result.allowed is True
        assert result.reason == "Public data"

    def test_evaluate_classification_denied(self, engine):
        """User with PUBLIC clearance cannot access CONFIDENTIAL."""
        user = UserContext(user_id="u1", tenant_id="t1", clearance_level="PUBLIC")
        resource = AccessControl(classification="CONFIDENTIAL", tenant_id="t1")
        
        result = engine.evaluate(user, resource)
        assert result.allowed is False
        assert "clearance" in result.reason.lower()

    def test_evaluate_expired_data_denied(self, engine):
        """Expired data is not accessible even with sufficient clearance."""
        user = UserContext(user_id="u1", tenant_id="t1", clearance_level="RESTRICTED")
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        resource = AccessControl(
            classification="PUBLIC",
            expiry_date=past,
        )
        
        result = engine.evaluate(user, resource)
        assert result.allowed is False
        assert "expired" in result.reason.lower()

    def test_evaluate_tenant_mismatch(self, engine):
        """Tenant mismatch denies access."""
        user = UserContext(user_id="u1", tenant_id="t1", clearance_level="RESTRICTED")
        resource = AccessControl(
            classification="INTERNAL",
            tenant_id="t2",
        )
        
        result = engine.evaluate(user, resource)
        assert result.allowed is False
        assert "tenant" in result.reason.lower()

    def test_evaluate_rbac_match(self, engine):
        """User passes if role matches."""
        user = UserContext(
            user_id="u1",
            tenant_id="t1",
            roles=["analyst"],
            clearance_level="INTERNAL",
        )
        resource = AccessControl(
            classification="INTERNAL",
            tenant_id="t1",
            roles_allowed=["analyst", "admin"],
        )
        
        result = engine.evaluate(user, resource)
        assert result.allowed is True

    def test_evaluate_abac_match(self, engine):
        """User passes if in users_allowed."""
        user = UserContext(
            user_id="special_user",
            tenant_id="t1",
            roles=["viewer"],
            clearance_level="INTERNAL",
        )
        resource = AccessControl(
            classification="INTERNAL",
            tenant_id="t1",
            roles_allowed=["admin"],
            users_allowed=["special_user"],
        )
        
        result = engine.evaluate(user, resource)
        assert result.allowed is True

    def test_evaluate_rbac_or_abac(self, engine):
        """User passes if EITHER role OR user matches."""
        user = UserContext(
            user_id="u1",
            tenant_id="t1",
            roles=["viewer"],
            clearance_level="INTERNAL",
        )
        resource = AccessControl(
            classification="INTERNAL",
            tenant_id="t1",
            roles_allowed=["admin"],
            users_allowed=["u1"],
        )
        
        result = engine.evaluate(user, resource)
        assert result.allowed is True

    def test_evaluate_neither_role_nor_user(self, engine):
        """User denied if neither role nor user matches."""
        user = UserContext(
            user_id="u1",
            tenant_id="t1",
            roles=["viewer"],
            clearance_level="INTERNAL",
        )
        resource = AccessControl(
            classification="INTERNAL",
            tenant_id="t1",
            roles_allowed=["admin"],
            users_allowed=["u2"],
        )
        
        result = engine.evaluate(user, resource)
        assert result.allowed is False

    def test_sql_filter_returns_parameterized(self, engine):
        """SQL filter returns clause + params, not interpolated string."""
        user = UserContext(
            user_id="u1",
            tenant_id="t1",
            roles=["analyst"],
            clearance_level="INTERNAL",
        )
        
        filter_result = engine.sql_filter(user)
        
        assert isinstance(filter_result, SQLFilter)
        assert "%(tenant_id)s" in filter_result.clause
        assert filter_result.params["tenant_id"] == "t1"
        assert filter_result.params["roles"] == ["analyst"]
        assert "expiry_date" in filter_result.clause

    def test_neo4j_filter_checks_all_roles(self, engine):
        """Neo4j filter checks ALL user roles."""
        user = UserContext(
            user_id="u1",
            tenant_id="t1",
            roles=["viewer", "analyst", "admin"],
            clearance_level="INTERNAL",
        )
        
        filter_result = engine.neo4j_filter(user)
        
        assert isinstance(filter_result, CypherFilter)
        assert "ANY(role IN $roles" in filter_result.clause
        assert filter_result.params["roles"] == ["viewer", "analyst", "admin"]

    def test_milvus_filter_has_post_filter(self, engine):
        """Milvus filter includes post_filter function."""
        user = UserContext(
            user_id="u1",
            tenant_id="t1",
            roles=["analyst"],
            clearance_level="INTERNAL",
        )
        
        filter_result = engine.milvus_filter(user)
        
        assert isinstance(filter_result, MilvusFilter)
        assert filter_result.post_filter is not None
        assert callable(filter_result.post_filter)

    def test_milvus_post_filter(self, engine):
        """Milvus post_filter correctly filters results."""
        user = UserContext(
            user_id="u1",
            tenant_id="t1",
            roles=["analyst"],
            clearance_level="INTERNAL",
        )
        filter_result = engine.milvus_filter(user)
        
        results = [
            {"classification": "PUBLIC", "roles_allowed": "[]", "users_allowed": "[]"},
            {"classification": "INTERNAL", "roles_allowed": '["admin"]', "users_allowed": "[]"},
            {"classification": "INTERNAL", "roles_allowed": '["analyst"]', "users_allowed": "[]"},
            {"classification": "INTERNAL", "roles_allowed": "[]", "users_allowed": '["u1"]'},
        ]
        
        filtered = filter_result.post_filter(results)
        assert len(filtered) == 3

    def test_tag_data_with_policy(self, engine):
        """tag_data applies policy correctly."""
        data = {"symbol": "NVDA", "price": 100.0}
        tagged = engine.tag_data(data, source="yfinance_stock", owner="system")
        
        assert "access_control" in tagged
        ac = tagged["access_control"]
        assert ac["classification"] == "PUBLIC"
        assert ac["source"] == "yfinance_stock"

    def test_tag_data_with_expiry(self, engine):
        """tag_data sets expiry from policy."""
        data = {"note": "test"}
        tagged = engine.tag_data(data, source="internal_note", owner="analyst1")
        
        ac = tagged["access_control"]
        assert ac["classification"] == "INTERNAL"
        assert ac["expiry_date"] is not None

    def test_check_write_permission(self, engine):
        """check_write_permission evaluates clearance."""
        user_low = UserContext(user_id="u1", tenant_id="t1", clearance_level="PUBLIC")
        user_high = UserContext(user_id="u2", tenant_id="t1", clearance_level="RESTRICTED")
        
        result_low = engine.check_write_permission(user_low, "CONFIDENTIAL")
        assert result_low.allowed is False
        
        result_high = engine.check_write_permission(user_high, "CONFIDENTIAL")
        assert result_high.allowed is True


class TestAuditLogging:
    """Tests for audit logging integration."""

    def test_evaluate_logs_allowed(self):
        """evaluate logs allowed access."""
        mock_logger = Mock(spec=AuditLogger)
        mock_logger.enabled = True
        engine = PermissionEngine(PolicyStore(), mock_logger)
        
        user = UserContext(user_id="u1", tenant_id="t1")
        resource = AccessControl(classification="PUBLIC")
        
        engine.evaluate(user, resource)
        
        mock_logger.log_access.assert_called_once()
        call_args = mock_logger.log_access.call_args
        assert call_args.kwargs["allowed"] is True

    def test_evaluate_logs_denied(self):
        """evaluate logs denied access."""
        mock_logger = Mock(spec=AuditLogger)
        mock_logger.enabled = True
        engine = PermissionEngine(PolicyStore(), mock_logger)
        
        user = UserContext(user_id="u1", tenant_id="t1", clearance_level="PUBLIC")
        resource = AccessControl(classification="RESTRICTED", tenant_id="t1")
        
        engine.evaluate(user, resource)
        
        mock_logger.log_access.assert_called_once()
        call_args = mock_logger.log_access.call_args
        assert call_args.kwargs["allowed"] is False


class TestMasking:
    """Tests for data masking."""

    def test_mask_value_full(self):
        """Full masking replaces entire value."""
        rule = MaskingRule(
            field_pattern=".*",
            min_classification="PUBLIC",
            mask_type="full",
        )
        assert mask_value("secret123", rule) == "*********"
        assert mask_value("", rule) == ""

    def test_mask_value_partial(self):
        """Partial masking shows last 4 characters."""
        rule = MaskingRule(
            field_pattern=".*",
            min_classification="PUBLIC",
            mask_type="partial",
        )
        assert mask_value("1234567890", rule) == "******7890"

    def test_mask_value_round(self):
        """Round masking rounds numeric values."""
        rule = MaskingRule(
            field_pattern=".*",
            min_classification="PUBLIC",
            mask_type="round",
        )
        assert mask_value(1_234_567_890, rule) == 1_000_000_000
        assert mask_value(12_345_678, rule) == 12_000_000
        assert mask_value(1_234, rule) == 1_000
        assert mask_value(123, rule) == 120

    def test_apply_masking(self):
        """apply_masking applies rules to matching fields."""
        data = {
            "aum": 5_000_000_000,
            "account_number": "1234567890",
            "name": "Test Fund",
        }
        
        result = apply_masking(data, "RESTRICTED")
        
        assert result["aum"] == 5_000_000_000
        assert result["account_number"] == "******7890"
        assert result["name"] == "Test Fund"

    def test_apply_masking_nested(self):
        """apply_masking handles nested dicts."""
        data = {
            "fund": {
                "aum": 1_000_000_000,
                "client_id": "ABC12345",
            }
        }
        
        result = apply_masking(data, "RESTRICTED")
        
        assert result["fund"]["client_id"] == "****2345"

    def test_masking_rule_matches_field(self):
        """MaskingRule.matches_field uses regex."""
        rule = MaskingRule(
            field_pattern=r"^(aum|total_assets)$",
            min_classification="CONFIDENTIAL",
            mask_type="round",
        )
        
        assert rule.matches_field("aum") is True
        assert rule.matches_field("total_assets") is True
        assert rule.matches_field("AUM") is True
        assert rule.matches_field("name") is False

    def test_masking_rule_should_mask(self):
        """MaskingRule.should_mask checks classification level."""
        rule = MaskingRule(
            field_pattern=".*",
            min_classification="CONFIDENTIAL",
            mask_type="full",
        )
        
        assert rule.should_mask("RESTRICTED") is True
        assert rule.should_mask("CONFIDENTIAL") is True
        assert rule.should_mask("INTERNAL") is False
        assert rule.should_mask("PUBLIC") is False
