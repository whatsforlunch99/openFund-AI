"""Output rail: compliance check, output guardrails, and user-profile formatting (Layer 6)."""

import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Optional

# Block list for explicit buy/sell advice in output (aligned with safety_gateway where relevant).
OUTPUT_BLOCKED_PHRASES: tuple[str, ...] = (
    "buy this stock now",
    "sell immediately",
    "guaranteed return",
    "insider tip",
)

# Phrases that turn analysis into explicit investment advice
FINANCIAL_ADVICE_BLOCKLIST: tuple[str, ...] = (
    # Direct trade instructions
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

    # Strong recommendations
    "i strongly recommend buying",
    "i strongly recommend selling",
    "this is a must buy",
    "this is a guaranteed winner",
    "this stock will definitely go up",
    "this stock will definitely go down",

    # Profit guarantees
    "guaranteed profit",
    "guaranteed returns",
    "risk free profit",
    "cannot lose money",
    "surefire investment",
    "guaranteed to double",

    # Timing instructions
    "buy now",
    "sell immediately",
    "enter the trade now",
    "exit the trade now",
    "act immediately",
    "don't miss this opportunity",

    # Personalized investment advice
    "you should allocate your portfolio",
    "put your savings into",
    "invest your retirement money in",
    "move your portfolio into",
)

TOXICITY_THRESHOLD = 0.5

# Regex patterns for secret detection. Match and redact.
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

    # Step 2: profanity filtering
    try:
        import better_profanity

        better_profanity.load_censor_words()
        if better_profanity.contains_profanity(text):
            text = better_profanity.censor(text)
    except ImportError:
        pass

    # Step 3: toxicity detection
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

    # Step 4: PII detection + anonymization
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
        pass
    except Exception:
        pass

    # Step 5: harmful content filtering
    for item in FINANCIAL_ADVICE_BLOCKLIST:
        if _semantic_or_substring_match(text, item):
            raise GuardrailViolation("harmful topic detected")

    # Step 6: regex secret detection
    text = _redact_secrets(text)

    # Step 7: schema validation
    if expected_format == "json":
        try:
            json.loads(text)
        except json.JSONDecodeError as e:
            raise GuardrailViolation(f"Invalid JSON: {e}") from e

    return text


@dataclass
class ComplianceResult:
    """Result of check_compliance."""

    passed: bool
    reason: Optional[str] = None


class OutputRail:
    """
    Final compliance and formatting before response is returned.

    Used by Responder: run_output_guardrail (optional), check_compliance, format_for_user.
    """

    def run_output_guardrail(
        self,
        text: str,
        expected_format: Optional[str] = None,
    ) -> str:
        """
        Run the full output guardrail pipeline (normalize, profanity, toxicity, PII, blocklist, secrets, schema).

        Returns sanitized text. Raises GuardrailViolation if content is rejected.
        """
        return output_guardrail(text, expected_format=expected_format)

    def check_compliance(self, text: str) -> ComplianceResult:
        """
        Ensure output does not contain explicit buy/sell advice, etc.

        Args:
            text: Proposed response text.

        Returns:
            ComplianceResult with passed flag and optional reason.
        """
        # Empty output is treated as non-violating from a phrase-policy perspective.
        if not text or not text.strip():
            return ComplianceResult(passed=True)
        lower = text.lower()
        # Phrase scan is intentionally simple and deterministic for predictable blocking.
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
