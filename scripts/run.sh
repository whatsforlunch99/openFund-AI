#!/usr/bin/env bash
# OpenFund-AI single entrypoint (live system only).
#
# Usage:
#   ./scripts/run.sh
#   ./scripts/run.sh --port 8010 --no-backends
#   ./scripts/run.sh --funds fresh-all
#   ./scripts/run.sh --install-deps
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PORT=8000
START_BACKENDS=1
SEED_DEMO=1
LOAD_FUNDS="existing"   # existing | fresh-symbols | fresh-all | skip
INSTALL_DEPS=0
WAIT_SECS=8

while [[ $# -gt 0 ]]; do
  case "$1" in
    --port)
      PORT="${2:-8000}"; shift 2 ;;
    --no-backends)
      START_BACKENDS=0; shift ;;
    --no-seed)
      SEED_DEMO=0; shift ;;
    --funds)
      LOAD_FUNDS="${2:-existing}"; shift 2 ;;
    --install-deps)
      INSTALL_DEPS=1; shift ;;
    --wait)
      WAIT_SECS="${2:-8}"; shift 2 ;;
    -h|--help)
      cat <<'EOF'
OpenFund-AI single runner

Options:
  --port <n>           API port (default 8000)
  --no-backends        Skip starting Postgres/Neo4j/Milvus
  --no-seed            Skip `python -m data_manager populate`
  --funds <mode>       existing | fresh-symbols | fresh-all | skip
  --install-deps       Install Python extras [backends,llm]
  --wait <secs>        Wait after backend start before seed (default 8)
EOF
      exit 0 ;;
    *)
      echo "Unknown option: $1" >&2
      exit 1 ;;
  esac
done

export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

if [[ -f "$ROOT/.venv/bin/activate" ]]; then
  # shellcheck source=/dev/null
  source "$ROOT/.venv/bin/activate"
fi

# Resolve interpreter after optional venv activation so PYTHON points at active env.
if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PYTHON="$ROOT/.venv/bin/python"
else
  # Prefer python3 so script works when python is not in PATH (e.g. macOS)
  PYTHON=$(command -v python3 2>/dev/null || command -v python 2>/dev/null)
  [[ -n "$PYTHON" ]] || PYTHON=python3
fi

if [[ ! -f "$ROOT/.env" ]]; then
  if [[ -f "$ROOT/.env.example" ]]; then
    cp "$ROOT/.env.example" "$ROOT/.env"
    echo "Created .env from .env.example at $ROOT/.env"
    echo "Edit .env (LLM_API_KEY is required) then re-run ./scripts/run.sh"
    exit 0
  else
    echo "Missing .env and .env.example" >&2
    exit 1
  fi
fi

set -a
# shellcheck source=/dev/null
source "$ROOT/.env"
set +a

if [[ $INSTALL_DEPS -eq 1 ]]; then
  if [[ ! -d "$ROOT/.venv" ]]; then
    python3 -m venv "$ROOT/.venv"
    # shellcheck source=/dev/null
    source "$ROOT/.venv/bin/activate"
  fi
  pip install -e ".[backends,llm]"
fi

start_postgres() {
  if [[ -z "${DATABASE_URL:-}" ]] || [[ ! "${DATABASE_URL:-}" =~ localhost|127\.0\.0\.1 ]]; then
    echo "PostgreSQL: skipped"
    return
  fi
  for name in postgresql@16 postgresql@15 postgresql@14 postgresql; do
    if brew list "$name" &>/dev/null; then
      brew services start "$name" >/dev/null 2>&1 || true
      echo "PostgreSQL: started/ready via brew ($name)"
      return
    fi
  done
  echo "PostgreSQL: brew package not found" >&2
}

start_neo4j() {
  if [[ -z "${NEO4J_URI:-}" ]] || [[ ! "${NEO4J_URI:-}" =~ localhost|127\.0\.0\.1 ]]; then
    echo "Neo4j: skipped"
    return
  fi
  (neo4j start >/dev/null 2>&1 || brew services start neo4j >/dev/null 2>&1 || true)
  echo "Neo4j: started/ready"
}

start_milvus() {
  if [[ -z "${MILVUS_URI:-}" ]] || [[ ! "${MILVUS_URI:-}" =~ localhost|127\.0\.0\.1 ]]; then
    echo "Milvus: skipped"
    return
  fi
  if ! command -v docker >/dev/null 2>&1; then
    echo "Milvus: docker not found" >&2
    return
  fi

  if docker ps --format '{{.Names}}' | grep -q '^milvus-standalone$'; then
    echo "Milvus: already running"
    return
  fi

  if docker ps -a --format '{{.Names}}' | grep -q '^milvus-standalone$'; then
    docker start milvus-standalone >/dev/null
    echo "Milvus: started existing container"
    return
  fi

  cfg_dir="$ROOT/.tmp_milvus_cfg"
  mkdir -p "$cfg_dir"
  cat > "$cfg_dir/embedEtcd.yaml" <<'YAML'
etcd:
  data:
    dir: /var/lib/milvus/etcd
YAML
  cat > "$cfg_dir/user.yaml" <<'YAML'
common:
  storageType: local
YAML

  mkdir -p "$ROOT/volumes/milvus"
  docker run -d \
    --name milvus-standalone \
    --security-opt seccomp=unconfined \
    -e ETCD_USE_EMBED=true \
    -e ETCD_DATA_DIR=/var/lib/milvus/etcd \
    -e ETCD_CONFIG_PATH=/milvus/configs/embedEtcd.yaml \
    -e COMMON_STORAGETYPE=local \
    -e DEPLOY_MODE=STANDALONE \
    -v "$ROOT/volumes/milvus:/var/lib/milvus" \
    -v "$cfg_dir/embedEtcd.yaml:/milvus/configs/embedEtcd.yaml:ro" \
    -v "$cfg_dir/user.yaml:/milvus/configs/user.yaml:ro" \
    -p 19530:19530 \
    -p 9091:9091 \
    milvusdb/milvus:v2.6.11 \
    milvus run standalone >/dev/null
  echo "Milvus: started new container"
}

if [[ $START_BACKENDS -eq 1 ]]; then
  echo "==> Starting configured local backends"
  start_postgres
  start_neo4j
  start_milvus
  echo "==> Waiting ${WAIT_SECS}s for backends..."
  sleep "$WAIT_SECS"
fi

if command -v createdb >/dev/null 2>&1; then
  createdb openfund >/dev/null 2>&1 || true
fi

if [[ $SEED_DEMO -eq 1 ]]; then
  echo "==> Seeding backend demo baseline"
  "$PYTHON" -m data_manager populate || true
fi

if [[ "$LOAD_FUNDS" != "skip" ]] && [[ -f "$ROOT/datasets/combined_funds.json" ]]; then
  echo "==> Loading fund dataset (${LOAD_FUNDS})"
  case "$LOAD_FUNDS" in
    existing)
      "$PYTHON" -m data_manager distribute-funds --file "$ROOT/datasets/combined_funds.json" --load-mode existing || true ;;
    fresh-symbols)
      "$PYTHON" -m data_manager distribute-funds --file "$ROOT/datasets/combined_funds.json" --load-mode fresh --fresh-scope symbols || true ;;
    fresh-all)
      "$PYTHON" -m data_manager distribute-funds --file "$ROOT/datasets/combined_funds.json" --load-mode fresh --fresh-scope all || true ;;
    *)
      echo "Unknown --funds mode: $LOAD_FUNDS" >&2
      exit 1 ;;
  esac
fi

echo "==> Starting live API on port ${PORT}"
exec "$PYTHON" main.py --serve --port "$PORT"
