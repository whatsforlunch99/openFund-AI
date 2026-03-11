#!/usr/bin/env python3
"""Interactive chat CLI: prompts for input and POSTs to the running API /chat endpoint."""

from __future__ import annotations

import argparse
import getpass
import warnings

# NotOpenSSLWarning is not UserWarning; match by message.
warnings.filterwarnings("ignore", message=".*urllib3 v2 only supports OpenSSL.*")
warnings.filterwarnings("ignore", message=".*LibreSSL.*")

import requests

VALID_PROFILES = ("beginner", "long_term", "analyst")
DEFAULT_PORT = 8000
REQUEST_TIMEOUT = 120
LOGIN_TIMEOUT = 15
MAX_LOGIN_ATTEMPTS = 3


def login_or_register(base_url: str) -> str | None:
    """Prompt for username/password, call POST /login (and optionally POST /register). Return user_id or None for anonymous."""
    try:
        username = input("Username (or Enter for anonymous): ").strip()
    except EOFError:
        return None
    if not username:
        return None
    for attempt in range(1, MAX_LOGIN_ATTEMPTS + 1):
        try:
            password = getpass.getpass("Password: " if attempt == 1 else f"Invalid credentials. Try again (attempt {attempt}/{MAX_LOGIN_ATTEMPTS}): ")
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
        try:
            data = resp.json() if resp.content else {}
        except Exception:
            data = {"detail": resp.text[:500] if getattr(resp, "text", None) else "Invalid response"}
        if resp.status_code == 200:
            return data.get("user_id") or username
        if resp.status_code == 404:
            # User does not exist yet; offer to create an account so the same username
            # can be used going forward.
            print(f"User '{username}' not found.")
            try:
                choice = input("Create a new user with this name? (y/N): ").strip().lower()
            except EOFError:
                return None
            if choice not in ("y", "yes"):
                return None
            # Ask the user to set a password (with confirmation) before calling /register.
            while True:
                try:
                    pw1 = getpass.getpass("Set password (min 8 chars): ")
                    pw2 = getpass.getpass("Confirm password: ")
                except EOFError:
                    return None
                if pw1 != pw2:
                    print("Passwords do not match. Try again.")
                    continue
                if len(pw1.strip()) < 8:
                    print("Password must be at least 8 characters. Try again.")
                    continue
                password = pw1
                break
            try:
                reg = requests.post(
                    f"{base_url}/register",
                    json={"username": username, "display_name": username, "password": password},
                    timeout=LOGIN_TIMEOUT,
                )
            except requests.exceptions.RequestException as e:
                print(f"[Error] Failed to create user: {e}. Continuing as anonymous.")
                return None
            try:
                reg_data = reg.json() if reg.content else {}
            except Exception:
                reg_data = {"detail": reg.text[:500] if getattr(reg, "text", None) else "Invalid response"}
            if reg.status_code == 200:
                print(reg_data.get("message") or f"New user '{username}' created.")
                return reg_data.get("user_id") or username
            detail = reg_data.get("detail", reg.text or "Unknown error")
            print(f"[Error] Could not create user: {detail}. Continuing as anonymous.")
            return None
        if resp.status_code == 401:
            if attempt < MAX_LOGIN_ATTEMPTS:
                continue
            print("Too many failed attempts. Continuing as anonymous.")
            return None
        if resp.status_code >= 500:
            print("[Error] Server error:", data.get("detail", resp.text or "Unknown error"), "Continuing as anonymous.")
            return None
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
        except KeyboardInterrupt:
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
            print()
            print("You can ask a follow-up or type a new question (or 'quit' to exit).")
        elif resp.status_code == 408:
            conversation_id = data.get("conversation_id") or conversation_id
            msg = data.get("message") or "The request took too long. You can try again."
            print("Assistant: [Timeout]", msg)
            print("You can retry or ask something else (or 'quit' to exit).")
        elif resp.status_code in (400, 422, 404, 500):
            detail = data.get("detail", resp.text or "Unknown error")
            if isinstance(detail, list):
                detail = "; ".join(str(d) for d in detail)
            print("Assistant: [Error]", detail)
            print("You can try again or type 'quit' to exit.")
        else:
            print("Assistant: [Error]", resp.status_code, (resp.text[:200] if resp.text else ""))
            print("You can try again or type 'quit' to exit.")
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
