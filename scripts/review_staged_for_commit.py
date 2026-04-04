#!/usr/bin/env python3
"""Review staged files before git commit: block secrets, cohesion hints, ruff on staged .py.

Run by pre-commit hook (see scripts/git-hooks/pre-commit). For AI-assisted cohesion/coupling
review, use Cursor rule: .cursor/rules/git-commit-cohesion-review.mdc
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from collections import Counter


def _staged_paths() -> list[str]:
    r = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]


def _forbidden_reason(path: str) -> str | None:
    """Return error message if path must not be committed, else None."""
    norm = path.replace("\\", "/")
    base = norm.split("/")[-1].lower()
    if base == ".env":
        return "Do not commit .env (secrets). Use .env.example for templates."
    # OpenSSH private key filenames (allow *.pub)
    _ssh_prefixes = ("id_rsa", "id_dsa", "id_ecdsa", "id_ed25519")
    if any(base.startswith(p) and not base.endswith(".pub") for p in _ssh_prefixes):
        return "Do not commit private SSH keys."
    if base.endswith(".pem"):
        risky = ("private", "privkey", "secret", "_key", "-key", "id_rsa", "id_ecdsa", "id_ed25519")
        if any(x in base for x in risky):
            return "Do not commit private .pem key material."
    low = norm.lower()
    if "aws_access_key" in low or "aws_secret" in low:
        return "Possible AWS credential filename; do not commit secrets."
    return None


def _cohesion_report(paths: list[str]) -> str:
    if not paths:
        return "(nothing staged)"
    roots = []
    for p in paths:
        parts = p.replace("\\", "/").split("/", 1)
        roots.append(parts[0] if parts[0] else ".")
    counts = Counter(roots)
    lines = ["Staged files by top-level area:"]
    for root, n in counts.most_common():
        lines.append(f"  {root}/  ({n} file(s))")
    distinct = len(counts)
    if distinct >= 5:
        lines.append(
            f"\nCohesion hint: {distinct} top-level areas — consider splitting into "
            "smaller commits if changes are unrelated."
        )
    elif distinct >= 3:
        lines.append(
            "\nCohesion hint: multiple areas — ensure each file belongs to the same logical change."
        )
    return "\n".join(lines)


_CHECKLIST = """
Cohesion / coupling checklist (apply in Cursor before committing if needed):
- Single responsibility: does each file change one concern? Split mixed refactors.
- High cohesion: related logic stays together; avoid scattering one feature across many modules.
- Low coupling: prefer small, explicit imports/APIs between packages (agents/util/openfund_mcp/api).
- No duplicate helpers: reuse util/* or existing patterns instead of copy-paste.
- Docs: if behavior changed, touch the owning doc per .cursor/rules/docs-structure.mdc
"""


def _run_ruff(paths: list[str]) -> int:
    py_files = [p for p in paths if p.endswith(".py")]
    if not py_files:
        return 0
    ruff = shutil.which("ruff")
    if not ruff:
        print("ruff not on PATH; skip lint (install: pip install '.[dev]').", file=sys.stderr)
        return 0
    r = subprocess.run([ruff, "check", *py_files])
    return int(r.returncode)


def main() -> int:
    p = argparse.ArgumentParser(description="Review staged git changes before commit.")
    p.add_argument(
        "--print-only",
        action="store_true",
        help="Print report only; do not run ruff or exit non-zero for cohesion hints.",
    )
    args = p.parse_args()

    try:
        paths = _staged_paths()
    except subprocess.CalledProcessError as e:
        print("git error:", e, file=sys.stderr)
        return 1

    if not paths:
        msg = "No staged files. Stage with git add before committing."
        if args.print_only:
            print(msg)
            return 0
        print(msg, file=sys.stderr)
        return 1

    errors: list[str] = []
    for path in paths:
        reason = _forbidden_reason(path)
        if reason:
            errors.append(f"  BLOCKED {path}: {reason}")

    print(_cohesion_report(paths))
    print(_CHECKLIST)

    if errors:
        print("\n".join(["", "Commit blocked:"] + errors), file=sys.stderr)
        return 1

    if args.print_only:
        return 0

    rc = _run_ruff(paths)
    if rc != 0:
        print("ruff check failed; fix issues or adjust staged files.", file=sys.stderr)
        return rc

    print("\nStaged review passed (secrets + ruff).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
