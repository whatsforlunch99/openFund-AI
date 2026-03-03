#!/usr/bin/env python3
"""Interactive chat CLI: prompts for input and POSTs to the running API /chat endpoint."""

import argparse
import warnings

warnings.filterwarnings(
    "ignore",
    message=".*urllib3 v2 only supports OpenSSL",
    category=UserWarning,
    module="urllib3",
)

import requests

VALID_PROFILES = ("beginner", "long_term", "analyst")
DEFAULT_PORT = 8000
REQUEST_TIMEOUT = 120


def run(port: int, profile: str) -> None:
    base = f"http://127.0.0.1:{port}"
    conversation_id: str | None = None
    print(f"Connected to API on port {port}. Type your query and press Enter (quit to exit).")
    print()
    while True:
        try:
            line = input("You: ").strip()
        except EOFError:
            print()
            break
        if not line:
            continue
        if line.lower() in ("quit", "exit", "q"):
            break
        body = {"query": line, "user_profile": profile}
        if conversation_id:
            body["conversation_id"] = conversation_id
        try:
            resp = requests.post(
                f"{base}/chat",
                json=body,
                timeout=REQUEST_TIMEOUT,
            )
        except requests.exceptions.ConnectionError:
            print("Assistant: [Error] Could not connect to the API. Is the server running?")
            continue
        except requests.exceptions.Timeout:
            print("Assistant: [Error] Request timed out.")
            continue
        except requests.exceptions.RequestException as e:
            print(f"Assistant: [Error] {e}")
            continue
        try:
            data = resp.json() if resp.content else {}
        except Exception:
            data = {}
        if resp.status_code == 200:
            conversation_id = data.get("conversation_id") or conversation_id
            text = data.get("response") or ""
            print("Assistant:", text)
        elif resp.status_code == 408:
            conversation_id = data.get("conversation_id") or conversation_id
            print("Assistant: [Timeout] The request took too long. You can try again.")
        elif resp.status_code in (400, 422, 404, 500):
            detail = data.get("detail", resp.text or "Unknown error")
            if isinstance(detail, list):
                detail = "; ".join(str(d) for d in detail)
            print("Assistant: [Error]", detail)
        else:
            print("Assistant: [Error]", resp.status_code, (resp.text[:200] if resp.text else ""))
    print("Goodbye.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Interactive chat client for OpenFund-AI API.")
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"API port (default {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--profile",
        choices=VALID_PROFILES,
        default="beginner",
        help="User profile (default beginner)",
    )
    args = parser.parse_args()
    run(args.port, args.profile)


if __name__ == "__main__":
    main()
