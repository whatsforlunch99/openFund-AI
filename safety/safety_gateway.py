"""Safety gateway: input validation, guardrails, PII masking (Layer 2)."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class ValidationResult:
    """Result of validate_input."""

    valid: bool
    reason: Optional[str] = None


@dataclass
class GuardrailResult:
    """Result of check_guardrails."""

    allowed: bool
    reason: Optional[str] = None


@dataclass
class ProcessedInput:
    """Result of process_user_input: cleaned text and metadata."""

    text: str
    raw_length: int
    masked: bool = False


class SafetyGateway:
    """
    Single entry point before user input reaches the message bus.

    Runs validation, guardrails (block list for illegal advice), and
    PII masking. All user input should pass through process_user_input.
    """

    def validate_input(self, text: str) -> ValidationResult:
        """
        Basic sanity checks: length, charset.

        Args:
            text: Raw user input.

        Returns:
            ValidationResult with valid flag and optional reason.
        """
        raise NotImplementedError

    def check_guardrails(self, text: str) -> GuardrailResult:
        """
        Block list for illegal investment-advice phrases.

        Args:
            text: User or content to check.

        Returns:
            GuardrailResult with allowed flag and optional reason.
        """
        raise NotImplementedError

    def mask_pii(self, text: str) -> str:
        """
        Mask PII (IDs, phone numbers, etc.) in text.

        Args:
            text: Text that may contain PII.

        Returns:
            Desensitized string.
        """
        raise NotImplementedError

    def process_user_input(self, raw_input: str) -> ProcessedInput:
        """
        Run validate -> check_guardrails -> mask_pii.

        Args:
            raw_input: Raw user query.

        Returns:
            ProcessedInput with cleaned text and metadata.
            Raises or returns error state if validation/guardrails fail.
        """
        raise NotImplementedError
