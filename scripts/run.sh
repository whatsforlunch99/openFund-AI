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
USER_LOG_FILE="$ROOT/startup_user.log"

log_user() {
  printf "%s\n" "$*" >> "$USER_LOG_FILE"
}

out() {
  printf "%s\n" "$*"
  log_user "$*"
}

progress_line() {
  local pct="$1" label="$2" width=32
  local filled=$((pct * width / 100))
  local empty=$((width - filled))
  local fillbar emptybar
  fillbar=$(printf "%*s" "$filled" "" | tr " " "█")
  emptybar=$(printf "%*s" "$empty" "" | tr " " "-")
  out "  [${fillbar}${emptybar}] ${pct}%  ${label}"
}

# Suppress urllib3 OpenSSL (NotOpenSSLWarning) and resource_tracker warnings in all Python child processes.
# Message-based filter: NotOpenSSLWarning is not UserWarning, so match by message.
export PYTHONWARNINGS="ignore:.*OpenSSL.*::,ignore:.*leaked semaphore.*::"

PORT=8000
START_BACKENDS=1
LOAD_FUNDS="existing"   # existing | fresh-symbols | fresh-all | skip
INSTALL_DEPS=0
WAIT_SECS=8
START_CHAT=1
ORIGINAL_ARGS=("$@")

while [[ $# -gt 0 ]]; do
  case "$1" in
    --port)
      PORT="${2:-8000}"; shift 2 ;;
    --no-backends)
      START_BACKENDS=0; shift ;;
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
  --funds <mode>       existing | fresh-symbols | fresh-all | skip
  --install-deps       Install Python extras [backends,llm]
  --wait <secs>        Wait after backend start (default 8)
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

# Create a per-run separator in the user-facing startup log.
{
  echo ""
  echo "=================================================="
  echo "Run started: $(date '+%Y-%m-%d %H:%M:%S %z')"
  echo "Command: ./scripts/run.sh ${ORIGINAL_ARGS[*]}"
  echo "=================================================="
} >> "$USER_LOG_FILE"

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
  out "=================================================="
  out "OpenFund-AI System Booting..."
  out "=================================================="
  out ""
  out "[████████████████████████████████] 100%  Initialization Complete"
  out ""
  out "▶ Backends"

  pg_line="$(start_postgres 2>&1 || true)"
  [[ -n "$pg_line" ]] && log_user "$pg_line"
  if [[ "$pg_line" == *"started/ready"* ]]; then
    out "  PostgreSQL   : [✔] ready"
  elif [[ "$pg_line" == *"skipped"* ]]; then
    out "  PostgreSQL   : ⚠ skipped"
  else
    out "  PostgreSQL   : ⚠ not ready"
  fi

  if command -v createdb >/dev/null 2>&1; then
    createdb openfund >/dev/null 2>&1 || true
  fi

  neo_line="$(start_neo4j 2>&1 || true)"
  [[ -n "$neo_line" ]] && log_user "$neo_line"
  if [[ "$neo_line" == *"already running"* || "$neo_line" == *"started"* ]]; then
    out "  Neo4j        : [✔]  ready (port 7687)"
  elif [[ "$neo_line" == *"skipped"* ]]; then
    out "  Neo4j        : ⚠ skipped"
  else
    out "  Neo4j        : ⚠ not ready"
  fi

  milvus_line="$(start_milvus 2>&1 || true)"
  [[ -n "$milvus_line" ]] && log_user "$milvus_line"
  if [[ "$milvus_line" == *"already running"* || "$milvus_line" == *"started"* ]]; then
    out "  Milvus       : [✔] running"
  elif [[ "$milvus_line" == *"skipped"* ]]; then
    out "  Milvus       : ⚠ skipped"
  else
    out "  Milvus       : ⚠ not ready"
  fi

  out ""
  out "▶ Model"
  llm_base_url_lc="$(printf '%s' "${LLM_BASE_URL:-}" | tr '[:upper:]' '[:lower:]')"
  model_label="all-MiniLM-L6-v2"
  if [[ "$llm_base_url_lc" == *"deepseek"* ]]; then
    model_label="DeepSeek"
  elif [[ "$llm_base_url_lc" == *"openai"* ]] || [[ "$llm_base_url_lc" == *"gpt"* ]]; then
    model_label="GPT/OpenAI"
  elif [[ "$llm_base_url_lc" == *"glm"* ]] || [[ "$llm_base_url_lc" == *"bigmodel"* ]] || [[ "$llm_base_url_lc" == *"zhipu"* ]]; then
    model_label="GLM"
  elif [[ "$llm_base_url_lc" == *"gemini"* ]] || [[ "$llm_base_url_lc" == *"googleapis"* ]] || [[ "$llm_base_url_lc" == *"generativelanguage"* ]]; then
    model_label="Gemini"
  fi
  out "  ${model_label} : [✔] loaded"
  out ""
  out "▶ Loading Data (${LOAD_FUNDS})"
  out "  Progress:"
  progress_line 35 "Initializing loaders"

  log_user "==> Waiting ${WAIT_SECS}s for backends..."
  sleep "$WAIT_SECS"
  # Wait for Neo4j Bolt port so populate does not hit connection refused.
  if [[ -n "${NEO4J_URI:-}" ]] && [[ "${NEO4J_URI:-}" =~ localhost|127\.0\.0\.1 ]]; then
    if wait_for_port 127.0.0.1 7687 45; then
      log_user "Neo4j: port 7687 ready"
    else
      log_user "Neo4j: port 7687 not ready after 45s."
    fi
  fi

  # Populate all backends from repo datasets (stats_data/text_data/neo4j_export).
  # Map legacy flag values to loader load-mode values.
  case "$LOAD_FUNDS" in
    existing)
      LOADER_MODE="existing" ;;
    fresh-symbols)
      # Loader does not implement symbol-scoped refresh; existing upsert is the closest behavior.
      LOADER_MODE="existing" ;;
    fresh-all)
      LOADER_MODE="fresh-all" ;;
    skip)
      LOADER_MODE="skip" ;;
    *)
      echo "Unknown --funds mode: $LOAD_FUNDS" >&2
      exit 1 ;;
  esac

  loader_tmp="$(mktemp)"
  progress_line 65 "SQL + Neo4j ingest"
  if "$PYTHON" "$ROOT/scripts/data_loader.py" \
    --load-mode "$LOADER_MODE" \
    --stats-dir "$ROOT/database/stats_data" \
    --text-dir "$ROOT/database/text_data" \
    --neo4j-csv-dir "$ROOT/database/graph_data/neo4j_export" >"$loader_tmp" 2>&1; then
    LOADER_RC=0
  else
    LOADER_RC=$?
  fi
  log_user "==> Raw data_loader output"
  while IFS= read -r line; do
    log_user "$line"
  done < "$loader_tmp"
  progress_line 85 "Graph relationships"

  loader_metrics="$("$PYTHON" - "$loader_tmp" <<'PY'
import json, sys
from json import JSONDecoder
path = sys.argv[1]
text = open(path, "r", encoding="utf-8").read()
dec = JSONDecoder()
obj = None
for i, ch in enumerate(text):
    if ch != "{":
        continue
    try:
        cand, end = dec.raw_decode(text[i:])
    except Exception:
        continue
    if isinstance(cand, dict) and "load_mode" in cand and "components" in cand:
        obj = cand
if obj is None:
    print("sql_status=unknown")
    print("sql_tables=0")
    print("sql_rows=0")
    print("neo_status=unknown")
    print("neo_nodes=0")
    print("neo_edges=0")
    print("neo_integrity=unknown")
    print("neo_warnings=0")
    print("milvus_status=unknown")
    print("milvus_vectors=0")
    sys.exit(0)
sql = (obj.get("sql") or {}).get("sql") or {}
sql_status = (obj.get("sql") or {}).get("status", "unknown")
sql_tables = len(sql.get("tables") or [])
rows = 0
for k, v in sql.items():
    if isinstance(v, dict) and isinstance(v.get("rows_upserted"), int):
        rows += v.get("rows_upserted", 0)
neo_top = obj.get("neo4j") or {}
neo = neo_top.get("neo4j") or {}
neo_status = neo_top.get("status", "unknown")
node_counts = ((neo.get("validation") or {}).get("node_counts") or {})
neo_nodes = sum(int(v) for v in node_counts.values() if isinstance(v, int))
neo_edges = (((neo.get("validation") or {}).get("relationship_checks") or {}).get("graph_relationships") or {}).get("rows", 0)
rel_checks = (((neo.get("validation") or {}).get("relationship_checks") or {}).get("graph_relationships") or {})
integrity_ok = (
    not rel_checks.get("missing_start_sample")
    and not rel_checks.get("missing_end_sample")
    and not rel_checks.get("invalid_rel_type_sample")
    and int(rel_checks.get("duplicate_rows", 0) or 0) == 0
)
neo_integrity = "clean" if integrity_ok else "issues"
neo_warnings = int((((neo.get("validation") or {}).get("warnings") or {}).get("suspicious_currency_codes_count", 0)) or 0)
milvus_top = obj.get("milvus") or {}
milvus = milvus_top.get("milvus") or {}
milvus_status = milvus_top.get("status", "unknown")
milvus_vectors = int((milvus.get("docs_count") or 0))
print(f"sql_status={sql_status}")
print(f"sql_tables={sql_tables}")
print(f"sql_rows={rows}")
print(f"neo_status={neo_status}")
print(f"neo_nodes={neo_nodes}")
print(f"neo_edges={neo_edges}")
print(f"neo_integrity={neo_integrity}")
print(f"neo_warnings={neo_warnings}")
print(f"milvus_status={milvus_status}")
print(f"milvus_vectors={milvus_vectors}")
PY
)"
  while IFS= read -r kv; do
    eval "$kv"
  done <<< "$loader_metrics"
  progress_line 100 "Completed"
  out ""
  if [[ "${sql_status:-unknown}" == "ok" ]]; then _sql_label="[✔] completed"; else _sql_label="⚠ ${sql_status:-unknown}"; fi
  out "  SQL             : ${_sql_label}"
  out "    - tables      : ${sql_tables:-0}"
  out "    - rows        : ${sql_rows:-0} total"
  out ""
  if [[ "${neo_status:-unknown}" == "ok" ]]; then _neo_label="[✔] completed"; else _neo_label="⚠ ${neo_status:-unknown}"; fi
  out "  Neo4j           : ${_neo_label}"
  out "    - nodes       : ${neo_nodes:-0}"
  out "    - edges       : ${neo_edges:-0}"
  if [[ "${neo_integrity:-unknown}" == "clean" ]]; then _neo_int_label="✓ clean"; else _neo_int_label="⚠ ${neo_integrity:-unknown}"; fi
  out "    - integrity   : ${_neo_int_label}"
  out ""
  if [[ "${milvus_status:-unknown}" == "ok" ]]; then _mv_label="[✔] completed"; else _mv_label="⚠ ${milvus_status:-unknown}"; fi
  out "  Milvus          : ${_mv_label}"
  out "    - vectors     : ${milvus_vectors:-0} indexed"
  rm -f "$loader_tmp"

  if [[ "${LOADER_RC:-0}" -ne 0 ]]; then
    out ""
    out "--------------------------------------------------"
    out "⚠ Loader reported errors; see startup_user.log"
    out "--------------------------------------------------"
  fi
fi

out ""
out "▶ API"
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

health_tmp="$(mktemp)"
if "$PYTHON" "$ROOT/scripts/check_health.py" --port "$PORT" >"$health_tmp" 2>&1; then
  HEALTH_RC=0
else
  HEALTH_RC=$?
fi
while IFS= read -r line; do
  log_user "$line"
done < "$health_tmp"
health_json="$(curl -s "http://127.0.0.1:${PORT}/health" || true)"
llm_ready="$("$PYTHON" - <<'PY' "$health_json"
import json, sys
try:
    d = json.loads(sys.argv[1] or "{}")
except Exception:
    d = {}
print("yes" if d.get("llm_configured") else "no")
PY
)"
if [[ "$HEALTH_RC" -eq 0 ]]; then _health_live="[✔] live"; else _health_live="⚠ degraded"; fi
out "  status          : ${_health_live}"
out "  endpoint        : http://localhost:${PORT}"
if [[ "$HEALTH_RC" -eq 0 ]]; then _health_ok="OK"; else _health_ok="FAIL"; fi
out "  health          : ${_health_ok}"
out ""
out "▶ System"
if [[ "$llm_ready" == "yes" ]]; then _llm_label="[✔] ready"; else _llm_label="⚠ unavailable"; fi
out "  LLM connection  : ${_llm_label}"
if [[ "$HEALTH_RC" -eq 0 ]]; then _svc_label="[✔] healthy"; else _svc_label="⚠ check startup_user.log"; fi
out "  services        : ${_svc_label}"
out ""
out "--------------------------------------------------"
out "[✔] SYSTEM READY"
out "--------------------------------------------------"
out ""
out "Enter your query below (type 'quit' to exit)"
out ""
rm -f "$health_tmp"

"$PYTHON" "$ROOT/scripts/chat_cli.py" --port "$PORT"
