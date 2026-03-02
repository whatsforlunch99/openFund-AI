"""Layer 2: Safety gateway."""

# Re-export the primary safety entry points for API-layer imports.
from safety.safety_gateway import SafetyError, SafetyGateway  # noqa: F401

__all__ = ["SafetyError", "SafetyGateway"]
