"""Permission engine: core authorization logic.

Provides PermissionEngine for evaluating access requests and generating
database-specific filters for PostgreSQL, Neo4j, and Milvus.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from permission.audit import AuditLogger, NullAuditLogger
from permission.filters import (
    CypherFilter,
    MilvusFilter,
    SQLFilter,
    escape_milvus_string,
    parse_json_array,
)
from permission.models import (
    AccessControl,
    CLEARANCE_HIERARCHY,
    PermissionResult,
    UserContext,
)
from permission.policy import PolicyStore

logger = logging.getLogger(__name__)

_engine_instance: PermissionEngine | None = None


def get_permission_engine() -> PermissionEngine:
    """Get or create the global PermissionEngine singleton.

    Returns:
        Shared PermissionEngine instance.
    """
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = PermissionEngine(PolicyStore(), NullAuditLogger())
    return _engine_instance


def set_permission_engine(engine: PermissionEngine) -> None:
    """Set the global PermissionEngine singleton.

    Args:
        engine: PermissionEngine instance to use globally.
    """
    global _engine_instance
    _engine_instance = engine


class PermissionEngine:
    """Central authorization engine for all data access.

    Evaluates user context against data access control to determine
    if access should be granted. Generates database-specific filters
    for authorized queries.
    """

    def __init__(
        self,
        policy_store: PolicyStore,
        audit_logger: AuditLogger,
    ) -> None:
        """Initialize the permission engine.

        Args:
            policy_store: Storage for permission policies.
            audit_logger: Logger for access audit trail.
        """
        self.policy_store = policy_store
        self.audit_logger = audit_logger

    def evaluate(
        self,
        user: UserContext,
        resource: AccessControl,
        action: str = "read",
    ) -> PermissionResult:
        """Evaluate if user can access resource.

        Multi-step evaluation:
        1. Check data expiry
        2. Check clearance level vs classification (using numeric hierarchy)
        3. Check tenant match (if not PUBLIC)
        4. Check RBAC OR ABAC (roles_allowed OR users_allowed)
        5. Log access attempt (both allowed and denied)

        Args:
            user: User context with identity and roles.
            resource: Access control metadata of the resource.
            action: Action being performed (read, write, delete).

        Returns:
            PermissionResult with allowed flag and reason.
        """

        def deny(reason: str) -> PermissionResult:
            self.audit_logger.log_access(
                user, resource, action, allowed=False, reason=reason
            )
            return PermissionResult(allowed=False, reason=reason)

        def allow(reason: str) -> PermissionResult:
            self.audit_logger.log_access(
                user, resource, action, allowed=True, reason=reason
            )
            return PermissionResult(allowed=True, reason=reason)

        # Step 1: Check expiry
        if resource.is_expired():
            return deny("Data expired")

        # Step 2: Classification vs clearance (PUBLIC data allows all)
        if resource.classification == "PUBLIC":
            return allow("Public data")

        user_level = user.get_clearance_numeric()
        data_level = CLEARANCE_HIERARCHY.get(resource.classification, 3)
        if user_level < data_level:
            return deny(
                f"Insufficient clearance: {user.clearance_level} < {resource.classification}"
            )

        # Step 3: Tenant check
        if resource.tenant_id and resource.tenant_id != user.tenant_id:
            return deny("Tenant mismatch")

        # Step 4: RBAC OR ABAC (either condition grants access)
        has_role_restriction = bool(resource.roles_allowed)
        has_user_restriction = bool(resource.users_allowed)

        if has_role_restriction or has_user_restriction:
            role_match = has_role_restriction and any(
                role in resource.roles_allowed for role in user.roles
            )
            user_match = has_user_restriction and user.user_id in resource.users_allowed

            if not (role_match or user_match):
                return deny("Neither role nor user authorized")

        return allow("Access granted")

    def sql_filter(self, user: UserContext) -> SQLFilter:
        """Generate parameterized PostgreSQL WHERE clause.

        Uses numeric clearance comparison and checks expiry_date.
        Returns clause with named parameters for safe execution.

        Example:
            filter = engine.sql_filter(user)
            cursor.execute(f"SELECT * FROM table WHERE {filter.clause}", filter.params)

        Args:
            user: User context for filter generation.

        Returns:
            SQLFilter with clause and params.
        """
        user_level = user.get_clearance_numeric()

        params: dict[str, Any] = {
            "tenant_id": user.tenant_id,
            "user_id": user.user_id,
            "roles": user.roles,
            "clearance_level": user_level,
        }

        clause = """
            (
                classification = 'PUBLIC'
            )
            OR (
                tenant_id = %(tenant_id)s
                AND classification_level <= %(clearance_level)s
                AND (expiry_date IS NULL OR expiry_date > NOW())
                AND (
                    roles_allowed IS NULL
                    OR cardinality(roles_allowed) = 0
                    OR roles_allowed ?| %(roles)s
                    OR users_allowed ? %(user_id)s
                )
            )
        """

        return SQLFilter(clause=clause.strip(), params=params)

    def neo4j_filter(self, user: UserContext) -> CypherFilter:
        """Generate parameterized Cypher WHERE clause for node filtering.

        Checks ALL user roles (not just the first one) using ANY().
        Returns clause with parameters for safe execution.

        Example:
            filter = engine.neo4j_filter(user)
            session.run(f"MATCH (n) WHERE {filter.clause} RETURN n", filter.params)

        Args:
            user: User context for filter generation.

        Returns:
            CypherFilter with clause and params.
        """
        user_level = user.get_clearance_numeric()

        params: dict[str, Any] = {
            "tenant_id": user.tenant_id,
            "user_id": user.user_id,
            "roles": user.roles,
            "clearance_level": user_level,
        }

        clause = """
            n.classification = 'PUBLIC'
            OR (
                n.tenant_id = $tenant_id
                AND n.classification_level <= $clearance_level
                AND (n.expiry_date IS NULL OR n.expiry_date > datetime())
                AND (
                    n.roles_allowed IS NULL
                    OR size(n.roles_allowed) = 0
                    OR ANY(role IN $roles WHERE role IN n.roles_allowed)
                    OR $user_id IN n.users_allowed
                )
            )
        """

        return CypherFilter(clause=clause.strip(), params=params)

    def milvus_filter(self, user: UserContext) -> MilvusFilter:
        """Generate Milvus boolean expression for metadata filtering.

        Milvus has limited expression capabilities (no array intersection).
        Strategy:
        1. Pre-filter: classification and tenant (efficient in Milvus)
        2. Post-filter: RBAC/ABAC check in Python after retrieval

        Example:
            filter = engine.milvus_filter(user)
            results = collection.search(..., expr=filter.expr)
            if filter.post_filter:
                results = filter.post_filter(results)

        Args:
            user: User context for filter generation.

        Returns:
            MilvusFilter with expr and post_filter function.
        """
        user_level = user.get_clearance_numeric()
        tenant_escaped = escape_milvus_string(user.tenant_id)

        expr = f'''classification == "PUBLIC" or (tenant_id == "{tenant_escaped}" and classification_level <= {user_level})'''

        def post_filter(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
            """Filter results by RBAC/ABAC rules."""
            filtered = []
            for item in results:
                if item.get("classification") == "PUBLIC":
                    filtered.append(item)
                    continue

                roles_allowed = parse_json_array(item.get("roles_allowed", []))
                users_allowed = parse_json_array(item.get("users_allowed", []))

                if not roles_allowed and not users_allowed:
                    filtered.append(item)
                    continue

                role_match = any(r in roles_allowed for r in user.roles)
                user_match = user.user_id in users_allowed
                if role_match or user_match:
                    filtered.append(item)

            return filtered

        return MilvusFilter(expr=expr, post_filter=post_filter)

    def tag_data(
        self,
        data: dict[str, Any],
        source: str,
        policy_name: str | None = None,
        owner: str = "system",
        tenant_id: str = "",
        region: str = "",
    ) -> dict[str, Any]:
        """Apply access control tags to data based on source and policy.

        Used during data ingestion (DataManagerAgent) to embed
        permission metadata.

        Args:
            data: Raw data to tag.
            source: Data source identifier.
            policy_name: Optional policy to apply; auto-selects if None.
            owner: Data owner identifier.
            tenant_id: Override tenant (uses policy default if empty).
            region: Geographic region.

        Returns:
            Data with access_control field added.
        """
        if policy_name:
            policy = self.policy_store.get_policy(policy_name)
        else:
            policy = self.policy_store.match_policy(source)

        if policy is None:
            access_control = AccessControl(
                classification="PUBLIC",
                source=source,
                owner=owner,
                tenant_id=tenant_id,
                region=region,
            )
        else:
            expiry_date = None
            if policy.expiry_days is not None:
                expiry_dt = datetime.now(timezone.utc) + timedelta(days=policy.expiry_days)
                expiry_date = expiry_dt.isoformat()

            access_control = AccessControl(
                classification=policy.default_classification,
                source=source,
                owner=owner,
                tenant_id=tenant_id or policy.default_tenant,
                roles_allowed=list(policy.default_roles),
                region=region,
                expiry_date=expiry_date,
            )

        result = data.copy()
        result["access_control"] = access_control.to_dict()
        return result

    def check_write_permission(
        self,
        user: UserContext,
        target_classification: str = "PUBLIC",
    ) -> PermissionResult:
        """Check if user can perform write operation.

        For inserts: user must have clearance >= target_classification.

        Args:
            user: User context.
            target_classification: Classification of data being written.

        Returns:
            PermissionResult indicating if write is allowed.
        """
        user_level = user.get_clearance_numeric()
        target_level = CLEARANCE_HIERARCHY.get(target_classification, 0)

        if user_level >= target_level:
            return PermissionResult(
                allowed=True,
                reason=f"User clearance {user.clearance_level} allows writing {target_classification} data",
            )
        return PermissionResult(
            allowed=False,
            reason=f"Insufficient clearance: {user.clearance_level} cannot write {target_classification} data",
        )
