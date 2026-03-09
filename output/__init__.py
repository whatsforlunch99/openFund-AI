"""Layer 6: Output rail."""

# OutputRail is intentionally isolated so compliance/formatting rules stay centralized.
from output.output_rail import (
    GuardrailViolation,
    OutputRail,
    output_guardrail,
)

__all__ = ["OutputRail", "output_guardrail", "GuardrailViolation"]
