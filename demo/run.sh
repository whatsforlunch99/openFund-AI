#!/usr/bin/env bash
#
# Single entry point to run the demo: ensures backends and data, then starts the demo.
# Run from project root:  ./demo/run.sh
# Or from anywhere:       bash /path/to/openFund\ AI/demo/run.sh
#
# First run: if .env is missing, creates it and runs install_backends.sh, then asks
# you to edit .env (NEO4J_PASSWORD, DATABASE_URL user) and run this script again.
# Subsequent runs: start services, create DB if needed, populate, then python -m demo.
#
set -e

DEMO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$DEMO_DIR/.." && pwd)"
cd "$ROOT"

export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
# Use project venv if present
if [[ -f "$ROOT/.venv/bin/activate" ]]; then
  set +e
  # shellcheck source=/dev/null
  source "$ROOT/.venv/bin/activate"
  set -e
fi

# --- Ensure .env and backends installed (first-time) ---
if [[ ! -f "$ROOT/.env" ]]; then
  echo "==> First-time setup: no .env found."
  if [[ -f "$ROOT/.env.example" ]]; then
    cp "$ROOT/.env.example" "$ROOT/.env"
    echo "    Created .env from .env.example."
  fi
  if [[ -f "$ROOT/scripts/install_backends.sh" ]]; then
    bash "$ROOT/scripts/install_backends.sh"
  else
    echo "    Copy .env.example to .env and set DATABASE_URL, NEO4J_*, MILVUS_URI."
  fi
  echo ""
  echo "==> Edit .env: set NEO4J_PASSWORD (and DATABASE_URL user to your Mac username if needed)."
  echo "    Then run again:  ./demo/run.sh"
  exit 0
fi

# Load .env for this script
set -a
# shellcheck source=/dev/null
[[ -f "$ROOT/.env" ]] && source "$ROOT/.env"
set +a

# --- Start backends ---
echo "==> Starting backend services..."
if [[ -f "$ROOT/scripts/start_services.sh" ]]; then
  bash "$ROOT/scripts/start_services.sh"
else
  echo "    scripts/start_services.sh not found; start Postgres, Neo4j, Milvus manually."
fi

# --- Create Postgres DB if needed ---
if [[ -f "$ROOT/scripts/create_db.sh" ]]; then
  bash "$ROOT/scripts/create_db.sh" 2>/dev/null || true
fi

# --- Seed demo data ---
echo "==> Seeding demo data..."
python -m data populate 2>/dev/null || {
  echo "    populate had errors (some backends may be optional). Continuing."
}

# --- Run demo ---
echo "==> Starting demo (API + chat)..."
exec python -m demo
