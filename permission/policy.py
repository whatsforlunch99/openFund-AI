"""Permission policy management.

Defines PermissionPolicy and PolicyStore for matching data sources
to default access control settings.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class PermissionPolicy:
    """Named policy that defines default access control for a data source.

    Policies are matched by source name/pattern and applied during
    data ingestion to generate access_control metadata.

    Attributes:
        name: Policy identifier.
        source_pattern: Regex pattern to match data source.
        default_classification: Default classification level.
        default_tenant: Default tenant (or empty for source-based).
        default_roles: Default roles allowed.
        allow_owner_override: Can data owner override defaults.
        expiry_days: Auto-expiry in days (None = no expiry).
        region_restrictions: Allowed regions (empty = all).
    """

    name: str
    source_pattern: str
    default_classification: str = "PUBLIC"
    default_tenant: str = ""
    default_roles: list[str] = field(default_factory=list)
    allow_owner_override: bool = False
    expiry_days: int | None = None
    region_restrictions: list[str] = field(default_factory=list)

    def matches(self, source: str) -> bool:
        """Check if this policy matches the given source."""
        try:
            return bool(re.match(self.source_pattern, source))
        except re.error:
            logger.warning("Invalid regex pattern in policy %s: %s", self.name, self.source_pattern)
            return False

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "name": self.name,
            "source_pattern": self.source_pattern,
            "default_classification": self.default_classification,
            "default_tenant": self.default_tenant,
            "default_roles": self.default_roles,
            "allow_owner_override": self.allow_owner_override,
            "expiry_days": self.expiry_days,
            "region_restrictions": self.region_restrictions,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PermissionPolicy:
        """Create PermissionPolicy from dictionary."""
        return cls(
            name=data.get("name", ""),
            source_pattern=data.get("source_pattern", ".*"),
            default_classification=data.get("default_classification", "PUBLIC"),
            default_tenant=data.get("default_tenant", ""),
            default_roles=data.get("default_roles", []),
            allow_owner_override=data.get("allow_owner_override", False),
            expiry_days=data.get("expiry_days"),
            region_restrictions=data.get("region_restrictions", []),
        )


DEFAULT_POLICIES: list[PermissionPolicy] = [
    PermissionPolicy(
        name="public_market_data",
        source_pattern=r"^(yfinance|alpha_vantage|public_api|market_tool).*",
        default_classification="PUBLIC",
        default_tenant="",
        default_roles=[],
        allow_owner_override=False,
        expiry_days=None,
        region_restrictions=[],
    ),
    PermissionPolicy(
        name="internal_research",
        source_pattern=r"^internal_.*",
        default_classification="INTERNAL",
        default_tenant="",
        default_roles=["analyst", "researcher"],
        allow_owner_override=True,
        expiry_days=365,
        region_restrictions=[],
    ),
    PermissionPolicy(
        name="premium_data",
        source_pattern=r"^(morningstar|bloomberg|refinitiv).*",
        default_classification="CONFIDENTIAL",
        default_tenant="",
        default_roles=["premium_user", "analyst"],
        allow_owner_override=False,
        expiry_days=None,
        region_restrictions=[],
    ),
    PermissionPolicy(
        name="client_data",
        source_pattern=r"^client_.*",
        default_classification="RESTRICTED",
        default_tenant="",
        default_roles=["client_manager"],
        allow_owner_override=False,
        expiry_days=90,
        region_restrictions=[],
    ),
    PermissionPolicy(
        name="default_fallback",
        source_pattern=r".*",
        default_classification="PUBLIC",
        default_tenant="",
        default_roles=[],
        allow_owner_override=True,
        expiry_days=None,
        region_restrictions=[],
    ),
]


class PolicyStore:
    """Storage and lookup for permission policies.

    Policies can be loaded from:
    - Built-in defaults (DEFAULT_POLICIES)
    - JSON configuration file (PERMISSION_POLICY_FILE env var)
    - Programmatic addition via add_policy()
    """

    def __init__(self, load_defaults: bool = True) -> None:
        """Initialize the policy store.

        Args:
            load_defaults: Whether to load DEFAULT_POLICIES on init.
        """
        self._policies: dict[str, PermissionPolicy] = {}
        if load_defaults:
            self._load_defaults()

    def _load_defaults(self) -> None:
        """Load default policies."""
        for policy in DEFAULT_POLICIES:
            self._policies[policy.name] = policy

    def load_from_file(self, path: str) -> int:
        """Load policies from JSON file.

        Args:
            path: Path to JSON file containing policy definitions.

        Returns:
            Number of policies loaded.

        Raises:
            FileNotFoundError: If file does not exist.
            json.JSONDecodeError: If file is not valid JSON.
        """
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, list):
            data = [data]

        count = 0
        for item in data:
            try:
                policy = PermissionPolicy.from_dict(item)
                self._policies[policy.name] = policy
                count += 1
            except Exception as e:
                logger.warning("Failed to load policy from %s: %s", item, e)

        return count

    def get_policy(self, name: str) -> PermissionPolicy | None:
        """Get policy by name.

        Args:
            name: Policy identifier.

        Returns:
            PermissionPolicy if found, else None.
        """
        return self._policies.get(name)

    def match_policy(self, source: str) -> PermissionPolicy | None:
        """Find first policy matching the source pattern.

        Policies are checked in order (excluding default_fallback first),
        then default_fallback is returned if no other match.

        Args:
            source: Data source identifier to match.

        Returns:
            Matching PermissionPolicy, or None if no match.
        """
        fallback = None
        for policy in self._policies.values():
            if policy.name == "default_fallback":
                fallback = policy
                continue
            if policy.matches(source):
                return policy
        return fallback

    def add_policy(self, policy: PermissionPolicy) -> None:
        """Register a new policy.

        Args:
            policy: PermissionPolicy to add.
        """
        self._policies[policy.name] = policy

    def remove_policy(self, name: str) -> bool:
        """Remove a policy by name.

        Args:
            name: Policy identifier to remove.

        Returns:
            True if removed, False if not found.
        """
        if name in self._policies:
            del self._policies[name]
            return True
        return False

    def list_policies(self) -> list[PermissionPolicy]:
        """List all registered policies.

        Returns:
            List of all policies.
        """
        return list(self._policies.values())

    def export_to_file(self, path: str) -> None:
        """Export policies to JSON file.

        Args:
            path: Path to write JSON file.
        """
        data = [p.to_dict() for p in self._policies.values()]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
