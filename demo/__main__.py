"""Single-command demo: start API and run the chat client.

Usage:
  python -m demo
  python -m demo --ensure-data

Starts the API server in the background, waits for it to be ready, then runs
the interactive chat. Uses real data, real API calls, and real LLM from .env.
Use --ensure-data to load datasets/combined_funds.json (or JSON files in datasets/)
into PostgreSQL/Neo4j before starting.
Type quit/exit to stop.
"""

from __future__ import annotations

import atexit
import os
import subprocess
import sys
import time

# Project root (parent of demo package)
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _wait_for_server(base_url: str, timeout_seconds: float = 30) -> bool:
    """Return True when GET base_url/demo succeeds."""
    try:
        import requests
    except ImportError:
        print("Install requests: pip install requests", file=sys.stderr)
        return False
    url = f"{base_url.rstrip('/')}/demo"
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            r = requests.get(url, timeout=2)
            if r.status_code == 200:
                return True
        except requests.RequestException:
            pass
        time.sleep(0.3)
    return False


def main() -> int:
    # Ensure project root is on path and load .env first
    if _PROJECT_ROOT not in sys.path:
        sys.path.insert(0, _PROJECT_ROOT)
    from config.config import load_config

    load_config()

    # Parse our flags (do not pass to server or chat)
    ensure_data = "--ensure-data" in sys.argv
    base_url = "http://localhost:8000"
    if "--base-url" in sys.argv:
        i = sys.argv.index("--base-url")
        if i + 1 < len(sys.argv):
            base_url = sys.argv[i + 1].rstrip("/")

    if ensure_data:
        combined_file = os.path.join(_PROJECT_ROOT, "datasets", "combined_funds.json")
        datasets_dir = os.path.join(_PROJECT_ROOT, "datasets")
        print("Loading fund data into backends...")
        try:
            from data_manager.distributor import DataDistributor

            dist = DataDistributor()
            if os.path.isfile(combined_file):
                batch = dist.distribute_fund_file(combined_file)
            elif os.path.isdir(datasets_dir):
                batch = dist.distribute_funds_dir(datasets_dir)
            else:
                batch = None

            if batch is None:
                print("  datasets not found; skipping.", file=sys.stderr)
            else:
                print(
                    f"  PostgreSQL: {batch.postgres_rows} rows, Neo4j: {batch.neo4j_nodes} nodes, {batch.neo4j_edges} edges."
                )
        except Exception as e:
            print(f"  Warning: could not load fund data: {e}", file=sys.stderr)

    print("Starting API...")
    proc = subprocess.Popen(
        [sys.executable, "main.py"],
        cwd=_PROJECT_ROOT,
        env=os.environ.copy(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )

    def kill_server() -> None:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

    atexit.register(kill_server)

    try:
        if not _wait_for_server(base_url):
            print("Server did not become ready in time.", file=sys.stderr)
            kill_server()
            return 1
    except KeyboardInterrupt:
        kill_server()
        return 130

    print("API is ready. Opening chat.\n")
    # Run the chat client in this process so we can clean up the server on exit
    sys.argv = ["demo_chat", "--base-url", base_url]
    from demo.demo_chat import main as chat_main

    return chat_main()


if __name__ == "__main__":
    sys.exit(main())
