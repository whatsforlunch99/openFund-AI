"""Output rail: compliance check and user-profile formatting (Layer 6)."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class ComplianceResult:
    """Result of check_compliance."""

    passed: bool
    reason: Optional[str] = None


class OutputRail:
    """
    Final compliance and formatting before response is returned.

    Used by Responder: check_compliance then format_for_user.
    """

    def check_compliance(self, text: str) -> ComplianceResult:
        """
        Ensure output does not contain explicit buy/sell advice, etc.

        Args:
            text: Proposed response text.

        Returns:
            ComplianceResult with passed flag and optional reason.
        """
        raise NotImplementedError

    def format_for_user(self, text: str, user_profile: str) -> str:
        """
        Adapt tone, length, and disclaimers to user type.

        Args:
            text: Draft response text.
            user_profile: User type (e.g. beginner, long_term, analyst).

        Returns:
            Formatted string for the user.
        """
        raise NotImplementedError
