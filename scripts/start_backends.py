#!/usr/bin/env python3
"""Check and optionally start PostgreSQL, Neo4j, and Milvus for OpenFund-AI.

Loads .env from project root. For each backend (if configured):
  1. Check if the service is running (port reachable).
  2. If not, try to start it (Homebrew or Docker).
  3. Re-check and report status.

Usage:
  python scripts/start_backends.py
  python scripts/start_backends.py --check-only   # only check, do not start
"""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
from urllib.parse import urlparse


def _project_root() -> str:
    """Project root: parent of the directory containing this script."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_dotenv() -> None:
    root = _project_root()
    try:
        from dotenv import load_dotenv
        path = os.path.join(root, ".env")
        load_dotenv(path)
    except ImportError:
        pass


def _port_open(host: str, port: int, timeout: float = 2.0) -> bool:
    """Return True if host:port accepts a TCP connection."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, socket.timeout):
        return False


def _parse_db_url(url: str) -> tuple[str, int] | None:
    """Extract (host, port) from postgresql://... or postgres://..."""
    if not url or not url.strip():
        return None
    url = url.strip()
    if not url.startswith(("postgresql://", "postgres://")):
        return None
    try:
        p = urlparse(url)
        host = p.hostname or "localhost"
        port = p.port if p.port is not None else 5432
        return (host, port)
    except Exception:
        return None


def _parse_neo4j_uri(uri: str) -> tuple[str, int] | None:
    """Extract (host, port) from bolt://host:7687."""
    if not uri or not uri.strip():
        return None
    uri = uri.strip().replace("bolt://", "//").replace("bolt+s://", "//")
    if "://" not in uri:
        uri = "//" + uri
    try:
        p = urlparse(uri)
        host = p.hostname or "localhost"
        port = p.port if p.port is not None else 7687
        return (host, port)
    except Exception:
        return None


def _parse_milvus_uri(uri: str) -> tuple[str, int] | None:
    """Extract (host, port) from http://host:19530."""
    if not uri or not uri.strip():
        return None
    uri = uri.strip()
    if "://" not in uri:
        uri = "http://" + uri
    try:
        p = urlparse(uri)
        host = p.hostname or "localhost"
        port = p.port if p.port is not None else 19530
        return (host, port)
    except Exception:
        return None


def _run(cmd: list[str], timeout: int = 15, env: dict | None = None) -> tuple[bool, str]:
    """Run command; return (success, stderr_or_stdout)."""
    run_env = (env or os.environ).copy()
    # Ensure Homebrew and common paths are on PATH so brew/neo4j/docker are findable
    extra_paths = [p for p in ("/opt/homebrew/bin", "/usr/local/bin") if os.path.isdir(p)]
    if extra_paths:
        run_env["PATH"] = os.pathsep.join(extra_paths) + os.pathsep + run_env.get("PATH", "")
    try:
        out = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=_project_root(),
            env=run_env,
        )
        msg = (out.stderr or out.stdout or "").strip() or f"exit {out.returncode}"
        return out.returncode == 0, msg
    except subprocess.TimeoutExpired:
        return False, "timeout"
    except FileNotFoundError as e:
        return False, f"command not found: {e.filename}"
    except Exception as e:
        return False, str(e)


def _run_shell(shell_cmd: str, timeout: int = 15) -> tuple[bool, str]:
    """Run a command in a login shell so PATH and brew are available."""
    run_env = os.environ.copy()
    for p in ("/opt/homebrew/bin", "/usr/local/bin"):
        if os.path.isdir(p) and (p not in run_env.get("PATH", "")):
            run_env["PATH"] = p + os.pathsep + run_env.get("PATH", "")
    shell = run_env.get("SHELL", "/bin/bash")
    try:
        out = subprocess.run(
            [shell, "-l", "-c", shell_cmd],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=_project_root(),
            env=run_env,
        )
        msg = (out.stderr or out.stdout or "").strip() or f"exit {out.returncode}"
        return out.returncode == 0, msg
    except subprocess.TimeoutExpired:
        return False, "timeout"
    except Exception as e:
        return False, str(e)


def _brew_path() -> str | None:
    """Return path to brew executable, or None if not found."""
    for p in ("/opt/homebrew/bin/brew", "/usr/local/bin/brew"):
        if os.path.isfile(p):
            return p
    return None


def _start_postgres(host: str, port: int) -> tuple[bool, str]:
    """Try to start PostgreSQL via Homebrew. Returns (success, error_msg)."""
    if host not in ("localhost", "127.0.0.1", "::1", ""):
        return False, "only localhost is auto-started"
    # Prefer login shell so user's PATH is used; fallback to explicit brew path
    for name in ("postgresql@16", "postgresql@15", "postgresql@14", "postgresql"):
        ok, msg = _run_shell(f"brew services start {name}", timeout=15)
        if ok:
            return True, ""
        brew = _brew_path()
        if brew:
            ok, msg = _run([brew, "services", "start", name], timeout=15)
            if ok:
                return True, ""
        if "No such keg" in msg or "Unknown command" in msg:
            continue
        return False, msg or "brew services start failed"
    return False, "PostgreSQL not installed via Homebrew (try: brew install postgresql@16)"


def _start_neo4j(host: str, port: int) -> tuple[bool, str]:
    """Try to start Neo4j via neo4j command or Homebrew. Returns (success, error_msg)."""
    if host not in ("localhost", "127.0.0.1", "::1", ""):
        return False, "only localhost is auto-started"
    ok, msg = _run_shell("neo4j start", timeout=30)
    if ok:
        return True, ""
    brew = _brew_path()
    if brew:
        ok, msg = _run([brew, "services", "start", "neo4j"], timeout=15)
        if ok:
            return True, ""
    return False, msg or "neo4j not in PATH and brew services start neo4j failed"


def _start_milvus(host: str, port: int) -> tuple[bool, str]:
    """Try to start Milvus via Docker. Returns (success, error_msg)."""
    if host not in ("localhost", "127.0.0.1", "::1", ""):
        return False, "only localhost is auto-started"
    # Prefer login shell so docker is on PATH; fallback to explicit /usr/local/bin/docker
    ok, _ = _run_shell("docker start milvus-standalone", timeout=15)
    if ok:
        return True, ""
    for docker_cmd in ("docker", "/usr/local/bin/docker"):
        ok, msg = _run(
            [docker_cmd, "run", "-d", "--name", "milvus-standalone", "-p", "19530:19530", "-p", "9091:9091", "milvusdb/milvus:latest"],
            timeout=120,
        )
        if ok:
            return True, ""
        if "command not found" in msg or "No such file" in msg:
            continue
        return False, msg or "docker run failed"
    return False, "Docker not found (is Docker installed and running?)"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check and optionally start PostgreSQL, Neo4j, Milvus for OpenFund-AI."
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Only check if services are running; do not attempt to start.",
    )
    parser.add_argument(
        "--wait",
        type=int,
        default=5,
        metavar="SECS",
        help="Seconds to wait after starting before re-checking (default 5).",
    )
    args = parser.parse_args()
    _load_dotenv()

    results = []
    check_only = args.check_only
    wait_secs = max(0, args.wait)

    # PostgreSQL
    db_url = os.environ.get("DATABASE_URL", "").strip()
    if db_url:
        parsed = _parse_db_url(db_url)
        if parsed:
            host, port = parsed
            running = _port_open(host, port)
            if running:
                results.append(("PostgreSQL", True, f"running at {host}:{port}"))
            else:
                if check_only:
                    results.append(("PostgreSQL", False, f"not reachable at {host}:{port}"))
                else:
                    started, err = _start_postgres(host, port)
                    if started:
                        time.sleep(wait_secs)
                        running = _port_open(host, port)
                        results.append(("PostgreSQL", running, "started" if running else "start attempted; re-check failed"))
                    else:
                        hint = f"Start manually (e.g. brew services start postgresql). {err}" if err else "Start manually (e.g. brew services start postgresql)"
                        results.append(("PostgreSQL", False, f"not running at {host}:{port}. {hint}"))
        else:
            results.append(("PostgreSQL", False, "DATABASE_URL could not be parsed"))
    else:
        results.append(("PostgreSQL", None, "DATABASE_URL not set (skipped)"))

    # Neo4j
    neo_uri = os.environ.get("NEO4J_URI", "").strip()
    if neo_uri:
        parsed = _parse_neo4j_uri(neo_uri)
        if parsed:
            host, port = parsed
            running = _port_open(host, port)
            if running:
                results.append(("Neo4j", True, f"running at {host}:{port}"))
            else:
                if check_only:
                    results.append(("Neo4j", False, f"not reachable at {host}:{port}"))
                else:
                    started, err = _start_neo4j(host, port)
                    if started:
                        time.sleep(wait_secs)
                        running = _port_open(host, port)
                        results.append(("Neo4j", running, "started" if running else "start attempted; re-check failed"))
                    else:
                        hint = f"Start manually (e.g. neo4j start). {err}" if err else "Start manually (e.g. neo4j start or brew services start neo4j)"
                        results.append(("Neo4j", False, f"not running at {host}:{port}. {hint}"))
        else:
            results.append(("Neo4j", False, "NEO4J_URI could not be parsed"))
    else:
        results.append(("Neo4j", None, "NEO4J_URI not set (skipped)"))

    # Milvus
    milvus_uri = os.environ.get("MILVUS_URI", "").strip()
    if milvus_uri:
        parsed = _parse_milvus_uri(milvus_uri)
        if parsed:
            host, port = parsed
            running = _port_open(host, port)
            if running:
                results.append(("Milvus", True, f"running at {host}:{port}"))
            else:
                if check_only:
                    results.append(("Milvus", False, f"not reachable at {host}:{port}"))
                else:
                    started, err = _start_milvus(host, port)
                    if started:
                        time.sleep(max(wait_secs, 10))
                        running = _port_open(host, port)
                        results.append(("Milvus", running, "started" if running else "start attempted; re-check failed (may need more time)"))
                    else:
                        hint = f"Start manually. {err}" if err else "Start manually (e.g. docker run -d -p 19530:19530 milvusdb/milvus:latest)"
                        results.append(("Milvus", False, f"not running at {host}:{port}. {hint}"))
        else:
            results.append(("Milvus", False, "MILVUS_URI could not be parsed"))
    else:
        results.append(("Milvus", None, "MILVUS_URI not set (skipped)"))

    # Print summary
    for name, status, msg in results:
        if status is None:
            print(f"  {name}: {msg}")
        elif status:
            print(f"  {name}: OK — {msg}")
        else:
            print(f"  {name}: NOT RUNNING — {msg}", file=sys.stderr)

    all_ok = all(s in (True, None) for _, s, _ in results)
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
