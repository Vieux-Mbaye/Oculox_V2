#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"
RUN_ID="${1:-phase10_$(date -u +%Y%m%d_%H%M%S)}"
EVENT_COUNT="${EVENT_COUNT:-50000}"
FILES="${FILES:-50}"

[[ "$RUN_ID" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || {
    printf 'RUN_ID invalide : utiliser uniquement lettres, chiffres, point, tiret et underscore.\n' >&2
    exit 2
}
[[ "$EVENT_COUNT" =~ ^[1-9][0-9]*$ && "$FILES" =~ ^[1-9][0-9]*$ ]] || {
    printf 'EVENT_COUNT et FILES doivent être des entiers strictement positifs.\n' >&2
    exit 2
}

EVENTS_PER_FILE=$((EVENT_COUNT / FILES))
RESULT_DIR="${PROJECT_DIR}/dev/tests/results/phase10/${RUN_ID}"
RESULTS="${RESULT_DIR}/comparison.tsv"

[[ $((EVENTS_PER_FILE * FILES)) -eq "$EVENT_COUNT" ]] || {
    printf 'EVENT_COUNT doit être divisible par FILES.\n' >&2
    exit 2
}

cd "$PROJECT_DIR"
mkdir -p "$RESULT_DIR"
printf 'mode\tevents_expected\tevents_indexed\telapsed_seconds\tthroughput_docs_s\tlogstash_1_events\tlogstash_2_events\topensearch_status\tstatus\n' > "$RESULTS"

compose_dual() {
    docker compose --project-directory "$PROJECT_DIR" \
        -f "$PROJECT_DIR/docker-compose.yml" \
        -f "$PROJECT_DIR/dev/compose/docker-compose.dev.yml" "$@"
}

health() {
    docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$1" 2>/dev/null || true
}

wait_healthy() {
    local container="$1" timeout="${2:-300}" elapsed=0
    while (( elapsed < timeout )); do
        [[ "$(health "$container")" == healthy ]] && return 0
        sleep 3
        elapsed=$((elapsed + 3))
    done
    printf 'Délai dépassé pour %s.\n' "$container" >&2
    return 1
}

wait_green() {
    local timeout="${1:-300}" elapsed=0 status
    while (( elapsed < timeout )); do
        status="$(docker exec oculox-opensearch-1 curl \
            -K /var/local/curlrc/.opensearch.primary.curlrc -sk \
            https://localhost:9200/_cluster/health 2>/dev/null | jq -r '.status // empty')"
        [[ "$status" == green ]] && return 0
        sleep 3
        elapsed=$((elapsed + 3))
    done
    return 1
}

count_marker() {
    local marker="$1"
    docker exec oculox-opensearch-1 curl \
        -K /var/local/curlrc/.opensearch.primary.curlrc -sk \
        'https://localhost:9200/arkime_sessions3-*/_count' \
        -H 'Content-Type: application/json' \
        -d "{\"query\":{\"query_string\":{\"query\":\"${marker}*\"}}}" \
        2>/dev/null | jq -r '.count // 0'
}

pipeline_in() {
    local container="$1"
    if ! docker inspect "$container" >/dev/null 2>&1; then
        printf '0\n'
        return
    fi
    docker exec "$container" curl -fsS \
        http://127.0.0.1:9600/_node/stats/pipelines/malcolm-input \
        2>/dev/null | jq -r '.pipelines["malcolm-input"].events.in // 0'
}

generate_files() {
    local marker="$1" sequence
    for sequence in $(seq -w 1 "$FILES"); do
        python3 dev/tests/generate-phase6-events.py \
            --output "zeek-logs/current/conn.log" \
            --marker "${marker}-${sequence}" \
            --count "$EVENTS_PER_FILE" \
            --append >/dev/null
    done
}

run_mode() {
    local mode="$1" marker="P10-${1}-${RUN_ID}" mode_dir="${RESULT_DIR}/${1}"
    local before_1=0 before_2=0 after_1=0 after_2=0 indexed=0
    local start_ns end_ns elapsed throughput os_status status=PASS monitor_pid

    mkdir -p "$mode_dir"
    compose_dual --profile malcolm down > "${mode_dir}/compose-down.log" 2>&1
    ./dev/scripts/platform-mode.sh "${mode}-ingest" > "${mode_dir}/startup.log" 2>&1
    wait_healthy oculox-opensearch-1
    wait_healthy oculox-logstash-1
    if [[ "$mode" == dual ]]; then
        wait_healthy oculox-logstash-2-1
    fi
    wait_healthy oculox-filebeat-1
    wait_green

    if [[ "$mode" == single ]] && docker ps --format '{{.Names}}' | grep -qx 'oculox-logstash-2-1'; then
        printf 'Le mode simple contient encore logstash-2.\n' >&2
        return 1
    fi

    # Filebeat est recréé après que toutes ses destinations soient disponibles.
    if [[ "$mode" == dual ]]; then
        compose_dual restart filebeat > "${mode_dir}/filebeat-restart.log" 2>&1
        wait_healthy oculox-filebeat-1
    fi
    sleep 5

    python3 dev/scripts/collect-platform-metrics.py \
        --label "${RUN_ID}-${mode}-before" \
        --output "${mode_dir}/before.json" >/dev/null

    before_1="$(pipeline_in oculox-logstash-1)"
    [[ "$mode" == dual ]] && before_2="$(pipeline_in oculox-logstash-2-1)"

    ./dev/scripts/monitor-platform.sh "phase10_${RUN_ID}_${mode}" 75 5 lightweight \
        > "${mode_dir}/monitor.log" 2>&1 &
    monitor_pid=$!

    start_ns="$(date +%s%N)"
    generate_files "$marker"
    for _ in $(seq 1 200); do
        indexed="$(count_marker "$marker")"
        [[ "$indexed" -eq "$EVENT_COUNT" ]] && break
        sleep 2
    done
    end_ns="$(date +%s%N)"

    wait "$monitor_pid"
    cp "dev/monitoring/data/phase10_${RUN_ID}_${mode}/summary.json" \
        "${mode_dir}/monitoring-summary.json"

    after_1="$(pipeline_in oculox-logstash-1)"
    [[ "$mode" == dual ]] && after_2="$(pipeline_in oculox-logstash-2-1)"
    os_status="$(docker exec oculox-opensearch-1 curl \
        -K /var/local/curlrc/.opensearch.primary.curlrc -sk \
        https://localhost:9200/_cluster/health | jq -r '.status')"

    elapsed="$(awk -v start="$start_ns" -v end="$end_ns" 'BEGIN {printf "%.3f", (end-start)/1000000000}')"
    throughput="$(awk -v count="$EVENT_COUNT" -v seconds="$elapsed" 'BEGIN {printf "%.2f", count/seconds}')"
    [[ "$indexed" -eq "$EVENT_COUNT" && "$os_status" == green ]] || status=FAIL

    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
        "$mode" "$EVENT_COUNT" "$indexed" "$elapsed" "$throughput" \
        "$((after_1-before_1))" "$((after_2-before_2))" "$os_status" "$status" \
        | tee -a "$RESULTS"

    python3 dev/scripts/collect-platform-metrics.py \
        --label "${RUN_ID}-${mode}-after" \
        --output "${mode_dir}/after.json" >/dev/null
}

printf 'run_id=%s\nstart_utc=%s\nevent_count=%s\nfiles=%s\nevents_per_file=%s\n' \
    "$RUN_ID" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$EVENT_COUNT" "$FILES" "$EVENTS_PER_FILE" \
    > "${RESULT_DIR}/metadata.txt"

run_mode single
run_mode dual

printf 'end_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "${RESULT_DIR}/metadata.txt"
awk -F '\t' 'NR == 2 {single=$5} NR == 3 {dual=$5} END {printf "single_docs_s=%s\ndual_docs_s=%s\ngain_percent=%.2f\n", single, dual, ((dual-single)/single)*100}' \
    "$RESULTS" > "${RESULT_DIR}/comparison-summary.txt"

if awk -F '\t' 'NR > 1 && $9 != "PASS" {failed=1} END {exit failed}' "$RESULTS"; then
    printf 'PHASE10_RESULT=PASS\n' >> "${RESULT_DIR}/metadata.txt"
else
    printf 'PHASE10_RESULT=FAIL\n' >> "${RESULT_DIR}/metadata.txt"
    exit 1
fi

printf 'Résultats : %s\n' "$RESULT_DIR"
