"""Output rail: compliance check and user-profile formatting (Layer 6)."""

from dataclasses import dataclass
from typing import Optional

# Block list for explicit buy/sell advice in output (aligned with safety_gateway where relevant).
OUTPUT_BLOCKED_PHRASES: tuple[str, ...] = (
    "buy this stock now",
    "sell immediately",
    "guaranteed return",
    "insider tip",
)


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
        if not text or not text.strip():
            return ComplianceResult(passed=True)
        lower = text.lower()
        for phrase in OUTPUT_BLOCKED_PHRASES:
            if phrase in lower:
                return ComplianceResult(
                    passed=False,
                    reason=f"Output contains disallowed phrase: {phrase!r}",
                )
        return ComplianceResult(passed=True)

    def format_for_user(self, text: str, user_profile: str) -> str:
        """
        Adapt tone, length, and disclaimers to user type.

        Args:
            text: Draft response text.
            user_profile: User type (e.g. beginner, long_term, analyst).

        Returns:
            Formatted string for the user.
        """
        profile = (user_profile or "").strip().lower()
        if profile not in ("beginner", "long_term", "analyst"):
            profile = "beginner"

        # Add disclaimer or tag per profile type
        if profile == "beginner":
            disclaimer = "This is not investment advice."
            return f"{text.strip()}\n\n{disclaimer}"
        if profile == "long_term":
            line = "Consider a long-term horizon and disciplined rebalancing."
            return f"{text.strip()}\n\n{line}"
        if profile == "analyst":
            return f"Analysis: {text.strip()}"
        return text.strip()
