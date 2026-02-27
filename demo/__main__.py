"""Single-command demo: start API in demo mode and run the chat client.

Usage:
  python -m demo

Starts the API server in the background, waits for it to be ready, then runs
the interactive chat. When you type quit/exit, the server is stopped.
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
    base_url = "http://localhost:8000"
    if "--base-url" in sys.argv:
        i = sys.argv.index("--base-url")
        if i + 1 < len(sys.argv):
            base_url = sys.argv[i + 1].rstrip("/")

    env = os.environ.copy()
    env["OPENFUND_DEMO"] = "1"

    print("Starting API in demo mode...")
    proc = subprocess.Popen(
        [sys.executable, "main.py", "--demo"],
        cwd=_PROJECT_ROOT,
        env=env,
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
