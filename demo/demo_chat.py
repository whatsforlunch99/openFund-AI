#!/usr/bin/env python3
"""Interactive CLI demo chat: set your name, then chat with the OpenFund-AI API.

Usage:
  # Start the API in demo mode first (in another terminal):
  #   python main.py --demo

  python -m demo.demo_chat
  python -m demo.demo_chat --base-url http://localhost:8000

The script prompts for your name, registers you, then lets you type questions.
Each response shows the system flow (planner, librarian, etc.) then the answer.
"""

from __future__ import annotations

import argparse
import sys

try:
    import requests
except ImportError:
    print("This script requires the 'requests' package. Run: pip install requests")
    sys.exit(1)

DEFAULT_BASE_URL = "http://localhost:8000"


def check_demo_mode(base_url: str) -> bool | None:
    """GET /demo; return True/False if server supports it, None on error."""
    url = f"{base_url.rstrip('/')}/demo"
    try:
        r = requests.get(url, timeout=5)
        if r.status_code != 200:
            return None
        return r.json().get("demo", False)
    except requests.RequestException:
        return None


def register(base_url: str, display_name: str) -> str | None:
    """POST /register with display_name; return user_id or None on error."""
    url = f"{base_url.rstrip('/')}/register"
    try:
        r = requests.post(url, json={"display_name": display_name}, timeout=10)
        r.raise_for_status()
        data = r.json()
        return data.get("user_id")
    except requests.RequestException as e:
        print(f"  Error: {e}")
        return None


def chat(
    base_url: str,
    query: str,
    user_id: str,
    conversation_id: str | None,
) -> dict | None:
    """POST /chat; return response dict (including on 408 timeout) or None on connection error."""
    url = f"{base_url.rstrip('/')}/chat"
    payload = {
        "query": query,
        "user_profile": "beginner",
        "user_id": user_id,
    }
    if conversation_id:
        payload["conversation_id"] = conversation_id
    try:
        r = requests.post(url, json=payload, timeout=90)
        if r.status_code == 408:
            return r.json()
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        print(f"  Error: {e}")
        return None


def main() -> int:
    """Run the interactive demo chat loop. Returns 0 on success, 1 on error."""
    parser = argparse.ArgumentParser(
        description="Interactive CLI demo chat. Start the API with: python main.py --demo"
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"API base URL (default: {DEFAULT_BASE_URL})",
    )
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")

    print()
    print("  ╭─────────────────────────────────────────────────────────────╮")
    print("  │  OpenFund-AI Demo Chat                                       │")
    print("  │  Make sure the API is running: python main.py --demo         │")
    print("  ╰─────────────────────────────────────────────────────────────╯")
    print()

    # Set name via interaction
    name_input = input("  Enter your name (or press Enter for Guest): ").strip()
    display_name = name_input if name_input else "Guest"
    print()
    print("  Registering...")
    user_id = register(base_url, display_name)
    if not user_id:
        print("  Could not register. Is the API running at", base_url, "?")
        return 1
    print(f"  New user created. Welcome, {display_name}! (user_id: {user_id})")
    demo = check_demo_mode(base_url)
    if demo is False:
        print()
        print("  ⚠ Server is NOT in demo mode — requests may be slow or time out.")
        print(
            "  For quick static answers, restart the API with:  python main.py --demo"
        )
        print()
    elif demo is True:
        print("  ✓ Demo mode: static data (answers in a few seconds)")
    print()

    conversation_id: str | None = None

    print(
        "  Ask a question (e.g. 'should I invest in Nvidia?'). Type 'quit' or 'exit' to leave."
    )
    print("  ─────────────────────────────────────────────────────────────")

    while True:
        try:
            prompt = "  You: "
            line = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        if line.lower() in ("quit", "exit", "q"):
            print("  Goodbye.")
            break

        print()
        print("  Thinking...")
        data = chat(base_url, line, user_id, conversation_id)
        if not data:
            print()
            continue

        conversation_id = data.get("conversation_id")
        flow = data.get("flow") or []
        response = data.get("response") or ""
        status = data.get("status", "")

        if flow:
            print("  ── Flow ──")
            for i, step in enumerate(flow):
                msg = step.get("message", "")
                if msg:
                    print(f"    • {msg}")
                if i < len(flow) - 1:
                    print()
            print("  ──────────")

        if response:
            print(f"  Assistant: {response}")
        elif status == "timeout":
            print("  Assistant: (Request timed out.)")
            print(
                "  Tip: Start the API with  python main.py --demo  for fast static answers."
            )
        else:
            print("  Assistant: (No response.)")
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
