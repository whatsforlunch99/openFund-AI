"""Audit logging for permission access attempts.

Provides AuditRecord for structured logging and AuditLogger for
async-safe file-based audit trail.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from permission.models import AccessControl, UserContext

logger = logging.getLogger(__name__)


@dataclass
class AuditRecord:
    """Single access audit log entry.

    Attributes:
        timestamp: ISO format timestamp.
        user_id: User who attempted access.
        tenant_id: User's tenant.
        action: Action performed (read, write, delete).
        resource_type: Table name, node label, or collection.
        resource_id: Primary key or identifier.
        classification: Data classification accessed.
        allowed: Whether access was granted.
        reason: Explanation for the decision.
        source_ip: Client IP if available.
        conversation_id: Associated conversation ID.
    """

    timestamp: str
    user_id: str
    tenant_id: str
    action: str
    resource_type: str
    resource_id: str
    classification: str
    allowed: bool
    reason: str
    source_ip: str | None = None
    conversation_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict())


class AuditLogger:
    """Async-safe access audit logger.

    Writes to file and optionally to database for compliance reporting.
    Buffers records and flushes when buffer reaches threshold.
    """

    def __init__(
        self,
        enabled: bool = False,
        file_path: str = "logs/access.log",
        buffer_size: int = 100,
    ) -> None:
        """Initialize the audit logger.

        Args:
            enabled: Whether audit logging is enabled.
            file_path: Path to audit log file.
            buffer_size: Number of records to buffer before flushing.
        """
        self.enabled = enabled
        self.file_path = file_path
        self.buffer_size = buffer_size
        self._buffer: list[AuditRecord] = []
        self._lock = threading.Lock()

    @classmethod
    def from_config(cls, config: Any) -> AuditLogger:
        """Create AuditLogger from config object.

        Args:
            config: Config object with permission_audit_enabled and permission_audit_file.

        Returns:
            Configured AuditLogger instance.
        """
        return cls(
            enabled=getattr(config, "permission_audit_enabled", False),
            file_path=getattr(config, "permission_audit_file", "logs/access.log"),
        )

    def log_access(
        self,
        user: UserContext,
        resource: AccessControl,
        action: str,
        allowed: bool,
        reason: str = "",
        resource_type: str = "",
        resource_id: str = "",
        conversation_id: str | None = None,
        source_ip: str | None = None,
    ) -> None:
        """Log an access attempt.

        Args:
            user: User context for the access attempt.
            resource: Access control metadata of the resource.
            action: Action being performed (read, write, delete).
            allowed: Whether access was granted.
            reason: Explanation for the decision.
            resource_type: Table name, node label, or collection.
            resource_id: Primary key or identifier.
            conversation_id: Associated conversation ID.
            source_ip: Client IP address.
        """
        if not self.enabled:
            return

        record = AuditRecord(
            timestamp=datetime.now(timezone.utc).isoformat(),
            user_id=user.user_id,
            tenant_id=user.tenant_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            classification=resource.classification,
            allowed=allowed,
            reason=reason,
            source_ip=source_ip,
            conversation_id=conversation_id,
        )

        with self._lock:
            self._buffer.append(record)
            if len(self._buffer) >= self.buffer_size:
                self._flush_unsafe()

    def log_raw(
        self,
        user_id: str,
        tenant_id: str,
        action: str,
        resource_type: str,
        resource_id: str,
        classification: str,
        allowed: bool,
        reason: str = "",
        conversation_id: str | None = None,
        source_ip: str | None = None,
    ) -> None:
        """Log an access attempt with raw values (no UserContext/AccessControl).

        Args:
            user_id: User identifier.
            tenant_id: User's tenant.
            action: Action being performed.
            resource_type: Table name, node label, or collection.
            resource_id: Primary key or identifier.
            classification: Data classification.
            allowed: Whether access was granted.
            reason: Explanation for the decision.
            conversation_id: Associated conversation ID.
            source_ip: Client IP address.
        """
        if not self.enabled:
            return

        record = AuditRecord(
            timestamp=datetime.now(timezone.utc).isoformat(),
            user_id=user_id,
            tenant_id=tenant_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            classification=classification,
            allowed=allowed,
            reason=reason,
            source_ip=source_ip,
            conversation_id=conversation_id,
        )

        with self._lock:
            self._buffer.append(record)
            if len(self._buffer) >= self.buffer_size:
                self._flush_unsafe()

    def flush(self) -> int:
        """Force flush buffered records to file.

        Returns:
            Number of records flushed.
        """
        with self._lock:
            return self._flush_unsafe()

    def _flush_unsafe(self) -> int:
        """Write buffered records to file (must hold lock).

        Returns:
            Number of records flushed.
        """
        if not self._buffer:
            return 0

        count = len(self._buffer)
        try:
            dir_path = os.path.dirname(self.file_path)
            if dir_path:
                os.makedirs(dir_path, exist_ok=True)

            with open(self.file_path, "a", encoding="utf-8") as f:
                for record in self._buffer:
                    f.write(record.to_json() + "\n")

        except Exception as e:
            logger.error("Failed to write audit log: %s", e)
            return 0
        finally:
            self._buffer.clear()

        return count

    def __del__(self) -> None:
        """Flush remaining records on destruction."""
        try:
            self.flush()
        except Exception:
            pass


class NullAuditLogger(AuditLogger):
    """No-op audit logger for when auditing is disabled."""

    def __init__(self) -> None:
        super().__init__(enabled=False)

    def log_access(self, *args: Any, **kwargs: Any) -> None:
        """No-op."""
        pass

    def log_raw(self, *args: Any, **kwargs: Any) -> None:
        """No-op."""
        pass

    def flush(self) -> int:
        """No-op."""
        return 0
