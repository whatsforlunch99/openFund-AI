#!/usr/bin/env bash
#
# Start Milvus standalone in Docker with embedded etcd (no separate etcd/MinIO).
# The default "docker run milvusdb/milvus:latest" does NOT start the server;
# this script runs the image with "milvus run standalone" and required config.
#
# Run from project root:  ./scripts/start_milvus.sh
# Requires: Docker. Ports 19530 (gRPC) and 9091 (health) will be bound.
#
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
MILVUS_DIR="$SCRIPT_DIR/milvus"
VOLUMES_DIR="$ROOT/volumes/milvus"
IMAGE="${MILVUS_IMAGE:-milvusdb/milvus:v2.6.11}"
CONTAINER_NAME="milvus-standalone"

cd "$ROOT"

if ! command -v docker &>/dev/null; then
  echo "Docker not found. Install Docker Desktop or docker CLI."
  exit 1
fi

# Use existing container if already created
if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
  if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo "Milvus is already running (container ${CONTAINER_NAME})."
    echo "Connect at localhost:19530 (MILVUS_URI=http://localhost:19530)"
    exit 0
  fi
  echo "Starting existing container ${CONTAINER_NAME}..."
  docker start "$CONTAINER_NAME"
  echo "Wait ~30–60s for Milvus to be ready, then run: python -m data populate"
  exit 0
fi

# Ensure config files exist
if [[ ! -f "$MILVUS_DIR/embedEtcd.yaml" ]] || [[ ! -f "$MILVUS_DIR/user.yaml" ]]; then
  echo "Missing config in $MILVUS_DIR (embedEtcd.yaml, user.yaml)."
  exit 1
fi

mkdir -p "$VOLUMES_DIR"

echo "Starting Milvus standalone (embedded etcd, image: $IMAGE)..."
docker run -d \
  --name "$CONTAINER_NAME" \
  --security-opt seccomp=unconfined \
  -e ETCD_USE_EMBED=true \
  -e ETCD_DATA_DIR=/var/lib/milvus/etcd \
  -e ETCD_CONFIG_PATH=/milvus/configs/embedEtcd.yaml \
  -e COMMON_STORAGETYPE=local \
  -e DEPLOY_MODE=STANDALONE \
  -v "$VOLUMES_DIR:/var/lib/milvus" \
  -v "$MILVUS_DIR/embedEtcd.yaml:/milvus/configs/embedEtcd.yaml:ro" \
  -v "$MILVUS_DIR/user.yaml:/milvus/configs/user.yaml:ro" \
  -p 19530:19530 \
  -p 9091:9091 \
  "$IMAGE" \
  milvus run standalone 1>/dev/null

echo "Container started. Wait ~30–60 seconds for Milvus to be ready, then:"
echo "  python -m data populate"
echo "Connect with MILVUS_URI=http://localhost:19530"
