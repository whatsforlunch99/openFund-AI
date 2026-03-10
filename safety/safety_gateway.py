"""Safety gateway: input validation, guardrails, PII masking, and output screening (Layer 2)."""

import json
import logging
import re
import unicodedata
from dataclasses import dataclass
from typing import Optional

from util import interaction_log

logger = logging.getLogger(__name__)
# Max input length enforced so very long payloads are rejected before processing (backend contract).
MAX_INPUT_LENGTH = 10_000

# Shared blocked phrases for both input guardrails and output compliance (case-insensitive).
BLOCKED_PHRASES: tuple[str, ...] = (
    "guaranteed return",
    "buy this stock now",
    "insider tip",
    "sell immediately",
)

# Extended blocklist for output_guardrail harmful-content step only.
FINANCIAL_ADVICE_BLOCKLIST: tuple[str, ...] = (
    "you should buy",
    "you should sell",
    "you should short",
    "you should go long",
    "you should open a position",
    "you should close your position",
    "you should invest in",
    "buy this stock",
    "sell this stock",
    "purchase shares of",
    "dump your shares",
    "i strongly recommend buying",
    "i strongly recommend selling",
    "this is a must buy",
    "this is a guaranteed winner",
    "this stock will definitely go up",
    "this stock will definitely go down",
    "guaranteed profit",
    "guaranteed returns",
    "risk free profit",
    "cannot lose money",
    "surefire investment",
    "guaranteed to double",
    "buy now",
    "sell immediately",
    "enter the trade now",
    "exit the trade now",
    "act immediately",
    "don't miss this opportunity",
    "you should allocate your portfolio",
    "put your savings into",
    "invest your retirement money in",
    "move your portfolio into",
)

TOXICITY_THRESHOLD = 0.5

# Regex patterns for secret detection in output.
AWS_KEY_REGEX = re.compile(
    r"(?<![A-Za-z0-9/+=])(A3T[A-Z0-9]|ABIA|ACCA|AROA|AIDA|APKA|ASIA)[A-Z0-9]{16}(?![A-Za-z0-9/+=])",
    re.IGNORECASE,
)
PRIVATE_KEY_REGEX = re.compile(
    r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----[\s\S]+?-----END (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----",
)
API_TOKEN_REGEX = re.compile(
    r"\b(?:api[_-]?key|apikey|api[_-]?secret|token)['\"]?\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{20,}['\"]?",
    re.IGNORECASE,
)
SECRET_PATTERNS: tuple[re.Pattern, ...] = (AWS_KEY_REGEX, PRIVATE_KEY_REGEX, API_TOKEN_REGEX)


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


@dataclass
class ComplianceResult:
    """Result of check_output_compliance (output phrase scan)."""

    passed: bool
    reason: Optional[str] = None


class GuardrailViolation(Exception):
    """Raised when output guardrail rejects content (e.g. toxic or harmful topic)."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def normalize_unicode(text: str) -> str:
    """Normalize to NFC."""
    if not text:
        return text
    return unicodedata.normalize("NFC", text)


def trim_whitespace(text: str) -> str:
    """Strip and collapse internal runs of whitespace to single space."""
    if not text:
        return text
    return " ".join(text.split())


def _redact_secrets(text: str) -> str:
    """Replace secret pattern matches with [REDACTED]."""
    out = text
    for pattern in SECRET_PATTERNS:
        out = pattern.sub("[REDACTED]", out)
    return out


def _semantic_or_substring_match(text: str, item: str) -> bool:
    """True if text matches blocklist item. Uses guardrails_ai if available, else substring."""
    try:
        from guardrails import Guard
        from guardrails.hub import Detect

        guard = Guard().use(Detect(item), item)
        result = guard.validate(text)
        return not result.validation_passed
    except Exception:
        pass
    return item.lower() in text.lower()


def check_output_compliance(text: str) -> ComplianceResult:
    """
    Ensure output does not contain blocked phrases (same list as input guardrails).

    Args:
        text: Proposed response text.

    Returns:
        ComplianceResult with passed flag and optional reason.
    """
    if not text or not text.strip():
        return ComplianceResult(passed=True)
    lower = text.lower()
    for phrase in BLOCKED_PHRASES:
        if phrase in lower:
            return ComplianceResult(
                passed=False,
                reason=f"Output contains disallowed phrase: {phrase!r}",
            )
    return ComplianceResult(passed=True)


def output_guardrail(
    llm_output: str,
    expected_format: Optional[str] = None,
) -> str:
    """
    Run the output guardrail pipeline: normalize, profanity, toxicity, PII, blocklist, secrets, schema.

    Args:
        llm_output: Raw LLM output text.
        expected_format: If "json", validate that text is valid JSON after other steps.

    Returns:
        Sanitized text.

    Raises:
        GuardrailViolation: If toxicity exceeds threshold or harmful topic detected.
    """
    if llm_output is None:
        return ""
    text = normalize_unicode(llm_output)
    text = trim_whitespace(text)

    # Profanity filtering
    try:
        import better_profanity

        better_profanity.load_censor_words()
        if better_profanity.contains_profanity(text):
            text = better_profanity.censor(text)
    except ImportError:
        pass

    # Toxicity detection
    try:
        from detoxify import Detoxify

        model = Detoxify("original")
        scores = model.predict(text)
        toxicity = scores.get("toxicity") or scores.get("identity_attack") or 0.0
        if isinstance(toxicity, (list, tuple)):
            toxicity = max(toxicity) if toxicity else 0.0
        if toxicity > TOXICITY_THRESHOLD:
            raise GuardrailViolation("toxic output detected")
    except ImportError:
        pass
    except GuardrailViolation:
        raise
    except Exception:
        pass

    # PII: use presidio when available, else regex mask_pii
    try:
        from presidio_analyzer import AnalyzerEngine
        from presidio_anonymizer import AnonymizerEngine

        analyzer = AnalyzerEngine()
        pii_entities = analyzer.analyze(
            text=text,
            language="en",
            entities=["PHONE_NUMBER", "EMAIL_ADDRESS", "CREDIT_CARD", "US_SSN", "SG_NRIC_FIN"],
        )
        if pii_entities:
            anonymizer = AnonymizerEngine()
            anonymized = anonymizer.anonymize(text=text, analyzer_results=pii_entities)
            text = anonymized.text
    except ImportError:
        gateway = SafetyGateway()
        text = gateway.mask_pii(text)
    except Exception:
        gateway = SafetyGateway()
        text = gateway.mask_pii(text)

    # Harmful content (financial advice blocklist)
    for item in FINANCIAL_ADVICE_BLOCKLIST:
        if _semantic_or_substring_match(text, item):
            raise GuardrailViolation("harmful topic detected")

    # Secret redaction
    text = _redact_secrets(text)

    # Schema validation
    if expected_format == "json":
        try:
            json.loads(text)
        except json.JSONDecodeError as e:
            raise GuardrailViolation(f"Invalid JSON: {e}") from e

    return text


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
        interaction_log.log_call(
            "safety.safety_gateway.SafetyGateway.process_user_input",
            params={"query_len": len(raw_input)},
        )
        # Validate length and charset; raise if invalid
        vr = self.validate_input(raw_input)
        if not vr.valid:
            interaction_log.log_call(
                "safety.safety_gateway.SafetyGateway.process_user_input",
                result={"error": vr.reason},
            )
            raise SafetyError(vr.reason or "Validation failed")

        # Block disallowed phrases (e.g. investment advice)
        gr = self.check_guardrails(raw_input)
        if not gr.allowed:
            interaction_log.log_call(
                "safety.safety_gateway.SafetyGateway.process_user_input",
                result={"error": gr.reason},
            )
            raise SafetyError(gr.reason or "Guardrails blocked input")

        # Mask PII then return cleaned input and metadata
        masked_text = self.mask_pii(raw_input)
        result = ProcessedInput(
            text=masked_text,
            raw_length=len(raw_input),
            masked=(masked_text != raw_input),
        )
        interaction_log.log_call(
            "safety.safety_gateway.SafetyGateway.process_user_input",
            result={
                "processed_length": len(masked_text),
                "raw_length": result.raw_length,
                "masked": result.masked,
            },
        )
        return result


class OutputRail:
    """
    Response formatting by user profile. Screening (compliance, guardrail) in same module.
    """

    def run_output_guardrail(
        self,
        text: str,
        expected_format: Optional[str] = None,
    ) -> str:
        """Run the output guardrail pipeline. Raises GuardrailViolation if rejected."""
        return output_guardrail(text, expected_format=expected_format)

    def check_compliance(self, text: str) -> ComplianceResult:
        """Check output for blocked phrases."""
        return check_output_compliance(text)

    def format_for_user(self, text: str, user_profile: str) -> str:
        """
        Adapt tone and disclaimers to user type.

        Args:
            text: Draft response text.
            user_profile: User type (e.g. beginner, long_term, analyst).

        Returns:
            Formatted string for the user.
        """
        profile = (user_profile or "").strip().lower()
        if profile not in ("beginner", "long_term", "analyst"):
            profile = "beginner"

        if profile == "beginner":
            disclaimer = "This is not investment advice."
            return f"{text.strip()}\n\n{disclaimer}"
        if profile == "long_term":
            line = "Consider a long-term horizon and disciplined rebalancing."
            return f"{text.strip()}\n\n{line}"
        if profile == "analyst":
            return f"Analysis: {text.strip()}"
        return text.strip()
