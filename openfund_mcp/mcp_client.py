"""MCP client: invoke tools on the FastMCP server via MCP SDK (stdio subprocess)."""

from __future__ import annotations

import json
import os
import queue
import threading
import time
from typing import Any, Optional

from util import interaction_log

# Lazy imports for MCP SDK (mcp package is the SDK; our package is openfund_mcp)
_ClientSession: Any = None
_stdio_client: Any = None
_StdioServerParameters: Any = None


def _ensure_sdk() -> None:
    global _ClientSession, _stdio_client, _StdioServerParameters
    if _ClientSession is not None:
        return
    try:
        from mcp import ClientSession, StdioServerParameters, stdio_client

        _ClientSession = ClientSession
        _StdioServerParameters = StdioServerParameters
        _stdio_client = stdio_client
    except ImportError as e:
        import sys

        py_ver = f"{sys.version_info.major}.{sys.version_info.minor}"
        hint = (
            "MCP SDK requires Python 3.10+. This environment is Python "
            f"{py_ver}. Recreate the venv with Python 3.11+ and run: pip install -e ."
        )
        raise RuntimeError(
            f"MCP SDK not installed or not importable ({e}). {hint}"
        ) from e


class MCPClient:
    """Client that spawns the FastMCP server as a subprocess and calls tools over stdio.

    For tests, an optional in-process MCPServer can be passed to avoid subprocess.
    """

    def __init__(
        self,
        server: Any = None,
        command: str = "python",
        args: tuple[str, ...] = ("-m", "openfund_mcp"),
        cwd: str = "",
        env: Optional[dict[str, str]] = None,
    ) -> None:
        """Initialize the client.

        Args:
            server: Optional MCPServer for in-process (tests). If set, tool calls use server.dispatch.
            command: Executable to run when using FastMCP subprocess.
            args: Arguments (e.g. ("-m", "openfund_mcp")).
            cwd: Working directory for the subprocess.
            env: Optional env for subprocess.
        """
        self._server = server if (hasattr(server, "dispatch") and hasattr(server, "_handlers")) else None
        self._use_sdk = self._server is None
        if self._use_sdk:
            _ensure_sdk()
            self._command = command
            self._args = list(args)
            self._cwd = cwd or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            self._env = env
            self._lock = threading.Lock()
            self._thread = None
            self._request_queue = queue.Queue()
            self._response_queue = queue.Queue()
            self._closed = False
        else:
            self._command = self._args = self._cwd = self._env = None
            self._lock = self._thread = self._request_queue = self._response_queue = None

    def _start_session_thread(self) -> None:
        if not self._use_sdk:
            return
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._thread = threading.Thread(target=self._run_session_loop, daemon=True)
            self._thread.start()
            # Wait for session ready or error
            try:
                msg = self._response_queue.get(timeout=30)
            except queue.Empty:
                raise RuntimeError("MCP server failed to start within 30s")
            if isinstance(msg, BaseException):
                raise RuntimeError(f"MCP server failed: {msg}") from msg

    def _run_session_loop(self) -> None:
        import anyio

        async def run() -> None:
            params = _StdioServerParameters(
                command=self._command,
                args=self._args,
                cwd=self._cwd or None,
                env=self._env,
            )
            try:
                async with _stdio_client(params) as (read_stream, write_stream):
                    async with _ClientSession(read_stream, write_stream) as session:
                        await session.initialize()
                        self._response_queue.put("ready")
                        while not self._closed:
                            try:
                                req = self._request_queue.get(timeout=0.5)
                            except queue.Empty:
                                continue
                            if req is None:
                                break
                            action = req.get("action")
                            future = req.get("future")
                            try:
                                if action == "list_tools":
                                    result = await session.list_tools()
                                    names = sorted(t.name for t in result.tools)
                                    future.set_result(names)
                                elif action == "call_tool":
                                    name = req["name"]
                                    arguments = req.get("arguments") or {}
                                    tool_result = await session.call_tool(name, arguments=arguments)
                                    if getattr(tool_result, "isError", getattr(tool_result, "is_error", False)):
                                        future.set_result({"error": str(tool_result.content or "unknown error")})
                                    else:
                                        out = self._parse_tool_result(tool_result)
                                        future.set_result(out)
                                else:
                                    future.set_exception(ValueError(f"Unknown action: {action}"))
                            except Exception as e:
                                future.set_exception(e)
            except Exception as e:
                self._response_queue.put(e)

        try:
            anyio.run(run)
        except Exception as e:
            self._response_queue.put(e)

    @staticmethod
    def _parse_tool_result(tool_result: Any) -> dict:
        """Convert MCP CallToolResult content to our dict format."""
        content = getattr(tool_result, "content", None) or []
        if not content:
            return {}
        first = content[0] if isinstance(content, list) else content
        text = getattr(first, "text", None) if first else None
        if text is None and isinstance(first, dict):
            text = first.get("text")
        if not text:
            return {}
        try:
            return json.loads(text)
        except (TypeError, json.JSONDecodeError):
            return {"content": text}

    def get_registered_tool_names(self) -> list[str]:
        """Return sorted list of tool names from the FastMCP server or in-process server."""
        if not self._use_sdk:
            return sorted(self._server._handlers.keys())
        self._start_session_thread()
        import concurrent.futures

        future: concurrent.futures.Future = concurrent.futures.Future()
        self._request_queue.put({"action": "list_tools", "future": future})
        return future.result(timeout=30)

    def call_tool(self, tool_name: str, payload: dict) -> dict:
        """Invoke a tool on the FastMCP server or in-process server.

        Args:
            tool_name: Name of the tool (e.g. vector_tool.search).
            payload: Tool parameters.

        Returns:
            Tool response dict.
        """
        start = time.perf_counter()
        if not self._use_sdk:
            result = self._server.dispatch(tool_name, payload)
        else:
            self._start_session_thread()
            import concurrent.futures

            future: concurrent.futures.Future = concurrent.futures.Future()
            self._request_queue.put({
                "action": "call_tool",
                "name": tool_name,
                "arguments": payload,
                "future": future,
            })
            try:
                result = future.result(timeout=60)
            except concurrent.futures.TimeoutError:
                result = {"error": "Tool call timed out after 60s"}
            except Exception as e:
                result = {"error": str(e)}
        duration_ms = (time.perf_counter() - start) * 1000.0

        result_summary: dict = {}
        _max_preview = 300

        if isinstance(result, dict):
            result_summary["result_keys"] = list(result.keys())
            if "error" in result:
                result_summary["error"] = str(result.get("error", ""))[:200]
            for k in ("documents", "rows", "content", "data", "plan"):
                if k in result and result[k] is not None:
                    val = result[k]
                    result_summary[f"{k}_size"] = len(val) if isinstance(val, (list, str)) else 1
                    break
            preview_parts = []
            for key in ("rows", "data", "content", "documents", "plan", "schema"):
                if key not in result or result[key] is None:
                    continue
                raw = result[key]
                try:
                    s = json.dumps(raw, default=str) if not isinstance(raw, str) else raw
                except (TypeError, ValueError):
                    s = str(raw)
                s = (s[: _max_preview] + "...") if len(s) > _max_preview else s
                if s.strip():
                    preview_parts.append(s)
                    break
            if preview_parts:
                result_summary["result_preview"] = preview_parts[0]
        else:
            result_summary["result_type"] = type(result).__name__
        interaction_log.log_call(
            "openfund_mcp.mcp_client.MCPClient.call_tool",
            params={"tool_name": tool_name, "payload": payload},
            result=result_summary or result,
            duration_ms=round(duration_ms, 2),
        )
        return result

    def close(self) -> None:
        """Signal the session loop to exit (daemon thread will stop with process)."""
        self._closed = True
        self._request_queue.put(None)
