#!/usr/bin/env bash
# Point this repo at versioned hooks under scripts/git-hooks/
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
if ! git rev-parse --git-dir >/dev/null 2>&1; then
  echo "Not a git repository: $ROOT" >&2
  exit 1
fi
chmod +x scripts/git-hooks/pre-commit scripts/commit-and-push.sh 2>/dev/null || true
git config core.hooksPath scripts/git-hooks
echo "Installed: core.hooksPath=scripts/git-hooks"
echo "pre-commit will run: python3 scripts/review_staged_for_commit.py"
