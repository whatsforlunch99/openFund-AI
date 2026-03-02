"""Permission management module for unified access control.

Provides RBAC + ABAC + data classification for all storage backends
(PostgreSQL, Neo4j, Milvus) and the agent layer.

Key components:
- AccessControl: Data-level permission metadata
- UserContext: User identity and attributes for authorization
- PermissionEngine: Core authorization logic and filter generation
- PolicyStore: Permission policy management
- AuditLogger: Access audit trail
"""

from permission.models import (
    AccessControl,
    PermissionResult,
    UserContext,
    CLEARANCE_HIERARCHY,
)
from permission.policy import PermissionPolicy, PolicyStore, DEFAULT_POLICIES
from permission.audit import AuditLogger, AuditRecord
from permission.filters import SQLFilter, CypherFilter, MilvusFilter
from permission.engine import PermissionEngine, get_permission_engine

__all__ = [
    "AccessControl",
    "UserContext",
    "PermissionResult",
    "CLEARANCE_HIERARCHY",
    "PermissionPolicy",
    "PolicyStore",
    "DEFAULT_POLICIES",
    "AuditLogger",
    "AuditRecord",
    "SQLFilter",
    "CypherFilter",
    "MilvusFilter",
    "PermissionEngine",
    "get_permission_engine",
]
