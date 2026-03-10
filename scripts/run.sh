#!/usr/bin/env bash
# OpenFund-AI single entrypoint (live system only).
#
# Usage:
#   ./scripts/run.sh
#   ./scripts/run.sh --port 8010 --no-backends
#   ./scripts/run.sh --funds fresh-all
#   ./scripts/run.sh --install-deps
#   ./scripts/run.sh --no-chat   # API only, no interactive chat
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Suppress urllib3 OpenSSL (NotOpenSSLWarning) and resource_tracker warnings in all Python child processes.
# Message-based filter: NotOpenSSLWarning is not UserWarning, so match by message.
export PYTHONWARNINGS="ignore:.*OpenSSL.*::,ignore:.*leaked semaphore.*::"

PORT=8000
START_BACKENDS=1
SEED_DEMO=1
LOAD_FUNDS="existing"   # existing | fresh-symbols | fresh-all | skip
INSTALL_DEPS=0
WAIT_SECS=8
START_CHAT=1

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
    --no-chat)
      START_CHAT=0; shift ;;
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
  --no-chat            Start API only; do not launch interactive chat client
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
  if command -v neo4j &>/dev/null; then
    if neo4j status &>/dev/null; then
      echo "Neo4j: already running"
      return
    fi
    neo4j start >/dev/null 2>&1 || brew services start neo4j >/dev/null 2>&1 || true
    if neo4j status &>/dev/null; then
      echo "Neo4j: started"
    else
      echo "Neo4j: start requested (if port 7687 never opens, run 'neo4j console' in another terminal to avoid launchd; or use Neo4j Desktop)" >&2
    fi
  elif brew services list 2>/dev/null | grep -q neo4j; then
    brew services start neo4j >/dev/null 2>&1 || true
    echo "Neo4j: start requested via brew (if you see 'Bootstrap failed: 5', run 'neo4j console' in another terminal instead)" >&2
  else
    echo "Neo4j: not found (install with 'brew install neo4j' or use Neo4j Desktop; unset NEO4J_URI to skip)" >&2
  fi
}

# Wait for a TCP port to accept connections. Returns 0 when ready, 1 on timeout.
wait_for_port() {
  local host="${1:-127.0.0.1}" port="$2" max_secs="${3:-60}" t=0
  while [[ $t -lt "$max_secs" ]]; do
    if (python3 -c "
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(2)
try:
    s.connect(('$host', $port))
    s.close()
    exit(0)
except Exception:
    exit(1)
" 2>/dev/null); then
      return 0
    fi
    sleep 2
    t=$((t + 2))
  done
  return 1
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
    # Try to start; if mounts are stale (e.g. scripts/milvus/embedEtcd.yaml dir-vs-file), start fails. Then remove and create fresh.
    if ! docker start milvus-standalone; then
      docker rm -f milvus-standalone >/dev/null 2>&1 || true
      echo "Milvus: removed container with invalid mounts; creating new one..."
    else
      echo "Milvus: started existing container"
      return
    fi
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
  # Wait for Neo4j Bolt port so populate does not hit connection refused.
  if [[ -n "${NEO4J_URI:-}" ]] && [[ "${NEO4J_URI:-}" =~ localhost|127\.0\.0\.1 ]]; then
    if wait_for_port 127.0.0.1 7687 45; then
      echo "Neo4j: port 7687 ready"
    else
      echo "Neo4j: port 7687 not ready after 45s. If Neo4j says already running, remove stale pid: 'rm -f \$(find /opt/homebrew -name neo4j.pid 2>/dev/null)' then run 'neo4j console' and wait for 'Bolt enabled'. Or unset NEO4J_URI in .env to skip." >&2
    fi
  fi
fi

if command -v createdb >/dev/null 2>&1; then
  createdb openfund >/dev/null 2>&1 || true
fi

if [[ $SEED_DEMO -eq 1 ]]; then
  echo "==> Seeding backend demo baseline"
  "$PYTHON" -m data_manager populate || true
fi

if [[ "$LOAD_FUNDS" != "skip" ]] && [[ -f "$ROOT/datasets/combined_funds.json" ]]; then
  # When --funds existing and backend already has fund data, skip loading to avoid redundant work.
  SKIP_FUND_LOAD=0
  if [[ "$LOAD_FUNDS" == "existing" ]] && [[ -n "${DATABASE_URL:-}" ]]; then
    if "$PYTHON" -c "
import os, sys
try:
    import psycopg2
    conn = psycopg2.connect(os.environ.get('DATABASE_URL'))
    cur = conn.cursor()
    cur.execute('SELECT 1 FROM fund_info LIMIT 1')
    if cur.fetchone():
        sys.exit(0)
    sys.exit(1)
except Exception:
    sys.exit(2)
" 2>/dev/null; then
      SKIP_FUND_LOAD=1
    fi
  fi
  if [[ $SKIP_FUND_LOAD -eq 1 ]]; then
    echo "==> Skipping fund load (backend already has fund data)"
  else
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
fi

echo "==> Starting live API on port ${PORT}"
if [[ $START_CHAT -eq 0 ]]; then
  exec "$PYTHON" main.py --serve --port "$PORT"
fi

# Start API in background, then run interactive chat client; on exit, kill server.
API_PID=""
cleanup() {
  if [[ -n "$API_PID" ]] && kill -0 "$API_PID" 2>/dev/null; then
    kill "$API_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

"$PYTHON" main.py --serve --port "$PORT" &
API_PID=$!

# Wait for server to be ready (FastAPI serves /openapi.json)
for i in $(seq 1 15); do
  if curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:${PORT}/openapi.json" 2>/dev/null | grep -q 200; then
    break
  fi
  if [[ $i -eq 15 ]]; then
    echo "API did not become ready in time" >&2
    exit 1
  fi
  sleep 1
done

echo "==> Checking API and LLM..."
"$PYTHON" "$ROOT/scripts/check_health.py" --port "$PORT"

"$PYTHON" "$ROOT/scripts/chat_cli.py" --port "$PORT"
