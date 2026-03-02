"""Data models for permission management.

Defines AccessControl (data-level metadata), UserContext (user identity),
and PermissionResult (evaluation outcome).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


CLEARANCE_HIERARCHY: dict[str, int] = {
    "PUBLIC": 0,
    "INTERNAL": 1,
    "CONFIDENTIAL": 2,
    "RESTRICTED": 3,
}


@dataclass
class AccessControl:
    """Access control metadata embedded in data records.

    Attributes:
        classification: Classification level (PUBLIC, INTERNAL, CONFIDENTIAL, RESTRICTED).
        classification_level: Numeric level (0-3) for efficient database comparisons.
        tenant_id: Organization/team identifier.
        roles_allowed: Roles that can access (RBAC).
        users_allowed: Specific users that can access (ABAC).
        source: Data source identifier.
        region: Geographic region for compliance.
        expiry_date: Optional expiration (ISO format, timezone-aware).
        owner: Data owner identifier.
        created_at: Creation timestamp (ISO format).
    """

    classification: str = "PUBLIC"
    classification_level: int = 0
    tenant_id: str = ""
    roles_allowed: list[str] = field(default_factory=list)
    users_allowed: list[str] = field(default_factory=list)
    source: str = ""
    region: str = ""
    expiry_date: str | None = None
    owner: str = ""
    created_at: str = ""

    def __post_init__(self) -> None:
        """Ensure classification_level matches classification; set created_at if empty."""
        expected_level = CLEARANCE_HIERARCHY.get(self.classification, 0)
        if self.classification_level != expected_level:
            self.classification_level = expected_level
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def is_expired(self) -> bool:
        """Check if this access control has expired."""
        if not self.expiry_date:
            return False
        try:
            expiry = datetime.fromisoformat(self.expiry_date)
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            return expiry < datetime.now(timezone.utc)
        except ValueError:
            return False

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "classification": self.classification,
            "classification_level": self.classification_level,
            "tenant_id": self.tenant_id,
            "roles_allowed": self.roles_allowed,
            "users_allowed": self.users_allowed,
            "source": self.source,
            "region": self.region,
            "expiry_date": self.expiry_date,
            "owner": self.owner,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AccessControl:
        """Create AccessControl from dictionary."""
        return cls(
            classification=data.get("classification", "PUBLIC"),
            classification_level=data.get("classification_level", 0),
            tenant_id=data.get("tenant_id", ""),
            roles_allowed=data.get("roles_allowed", []),
            users_allowed=data.get("users_allowed", []),
            source=data.get("source", ""),
            region=data.get("region", ""),
            expiry_date=data.get("expiry_date"),
            owner=data.get("owner", ""),
            created_at=data.get("created_at", ""),
        )


@dataclass
class UserContext:
    """User identity and attributes for authorization.

    Attributes:
        user_id: Unique user identifier.
        tenant_id: Organization the user belongs to.
        roles: User's roles (e.g., ["analyst", "admin"]).
        attributes: Additional attributes for ABAC.
        clearance_level: Maximum classification user can access.
    """

    user_id: str
    tenant_id: str
    roles: list[str] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)
    clearance_level: str = "PUBLIC"

    def get_clearance_numeric(self) -> int:
        """Get numeric clearance level for comparison."""
        return CLEARANCE_HIERARCHY.get(self.clearance_level, 0)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for message passing."""
        return {
            "user_id": self.user_id,
            "tenant_id": self.tenant_id,
            "roles": self.roles,
            "attributes": self.attributes,
            "clearance_level": self.clearance_level,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UserContext:
        """Create UserContext from dictionary."""
        return cls(
            user_id=data.get("user_id", "anonymous"),
            tenant_id=data.get("tenant_id", "default"),
            roles=data.get("roles", []),
            attributes=data.get("attributes", {}),
            clearance_level=data.get("clearance_level", "PUBLIC"),
        )

    @classmethod
    def anonymous(cls) -> UserContext:
        """Create anonymous user context with minimal permissions."""
        return cls(
            user_id="anonymous",
            tenant_id="default",
            roles=["public_user"],
            attributes={},
            clearance_level="PUBLIC",
        )


@dataclass
class PermissionResult:
    """Result of permission evaluation.

    Attributes:
        allowed: Whether access is granted.
        reason: Explanation for the decision.
    """

    allowed: bool
    reason: str

    def __bool__(self) -> bool:
        """Allow using result directly in if statements."""
        return self.allowed
