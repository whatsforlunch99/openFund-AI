#!/usr/bin/env bash
# Load .env from project root into the current shell.
# Usage: source scripts/load-env.sh   (or: . scripts/load-env.sh)
if [[ -f ".env" ]]; then
  set -a
  source .env
  set +a
  echo "Loaded .env from $(pwd)"
elif [[ -f "${BASH_SOURCE[0]}" ]]; then
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
  if [[ -f "$ROOT/.env" ]]; then
    set -a
    source "$ROOT/.env"
    set +a
    echo "Loaded .env from $ROOT"
  else
    echo "No .env found at $ROOT" >&2
  fi
else
  echo "No .env in $(pwd) and could not resolve script dir" >&2
fi
