#!/usr/bin/env bash
#
# OpenFund-AI: Install backend services and Python dependencies for new users.
#
# Run from project root:  ./scripts/install_backends.sh
# Or:  bash scripts/install_backends.sh
#
# Installs (when possible):
#   - Homebrew (macOS, if missing)
#   - PostgreSQL (Homebrew)
#   - Neo4j (Homebrew)
#   - Docker (prompts user on macOS; optional for Milvus)
#   - Python package [backends]: psycopg2-binary, neo4j, pymilvus, sentence-transformers
#   - .env from .env.example if .env does not exist
#
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

echo "==> OpenFund-AI backend installation (project root: $ROOT)"
echo ""

# --- Homebrew (macOS) ---
if [[ "$(uname -s)" == "Darwin" ]]; then
  if ! command -v brew &>/dev/null; then
    echo "==> Installing Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    # Add to PATH for this session (Apple Silicon)
    [[ -x /opt/homebrew/bin/brew ]] && eval "$(/opt/homebrew/bin/brew shellenv)"
    [[ -x /usr/local/bin/brew ]] && eval "$(/usr/local/bin/brew shellenv)"
  else
    echo "==> Homebrew already installed."
  fi
  BREW_PREFIX="${HOMEBREW_PREFIX:-$(brew --prefix 2>/dev/null || echo /usr/local)}"
  export PATH="$BREW_PREFIX/bin:$PATH"
fi

# --- PostgreSQL ---
echo ""
echo "==> PostgreSQL"
if command -v brew &>/dev/null; then
  for pkg in postgresql@16 postgresql@15 postgresql@14 postgresql; do
    if brew list "$pkg" &>/dev/null; then
      echo "    Already installed: $pkg"
      break
    fi
    if brew install "$pkg" 2>/dev/null; then
      echo "    Installed: $pkg"
      break
    fi
  done
else
  echo "    Skipped (Homebrew not available). Install PostgreSQL manually."
fi

# --- Neo4j ---
echo ""
echo "==> Neo4j"
if command -v brew &>/dev/null; then
  if brew list neo4j &>/dev/null; then
    echo "    Already installed: neo4j"
  elif brew install neo4j; then
    echo "    Installed: neo4j"
  else
    echo "    Install failed or skipped. Try manually: brew install neo4j"
  fi
else
  echo "    Skipped (Homebrew not available). Install Neo4j manually."
fi

# --- Docker (Milvus) ---
echo ""
echo "==> Docker (optional, for Milvus)"
if command -v docker &>/dev/null; then
  if docker info &>/dev/null; then
    echo "    Docker is installed and running."
  else
    echo "    Docker is installed but not running. Start Docker Desktop (or run: open -a Docker)."
  fi
else
  echo "    Docker not found. For Milvus vector search:"
  echo "    - macOS: install Docker Desktop from https://docs.docker.com/desktop/install/mac-install/"
  echo "    - Or skip Milvus and use demo mode with static data."
fi

# --- Python venv and backends ---
echo ""
echo "==> Python backend dependencies"
if [[ ! -d ".venv" ]]; then
  echo "    Creating .venv..."
  python3 -m venv .venv
fi
echo "    Activating .venv and installing [backends]..."
# shellcheck source=/dev/null
source .venv/bin/activate
pip install -e ".[backends]" --quiet
echo "    Installed: psycopg2-binary, neo4j, pymilvus, sentence-transformers"

# --- .env ---
echo ""
echo "==> .env"
if [[ -f ".env" ]]; then
  echo "    .env already exists; not overwriting."
else
  if [[ -f ".env.example" ]]; then
    cp .env.example .env
    echo "    Created .env from .env.example. Edit .env and set:"
    echo "      DATABASE_URL=postgresql://USER:PASSWORD@localhost:5432/openfund"
    echo "      NEO4J_URI=bolt://localhost:7687  NEO4J_USER=neo4j  NEO4J_PASSWORD=..."
    echo "      MILVUS_URI=http://localhost:19530"
  else
    echo "    No .env.example found; create .env manually."
  fi
fi

echo ""
echo "==> Done. Next steps:"
echo "    1. Edit .env with your database passwords and URLs."
echo "    2. Start services:  ./scripts/start_services.sh"
echo "    3. Seed demo data:  python -m data populate"
echo "    4. Run demo:        python -m demo   (optional: python -m demo --ensure-data)"
echo ""
