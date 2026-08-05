#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"

RUN_ID="${1:-monitor_$(date -u +%Y%m%d_%H%M%S)}"
DURATION="${2:-60}"
INTERVAL="${3:-5}"
MODE="${4:-full}"
OUTPUT_DIR="${PROJECT_DIR}/dev/monitoring/data/${RUN_ID}"

[[ "$RUN_ID" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || {
    printf 'RUN_ID invalide : utiliser uniquement lettres, chiffres, point, tiret et underscore.\n' >&2
    exit 2
}

[[ "$MODE" == full || "$MODE" == lightweight ]] || {
    printf 'Le mode doit être "full" ou "lightweight".\n' >&2
    exit 2
}

for value in "$DURATION" "$INTERVAL"; do
    [[ "$value" =~ ^[1-9][0-9]*$ ]] || {
        printf 'La durée et l’intervalle doivent être des entiers positifs.\n' >&2
        exit 2
    }
done

mkdir -p "$OUTPUT_DIR"
printf '%s\n' "$RUN_ID" > "${PROJECT_DIR}/dev/monitoring/data/LATEST"

START_EPOCH="$(date +%s)"
SEQUENCE=0
while (( $(date +%s) - START_EPOCH < DURATION )); do
    SEQUENCE=$((SEQUENCE + 1))
    printf -v SNAPSHOT 'snapshot_%04d.json' "$SEQUENCE"
    COLLECT_ARGS=(
        --label "$RUN_ID"
        --output "${OUTPUT_DIR}/${SNAPSHOT}"
    )
    [[ "$MODE" == lightweight ]] && COLLECT_ARGS+=(--lightweight)
    python3 "${SCRIPT_DIR}/collect-platform-metrics.py" \
        "${COLLECT_ARGS[@]}" >/dev/null
    sleep "$INTERVAL"
done

python3 "${SCRIPT_DIR}/summarize-monitoring.py" \
    --input "$OUTPUT_DIR" \
    --output "${OUTPUT_DIR}/summary.json"

printf 'Supervision terminée : %s\n' "$OUTPUT_DIR"
