#!/usr/bin/env bash
# Stop local backends started by run.sh (PostgreSQL, Neo4j, Milvus).
#
# Usage:
#   ./scripts/stop.sh
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$ROOT/.env"
  set +a
fi

echo "==> Stopping local backends"

# PostgreSQL: stop brew service for first installed postgresql variant
pg_found=0
for name in postgresql@16 postgresql@15 postgresql@14 postgresql; do
  if brew list "$name" &>/dev/null; then
    brew services stop "$name" >/dev/null 2>&1 || true
    echo "PostgreSQL: stopped ($name)"
    pg_found=1
    break
  fi
done
if [[ $pg_found -eq 0 ]]; then
  echo "PostgreSQL: skipped (not installed)"
fi

# Neo4j: neo4j stop or brew services stop
if command -v neo4j &>/dev/null; then
  if neo4j stop 2>/dev/null; then
    echo "Neo4j: stopped"
  elif neo4j status &>/dev/null; then
    echo "Neo4j: stop failed (try 'sudo kill -9 \$(pgrep -f neo4j)' or get PID from 'neo4j console')" >&2
  else
    echo "Neo4j: skipped (not running)"
  fi
elif brew services list 2>/dev/null | grep -q neo4j; then
  brew services stop neo4j >/dev/null 2>&1 || true
  echo "Neo4j: stopped (brew)"
else
  echo "Neo4j: skipped (not found)"
fi

# Milvus: docker stop container
if command -v docker &>/dev/null 2>&1; then
  if docker ps -a --format '{{.Names}}' | grep -q '^milvus-standalone$'; then
    docker stop milvus-standalone >/dev/null 2>&1 || true
    echo "Milvus: stopped"
  else
    echo "Milvus: skipped (container not found)"
  fi
else
  echo "Milvus: skipped (docker not found)"
fi

echo "==> Done"
