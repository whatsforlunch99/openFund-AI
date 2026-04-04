#!/usr/bin/env bash
# Run full staged review explicitly, commit (pre-commit runs again), then push.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

python3 scripts/review_staged_for_commit.py

if [[ -z "$(git diff --cached --name-only)" ]]; then
  echo "Nothing staged. Use: git add ..." >&2
  exit 1
fi

git commit "$@"
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
read -r -p "Push branch '${BRANCH}' to origin? [y/N] " ans
ans_lc=$(printf '%s' "$ans" | tr '[:upper:]' '[:lower:]')
if [[ "$ans_lc" == "y" || "$ans_lc" == "yes" ]]; then
  git push -u origin "$BRANCH"
else
  echo "Skipped push. Run: git push -u origin $BRANCH"
fi
