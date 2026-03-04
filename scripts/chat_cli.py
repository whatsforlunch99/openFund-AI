#!/usr/bin/env python3
"""Interactive chat CLI: prompts for input and POSTs to the running API /chat endpoint."""

from __future__ import annotations

import argparse
import getpass
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
LOGIN_TIMEOUT = 15


def login_or_register(base_url: str) -> str | None:
    """Prompt for username/password, call POST /login (and optionally POST /register). Return user_id or None for anonymous."""
    try:
        username = input("Username (or Enter for anonymous): ").strip()
    except EOFError:
        return None
    if not username:
        return None
    try:
        password = getpass.getpass("Password: ")
    except EOFError:
        return None
    try:
        resp = requests.post(
            f"{base_url}/login",
            json={"username": username, "password": password},
            timeout=LOGIN_TIMEOUT,
        )
    except requests.exceptions.ConnectionError:
        print("[Error] Could not connect to the API. Continuing as anonymous.")
        return None
    except requests.exceptions.Timeout:
        print("[Error] Login request timed out. Continuing as anonymous.")
        return None
    except requests.exceptions.RequestException as e:
        print(f"[Error] {e}. Continuing as anonymous.")
        return None
    data = resp.json() if resp.content else {}
    if resp.status_code == 200:
        return data.get("user_id") or username
    if resp.status_code == 401:
        try:
            reg = input("Invalid credentials. Register? (y/n): ").strip().lower()
        except EOFError:
            return None
        if reg != "y":
            return None
        if len(password) < 8:
            try:
                password = getpass.getpass("Password (min 8 characters): ")
            except EOFError:
                return None
            if len(password) < 8:
                print("[Error] Password must be at least 8 characters. Continuing as anonymous.")
                return None
        try:
            rresp = requests.post(
                f"{base_url}/register",
                json={"username": username, "password": password, "display_name": username},
                timeout=LOGIN_TIMEOUT,
            )
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            print("[Error] Could not connect to the API. Continuing as anonymous.")
            return None
        rdata = rresp.json() if rresp.content else {}
        if rresp.status_code == 200:
            return rdata.get("user_id") or username
        if rresp.status_code == 409:
            print(f"[Error] Username '{username}' is already taken. Continuing as anonymous.")
            return None
        print("[Error]", rdata.get("detail", rresp.text or "Registration failed. Continuing as anonymous."))
        return None
    return None


def run(port: int, profile: str, skip_login: bool = False) -> None:
    base = f"http://127.0.0.1:{port}"
    conversation_id: str | None = None
    user_id: str | None = None
    print(f"Connected to API on port {port}. Type your query and press Enter (quit to exit).")
    if not skip_login:
        user_id = login_or_register(base)
        if user_id:
            print(f"Logged in as {user_id}.")
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
        if user_id:
            body["user_id"] = user_id
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
    parser.add_argument(
        "--no-login",
        action="store_true",
        help="Skip login prompt and run as anonymous",
    )
    args = parser.parse_args()
    run(args.port, args.profile, skip_login=args.no_login)


if __name__ == "__main__":
    main()
