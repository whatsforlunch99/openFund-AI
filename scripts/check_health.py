#!/usr/bin/env python3
"""Check API health and LLM configuration before starting interactive chat.
Exits 0 only if GET /health returns 200 and llm_configured is true; otherwise prints an error and exits 1.
"""

import argparse
import sys
import warnings

# NotOpenSSLWarning is not UserWarning; match by message.
warnings.filterwarnings("ignore", message=".*urllib3 v2 only supports OpenSSL.*")
warnings.filterwarnings("ignore", message=".*LibreSSL.*")

import requests

DEFAULT_PORT = 8000
TIMEOUT = 10


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify API is up and LLM is configured (for run.sh before chat)."
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"API port (default {DEFAULT_PORT})",
    )
    args = parser.parse_args()
    url = f"http://127.0.0.1:{args.port}/health"

    try:
        resp = requests.get(url, timeout=TIMEOUT)
    except requests.exceptions.ConnectionError:
        print("API health check failed: could not connect to the API.", file=sys.stderr)
        return 1
    except requests.exceptions.Timeout:
        print("API health check failed: request timed out.", file=sys.stderr)
        return 1
    except requests.exceptions.RequestException as e:
        print(f"API health check failed: {e}", file=sys.stderr)
        return 1

    if resp.status_code != 200:
        print(
            f"API health check failed: GET /health returned {resp.status_code}.",
            file=sys.stderr,
        )
        return 1

    try:
        data = resp.json()
    except ValueError:
        print("API health check failed: invalid JSON from /health.", file=sys.stderr)
        return 1

    if not data.get("llm_configured"):
        print(
            "LLM is not configured. Set LLM_API_KEY in .env and run: pip install -e \".[llm]\".",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
