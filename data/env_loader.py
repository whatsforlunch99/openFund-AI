"""Legacy env loader wrapper for compatibility with older imports."""

from config.config import load_config


def load_dotenv() -> None:
    """Load project configuration/.env via central config loader."""
    load_config()
