"""File read/list (MCP tool).

When MCP_FILE_BASE_DIR is set, read_file only allows paths under that directory
(to avoid path traversal). If unset, path is used as-is (trusted caller only).
"""

from __future__ import annotations

import os


def read_file(path: str) -> dict:
    """Read file content and metadata.

    When MCP_FILE_BASE_DIR is set, path must resolve under that directory;
    otherwise any path is allowed (suitable when path comes from trusted agents only).

    Args:
        path: File path.

    Returns:
        Dict with "content" and "path" on success; dict with "error" and "path" on failure.
    """
    base_dir = os.getenv("MCP_FILE_BASE_DIR")
    if base_dir:
        # Safety gate: resolve and constrain target path under configured base directory.
        base_dir = os.path.abspath(base_dir)
        try:
            abs_path = os.path.abspath(path)
        except OSError as e:
            return {"error": str(e), "path": path}
        if not abs_path.startswith(base_dir):
            return {
                "error": "Path not allowed (outside MCP_FILE_BASE_DIR)",
                "path": path,
            }
        path = abs_path
    try:
        # Read file as UTF-8; return content and path for agent consumption
        with open(path, encoding="utf-8") as f:
            content = f.read()
        return {"content": content, "path": path}
    except OSError as e:
        return {"error": str(e), "path": path}


def list_files(prefix: str) -> list[str]:
    """List files under a prefix path.

    Args:
        prefix: Path prefix.

    Returns:
        List of file paths.
    """
    raise NotImplementedError
