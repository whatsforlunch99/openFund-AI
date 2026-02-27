"""Load .env from project root so data CLI and populate work from any cwd."""

from __future__ import annotations

import os

# Project root: parent of the data package directory
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_dotenv() -> None:
    """Load .env from the project root. Call before using DATABASE_URL, NEO4J_URI, MILVUS_URI."""
    try:
        from dotenv import load_dotenv as _load

        path = os.path.join(_PROJECT_ROOT, ".env")
        _load(path)
    except ImportError:
        pass
