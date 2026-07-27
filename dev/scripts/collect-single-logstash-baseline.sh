#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
RUN_ID=${1:-baseline_$(date -u +%Y%m%d_%H%M%S)}
OUT_DIR="$ROOT_DIR/dev/tests/results/phase4/$RUN_ID"

mkdir -p "$OUT_DIR"
printf '%s\n' "$RUN_ID" > "$ROOT_DIR/dev/tests/results/phase4/LATEST"

cd "$ROOT_DIR"
date -u +'%Y-%m-%dT%H:%M:%SZ' > "$OUT_DIR/timestamp.txt"
docker compose --profile malcolm ps > "$OUT_DIR/compose_ps.txt"
docker stats --no-stream \
  --format '{{.Name}},{{.CPUPerc}},{{.MemUsage}},{{.NetIO}},{{.BlockIO}}' \
  $(docker ps --filter 'label=com.docker.compose.project=oculox' -q) \
  > "$OUT_DIR/docker_stats.csv"

docker exec oculox-logstash-1 \
  curl -s 'http://localhost:9600/_node/stats/pipelines?pretty' \
  > "$OUT_DIR/logstash_pipelines.json"
docker exec oculox-logstash-1 \
  curl -s 'http://localhost:9600/_node/stats/jvm?pretty' \
  > "$OUT_DIR/logstash_jvm.json"
docker exec oculox-logstash-1 sh -c \
  'du -sh /logstash-persistent-queue /usr/share/logstash/data/queue 2>/dev/null || true' \
  > "$OUT_DIR/logstash_queues.txt"

docker exec oculox-opensearch-1 \
  curl -K /var/local/curlrc/.opensearch.primary.curlrc -sk \
  'https://localhost:9200/_cluster/health?pretty' \
  > "$OUT_DIR/opensearch_health.json"
docker exec oculox-opensearch-1 \
  curl -K /var/local/curlrc/.opensearch.primary.curlrc -sk \
  'https://localhost:9200/_cat/indices?format=json&bytes=b' \
  > "$OUT_DIR/opensearch_indices.json"

free -b > "$OUT_DIR/host_memory.txt"
df -B1 . > "$OUT_DIR/host_disk.txt"

printf 'Baseline enregistrée dans %s\n' "$OUT_DIR"
