#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"
RUN_ID="${1:-phase9_$(date -u +%Y%m%d_%H%M%S)}"
RESULT_DIR="${PROJECT_DIR}/dev/tests/results/phase9/${RUN_ID}"
RESULTS="${RESULT_DIR}/results.tsv"

[[ "$RUN_ID" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || {
    printf 'RUN_ID invalide : utiliser uniquement lettres, chiffres, point, tiret et underscore.\n' >&2
    exit 2
}

cd "$PROJECT_DIR"
mkdir -p "$RESULT_DIR"
printf 'test\texpected\tactual\tstatus\tnote\n' > "$RESULTS"

compose() {
    docker compose --project-directory "$PROJECT_DIR" \
        -f "$PROJECT_DIR/docker-compose.yml" \
        -f "$PROJECT_DIR/dev/compose/docker-compose.dev.yml" \
        --profile malcolm "$@"
}

record() {
    printf '%s\t%s\t%s\t%s\t%s\n' "$1" "$2" "$3" "$4" "$5" | tee -a "$RESULTS"
}

container_health() {
    docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$1" 2>/dev/null || true
}

wait_container() {
    local name="$1" timeout="${2:-240}" elapsed=0 state
    while (( elapsed < timeout )); do
        state="$(container_health "$name")"
        [[ "$state" == "healthy" ]] && return 0
        sleep 3
        elapsed=$((elapsed + 3))
    done
    printf 'Délai dépassé pour %s, état=%s\n' "$name" "$state" >&2
    return 1
}

wait_opensearch() {
    local timeout="${1:-240}" elapsed=0 status
    while (( elapsed < timeout )); do
        status="$(docker exec oculox-opensearch-1 curl \
            -K /var/local/curlrc/.opensearch.primary.curlrc -sk \
            https://localhost:9200/_cluster/health 2>/dev/null | jq -r '.status // empty')"
        [[ "$status" == "green" ]] && return 0
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

wait_count() {
    local marker="$1" expected="$2" timeout="${3:-240}" elapsed=0 actual=0
    while (( elapsed < timeout )); do
        actual="$(count_marker "$marker")"
        [[ "$actual" -eq "$expected" ]] && {
            printf '%s\n' "$actual"
            return 0
        }
        sleep 3
        elapsed=$((elapsed + 3))
    done
    printf '%s\n' "$actual"
    return 1
}

generate() {
    local marker="$1" count="$2"
    python3 dev/tests/generate-phase6-events.py \
        --output "zeek-logs/current/conn.log" \
        --marker "$marker" --count "$count" --append >/dev/null
}

generate_files() {
    local marker="$1" files="$2" events_per_file="$3" sequence
    for sequence in $(seq -w 1 "$files"); do
        generate "${marker}-${sequence}" "$events_per_file"
        # Des ajouts espacés forcent plusieurs lots de publication sans créer
        # de nouveaux noms de jeux de données Zeek dans OpenSearch.
        sleep 1
    done
}

pipeline_in() {
    local container="$1"
    docker exec "$container" curl -fsS \
        http://127.0.0.1:9600/_node/stats/pipelines/malcolm-input \
        2>/dev/null | jq -r '.pipelines["malcolm-input"].events.in // 0'
}

queue_total() {
    local total=0 container
    for container in oculox-logstash-1 oculox-logstash-2-1; do
        if docker inspect "$container" >/dev/null 2>&1; then
            value="$(docker exec "$container" curl -fsS \
                http://127.0.0.1:9600/_node/stats/pipelines 2>/dev/null |
                jq '[.pipelines[].queue.events_count // 0] | add // 0' || printf '0')"
            total=$((total + value))
        fi
    done
    printf '%s\n' "$total"
}

assert_count() {
    local test="$1" marker="$2" expected="$3" note="$4" actual status
    if actual="$(wait_count "$marker" "$expected")"; then status=PASS; else status=FAIL; fi
    record "$test" "$expected" "$actual" "$status" "$note"
    [[ "$status" == PASS ]]
}

printf 'run_id=%s\nstart_utc=%s\n' "$RUN_ID" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "${RESULT_DIR}/metadata.txt"
# A previous manual test may have left one destination stopped. Recreating the
# four reduced-stack containers makes the campaign deterministic while keeping
# all named volumes intact.
compose down > "${RESULT_DIR}/initial-compose-down.log" 2>&1
./dev/scripts/platform-mode.sh dual-ingest > "${RESULT_DIR}/startup.log" 2>&1
wait_container oculox-opensearch-1
wait_container oculox-logstash-1
wait_container oculox-logstash-2-1
wait_container oculox-filebeat-1
wait_opensearch
compose restart filebeat > "${RESULT_DIR}/initial-filebeat-restart.log" 2>&1
wait_container oculox-filebeat-1
sleep 5

# 1. Both Logstash nodes receive data.
MARKER="P9-NORMAL-${RUN_ID}"; COUNT=6000
L1_BEFORE="$(pipeline_in oculox-logstash-1)"; L2_BEFORE="$(pipeline_in oculox-logstash-2-1)"
generate "$MARKER" "$COUNT"
assert_count normal "$MARKER" "$COUNT" "two destinations active"
L1_AFTER="$(pipeline_in oculox-logstash-1)"; L2_AFTER="$(pipeline_in oculox-logstash-2-1)"
L1_DELTA=$((L1_AFTER - L1_BEFORE)); L2_DELTA=$((L2_AFTER - L2_BEFORE))
if (( L1_DELTA > 0 && L2_DELTA > 0 )); then status=PASS; else status=FAIL; fi
record distribution ">0 on each node" "logstash=${L1_DELTA};logstash-2=${L2_DELTA}" "$status" "Filebeat load balancing"

# 2. First destination unavailable.
compose stop logstash > "${RESULT_DIR}/stop-logstash-1.log" 2>&1
MARKER="P9-LS1-DOWN-${RUN_ID}"; COUNT=3000
generate "$MARKER" "$COUNT"
assert_count logstash_down "$MARKER" "$COUNT" "logstash-2 alone"

# 3. Second destination unavailable.
compose start logstash > "${RESULT_DIR}/start-logstash-1.log" 2>&1
wait_container oculox-logstash-1
compose stop logstash-2 > "${RESULT_DIR}/stop-logstash-2.log" 2>&1
MARKER="P9-LS2-DOWN-${RUN_ID}"; COUNT=3000
generate "$MARKER" "$COUNT"
assert_count logstash_2_down "$MARKER" "$COUNT" "logstash alone"

# 4. The returning node receives traffic again.
compose start logstash-2 > "${RESULT_DIR}/start-logstash-2.log" 2>&1
wait_container oculox-logstash-2-1
# Filebeat utilise un backoff exponentiel après l'échec d'une destination.
# On laisse expirer son backoff maximal avant de mesurer la réintégration.
sleep 70
MARKER="P9-RETURN-${RUN_ID}"; COUNT=20000
L1_BEFORE="$(pipeline_in oculox-logstash-1)"; L2_BEFORE="$(pipeline_in oculox-logstash-2-1)"
generate_files "$MARKER" 40 500
assert_count instance_return "$MARKER" "$COUNT" "automatic reintegration"
L1_AFTER="$(pipeline_in oculox-logstash-1)"; L2_AFTER="$(pipeline_in oculox-logstash-2-1)"
L1_DELTA=$((L1_AFTER - L1_BEFORE)); L2_DELTA=$((L2_AFTER - L2_BEFORE))
if (( L1_DELTA > 0 && L2_DELTA > 0 )); then status=PASS; else status=FAIL; fi
record redistribution ">0 on each node" "logstash=${L1_DELTA};logstash-2=${L2_DELTA}" "$status" "40 independent batches, no Filebeat restart"

# 5. OpenSearch outage fills persistent queues, then drains them.
compose stop opensearch > "${RESULT_DIR}/stop-opensearch.log" 2>&1
MARKER="P9-OS-DOWN-${RUN_ID}"; COUNT=5000
generate "$MARKER" "$COUNT"
sleep 20
QUEUED="$(queue_total)"
record opensearch_outage_queue ">0" "$QUEUED" "$([[ "$QUEUED" -gt 0 ]] && printf PASS || printf FAIL)" "events persisted on disk"
compose start opensearch > "${RESULT_DIR}/start-opensearch.log" 2>&1
wait_container oculox-opensearch-1
wait_opensearch
assert_count opensearch_recovery "$MARKER" "$COUNT" "queues replayed"

# 6. Filebeat restart while both destinations are down.
compose stop logstash logstash-2 > "${RESULT_DIR}/stop-both-logstash.log" 2>&1
MARKER="P9-FILEBEAT-RESTART-${RUN_ID}"; COUNT=4000
generate "$MARKER" "$COUNT"
sleep 8
compose restart filebeat > "${RESULT_DIR}/restart-filebeat.log" 2>&1
wait_container oculox-filebeat-1
compose start logstash logstash-2 > "${RESULT_DIR}/start-both-logstash.log" 2>&1
wait_container oculox-logstash-1
wait_container oculox-logstash-2-1
assert_count filebeat_registry_recovery "$MARKER" "$COUNT" "persistent registry"

# 7. Complete Compose restart without deleting volumes.
MARKER="P9-FULL-RESTART-${RUN_ID}"; COUNT=2000
generate "$MARKER" "$COUNT"
assert_count before_full_restart "$MARKER" "$COUNT" "reference data indexed"
docker volume ls --format '{{.Name}}' | grep -E '^oculox_(opensearch|filebeat|logstash-persistent-queue)' > "${RESULT_DIR}/volumes-before.txt"
compose down > "${RESULT_DIR}/compose-down.log" 2>&1
./dev/scripts/platform-mode.sh dual-ingest > "${RESULT_DIR}/compose-up.log" 2>&1
wait_container oculox-opensearch-1
wait_container oculox-logstash-1
wait_container oculox-logstash-2-1
wait_container oculox-filebeat-1
wait_opensearch
assert_count after_full_restart "$MARKER" "$COUNT" "OpenSearch volume retained"
./dev/scripts/check-beats-certificates.sh > "${RESULT_DIR}/tls-check.txt"
record tls_after_restart "success" "success" PASS "mutual TLS verified"

python3 dev/scripts/collect-platform-metrics.py \
    --label "$RUN_ID-final" --output "${RESULT_DIR}/final-state.json" >/dev/null
printf 'end_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "${RESULT_DIR}/metadata.txt"

if awk -F '\t' 'NR > 1 && $4 != "PASS" {failed=1} END {exit failed}' "$RESULTS"; then
    printf 'PHASE9_RESULT=PASS\n' | tee -a "${RESULT_DIR}/metadata.txt"
else
    printf 'PHASE9_RESULT=FAIL\n' | tee -a "${RESULT_DIR}/metadata.txt"
    exit 1
fi

printf 'Résultats : %s\n' "$RESULT_DIR"
