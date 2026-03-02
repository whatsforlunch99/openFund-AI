"""Data masking and desensitization.

Provides field-level masking rules for sensitive data that passes
authorization but should be partially hidden before display.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from permission.models import CLEARANCE_HIERARCHY


@dataclass
class MaskingRule:
    """Rule for field-level data masking.

    Attributes:
        field_pattern: Regex pattern to match field names.
        min_classification: Minimum classification level to trigger masking.
        mask_type: Type of masking (full, partial, hash, round).
        mask_char: Character to use for masking (default "*").
    """

    field_pattern: str
    min_classification: str
    mask_type: str
    mask_char: str = "*"

    def matches_field(self, field_name: str) -> bool:
        """Check if this rule applies to the given field name."""
        try:
            return bool(re.match(self.field_pattern, field_name, re.IGNORECASE))
        except re.error:
            return False

    def should_mask(self, classification: str) -> bool:
        """Check if masking should be applied for the given classification."""
        min_level = CLEARANCE_HIERARCHY.get(self.min_classification, 0)
        data_level = CLEARANCE_HIERARCHY.get(classification, 0)
        return data_level >= min_level


DEFAULT_MASKING_RULES: list[MaskingRule] = [
    MaskingRule(
        field_pattern=r"^(aum|assets_under_management|total_assets|net_assets)$",
        min_classification="CONFIDENTIAL",
        mask_type="round",
    ),
    MaskingRule(
        field_pattern=r"^(account_number|account_id|client_id)$",
        min_classification="RESTRICTED",
        mask_type="partial",
    ),
    MaskingRule(
        field_pattern=r"^(ssn|social_security|tax_id|ein)$",
        min_classification="RESTRICTED",
        mask_type="full",
    ),
    MaskingRule(
        field_pattern=r"^(email|phone|address|zip_code)$",
        min_classification="CONFIDENTIAL",
        mask_type="partial",
    ),
    MaskingRule(
        field_pattern=r"^(password|secret|api_key|token)$",
        min_classification="PUBLIC",
        mask_type="full",
    ),
]


def mask_value(value: Any, rule: MaskingRule) -> Any:
    """Apply masking to a single value.

    Args:
        value: Value to mask.
        rule: Masking rule to apply.

    Returns:
        Masked value.
    """
    if value is None:
        return None

    if rule.mask_type == "full":
        if isinstance(value, str):
            return rule.mask_char * len(value) if value else ""
        return rule.mask_char * 8

    if rule.mask_type == "partial":
        if isinstance(value, str) and len(value) > 4:
            visible = 4
            return rule.mask_char * (len(value) - visible) + value[-visible:]
        return rule.mask_char * 4

    if rule.mask_type == "round":
        if isinstance(value, (int, float)):
            if value >= 1_000_000_000:
                return round(value / 1_000_000_000) * 1_000_000_000
            if value >= 1_000_000:
                return round(value / 1_000_000) * 1_000_000
            if value >= 1_000:
                return round(value / 1_000) * 1_000
            return round(value, -1)
        return value

    if rule.mask_type == "hash":
        import hashlib
        str_val = str(value)
        return hashlib.sha256(str_val.encode()).hexdigest()[:16]

    return value


def apply_masking(
    data: dict[str, Any],
    classification: str,
    rules: list[MaskingRule] | None = None,
) -> dict[str, Any]:
    """Apply masking rules to data before returning to user.

    Used in LLM response generation to desensitize values.

    Args:
        data: Dictionary of field names to values.
        classification: Data classification level.
        rules: Masking rules to apply (default: DEFAULT_MASKING_RULES).

    Returns:
        Dictionary with masked values.
    """
    rules = rules or DEFAULT_MASKING_RULES
    result = {}

    for key, value in data.items():
        masked = False
        for rule in rules:
            if rule.matches_field(key) and rule.should_mask(classification):
                result[key] = mask_value(value, rule)
                masked = True
                break
        if not masked:
            if isinstance(value, dict):
                result[key] = apply_masking(value, classification, rules)
            elif isinstance(value, list):
                result[key] = [
                    apply_masking(item, classification, rules) if isinstance(item, dict) else item
                    for item in value
                ]
            else:
                result[key] = value

    return result


def create_masking_rule(
    field_pattern: str,
    min_classification: str,
    mask_type: str,
    mask_char: str = "*",
) -> MaskingRule:
    """Create a new masking rule.

    Args:
        field_pattern: Regex pattern to match field names.
        min_classification: Minimum classification level to trigger masking.
        mask_type: Type of masking (full, partial, hash, round).
        mask_char: Character to use for masking.

    Returns:
        New MaskingRule instance.
    """
    return MaskingRule(
        field_pattern=field_pattern,
        min_classification=min_classification,
        mask_type=mask_type,
        mask_char=mask_char,
    )
