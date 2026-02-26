"""Safety gateway: input validation, guardrails, PII masking (Layer 2)."""

import re
from dataclasses import dataclass
from typing import Optional

MAX_INPUT_LENGTH = 10_000

# Phrases that indicate illegal investment advice (case-insensitive).
BLOCKED_PHRASES: tuple[str, ...] = (
    "guaranteed return",
    "buy this stock now",
    "insider tip",
)


class SafetyError(Exception):
    """Raised when validation or guardrails fail. Mapped to HTTP 400."""

    def __init__(self, reason: str, code: Optional[str] = None) -> None:
        self.reason = reason
        self.code = code
        super().__init__(reason)


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


def _is_printable_or_whitespace(text: str) -> bool:
    """Allow UTF-8 printable and common whitespace (tab, newline, carriage return, space)."""
    for c in text:
        if c in "\t\n\r ":
            continue
        if ord(c) < 32:
            return False
        # Allow printable (incl. high Unicode)
        if ord(c) == 0x7F:
            return False  # DEL
    return True


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
        if not text or not text.strip():
            return ValidationResult(
                valid=False, reason="Input is empty or whitespace only"
            )
        if len(text) > MAX_INPUT_LENGTH:
            return ValidationResult(
                valid=False,
                reason=f"Input exceeds maximum length of {MAX_INPUT_LENGTH} characters",
            )
        if not _is_printable_or_whitespace(text):
            return ValidationResult(
                valid=False, reason="Input contains invalid characters"
            )
        return ValidationResult(valid=True)

    def check_guardrails(self, text: str) -> GuardrailResult:
        """
        Block list for illegal investment-advice phrases.

        Args:
            text: User or content to check.

        Returns:
            GuardrailResult with allowed flag and optional reason.
        """
        lower = text.lower()
        for phrase in BLOCKED_PHRASES:
            if phrase in lower:
                return GuardrailResult(
                    allowed=False,
                    reason=f"Blocked phrase not allowed: {phrase!r}",
                )
        return GuardrailResult(allowed=True)

    def mask_pii(self, text: str) -> str:
        """
        Mask PII (IDs, phone numbers, etc.) in text.

        Replaces phone numbers, emails, and SSN-like patterns with placeholders.
        """
        out = text
        # Phone: digits with optional separators (dashes, spaces, dots, parens)
        out = re.sub(
            r"\b(?:\d[\d\s\-\.]{8,14}\d|\d{3}[-.\s]?\d{3}[-.\s]?\d{4})\b",
            "[PHONE]",
            out,
        )
        # Email: local@domain
        out = re.sub(
            r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
            "[EMAIL]",
            out,
        )
        # SSN-like: xxx-xx-xxxx
        out = re.sub(r"\b\d{3}-\d{2}-\d{4}\b", "[REDACTED]", out)
        return out

    def process_user_input(self, raw_input: str) -> ProcessedInput:
        """
        Run validate -> check_guardrails -> mask_pii.

        Args:
            raw_input: Raw user query.

        Returns:
            ProcessedInput with cleaned text and metadata.
            Raises SafetyError if validation or guardrails fail.
        """
        vr = self.validate_input(raw_input)
        if not vr.valid:
            raise SafetyError(vr.reason or "Validation failed")
        gr = self.check_guardrails(raw_input)
        if not gr.allowed:
            raise SafetyError(gr.reason or "Guardrails blocked input")
        masked_text = self.mask_pii(raw_input)
        return ProcessedInput(
            text=masked_text,
            raw_length=len(raw_input),
            masked=(masked_text != raw_input),
        )
