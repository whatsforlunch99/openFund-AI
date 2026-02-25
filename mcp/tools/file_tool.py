"""File read/list (MCP tool)."""

from typing import List


def read_file(path: str) -> dict:
    """
    Read file content and metadata.

    Args:
        path: File path.

    Returns:
        Dict with content and metadata (content, path). On error, dict with error key.
    """
    try:
        with open(path, encoding="utf-8") as f:
            content = f.read()
        return {"content": content, "path": path}
    except OSError as e:
        return {"error": str(e), "path": path}


def list_files(prefix: str) -> List[str]:
    """
    List files under a prefix path.

    Args:
        prefix: Path prefix.

    Returns:
        List of file paths.
    """
    raise NotImplementedError
