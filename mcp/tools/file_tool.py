"""File read/list (MCP tool)."""

from typing import List, Optional


def read_file(path: str) -> dict:
    """
    Read file content and metadata.

    Args:
        path: File path.

    Returns:
        Dict with content and metadata.
    """
    raise NotImplementedError


def list_files(prefix: str) -> List[str]:
    """
    List files under a prefix path.

    Args:
        prefix: Path prefix.

    Returns:
        List of file paths.
    """
    raise NotImplementedError
