#!/usr/bin/env bash
#
# OpenFund-AI: Start backend services (PostgreSQL, Neo4j, Milvus).
#
# Run from project root:  ./scripts/start_services.sh
# Or:  bash scripts/start_services.sh
#
# Uses Homebrew services and Docker. Loads .env from project root to decide
# which hosts/ports to check. Waits a few seconds then reports status.
#
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

# Ensure PATH includes Homebrew
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

# Load .env if present (for DATABASE_URL, NEO4J_URI, MILVUS_URI)
if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$ROOT/.env"
  set +a
fi

echo "==> OpenFund-AI: starting backend services"
echo ""

# --- PostgreSQL ---
_start_postgres() {
  for name in postgresql@16 postgresql@15 postgresql@14 postgresql; do
    if brew list "$name" &>/dev/null; then
      brew services start "$name" 2>/dev/null && return 0
    fi
  done
  return 1
}

if [[ -n "${DATABASE_URL:-}" ]] && [[ "$DATABASE_URL" =~ localhost|127\.0\.0\.1 ]]; then
  echo -n "PostgreSQL: "
  if _start_postgres; then
    echo "started (brew services)"
  else
    echo "could not start (install with: brew install postgresql@16)"
  fi
else
  echo "PostgreSQL: skipped (DATABASE_URL not set or not localhost)"
fi

# --- Neo4j ---
echo -n "Neo4j: "
if [[ -z "${NEO4J_URI:-}" ]] || [[ ! "$NEO4J_URI" =~ localhost|127\.0\.0\.1 ]]; then
  echo "skipped (NEO4J_URI not set or not localhost)"
elif command -v neo4j &>/dev/null; then
  (neo4j start 2>/dev/null || brew services start neo4j 2>/dev/null) && echo "started" || echo "start failed"
elif brew list neo4j &>/dev/null 2>&1; then
  brew services start neo4j 2>/dev/null && echo "started (brew services)" || echo "start failed"
else
  echo "not installed (brew install neo4j)"
fi

# --- Milvus (Docker) ---
echo -n "Milvus: "
if [[ -n "${MILVUS_URI:-}" ]] && [[ "$MILVUS_URI" =~ localhost|127\.0\.0\.1 ]]; then
  if command -v docker &>/dev/null; then
    if docker start milvus-standalone 2>/dev/null; then
      echo "started (docker start milvus-standalone)"
    elif [[ -f "$SCRIPT_DIR/start_milvus.sh" ]]; then
      bash "$SCRIPT_DIR/start_milvus.sh" && echo "started (standalone with embed etcd)" || echo "start failed (see script)"
    else
      echo "could not start (run: ./scripts/start_milvus.sh)"
    fi
  else
    echo "Docker not found; skip or install Docker Desktop"
  fi
else
  echo "skipped (MILVUS_URI not set or not localhost)"
fi

echo ""
echo "==> Waiting 5s for services to accept connections..."
sleep 5

# Optional: run Python checker for clear status
if [[ -f "$ROOT/scripts/start_backends.py" ]]; then
  echo "==> Status:"
  python3 "$ROOT/scripts/start_backends.py" --check-only 2>/dev/null || true
fi

echo ""
echo "==> Next: python -m data populate   then   python -m demo   (optional: python -m demo --ensure-data)"
echo ""
