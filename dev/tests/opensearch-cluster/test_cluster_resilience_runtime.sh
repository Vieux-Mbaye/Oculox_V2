#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../../.." && pwd)"
ENV_FILE="${OPENSEARCH_CLUSTER_ENV_FILE:-$PROJECT_DIR/dev/config/opensearch-cluster/cluster.env.example}"
ACCOUNTS_ENV="${OPENSEARCH_ACCOUNTS_ENV:-$PROJECT_DIR/dev/generated/opensearch-cluster/security/accounts.env}"
CA_FILE="${OPENSEARCH_CA_FILE:-$PROJECT_DIR/dev/generated/opensearch-cluster/pki/client-trust/oculox-opensearch-ca.crt}"
COMPOSE_FILE="$PROJECT_DIR/dev/compose/opensearch-cluster/compose.yml"
INDEX="cluster-resilience-$(date -u +%Y%m%d%H%M%S)"
RESULT_DIR="${CLUSTER_RESILIENCE_RESULT_DIR:-$PROJECT_DIR/dev/generated/opensearch-cluster/cluster-resilience}"
RESULT_FILE="$RESULT_DIR/last-run.txt"
RECOVERY_REQUIRED=true

for file in "$ENV_FILE" "$ACCOUNTS_ENV" "$CA_FILE" "$COMPOSE_FILE"; do
  [[ -f "$file" ]] || { printf 'Required file not found: %s\n' "$file" >&2; exit 1; }
done

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
# shellcheck disable=SC1090
source "$ACCOUNTS_ENV"
set +a

ENDPOINT="${OPENSEARCH_CLUSTER_ENDPOINT:?missing OPENSEARCH_CLUSTER_ENDPOINT}"
auth=(--user "oculox_platform_admin:$OCULOX_PLATFORM_ADMIN_PASSWORD")
tls=(--cacert "$CA_FILE")
compose=(docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE")
nodes=(opensearch-1 opensearch-2 opensearch-3)

mkdir -p "$RESULT_DIR"
chmod 700 "$RESULT_DIR"
touch "$RESULT_FILE"
chmod 600 "$RESULT_FILE"
exec > >(tee "$RESULT_FILE") 2>&1

api() {
  local method="$1"
  local path="$2"
  local data="${3:-}"
  local args=(--silent --show-error --fail --max-time 30 "${tls[@]}" "${auth[@]}" --request "$method")
  if [[ -n "$data" ]]; then
    args+=(--header 'Content-Type: application/json' --data "$data")
  fi
  curl "${args[@]}" "$ENDPOINT$path"
}

api_status() {
  local method="$1"
  local path="$2"
  local data="${3:-}"
  local output_file="$4"
  local args=(--silent --show-error --max-time 12 --output "$output_file" --write-out '%{http_code}' "${tls[@]}" "${auth[@]}" --request "$method")
  if [[ -n "$data" ]]; then
    args+=(--header 'Content-Type: application/json' --data "$data")
  fi
  local status
  status="$(curl "${args[@]}" "$ENDPOINT$path" 2>/dev/null)" || true
  printf '%s' "${status:-000}"
}

wait_for_api() {
  local attempts="${1:-120}"
  for _ in $(seq 1 "$attempts"); do
    if api GET '/_cluster/health' >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  return 1
}

wait_for_green() {
  local response
  for _ in $(seq 1 150); do
    if response="$(api GET '/_cluster/health' 2>/dev/null)" && python3 -c '
import json, sys
d = json.load(sys.stdin)
assert d["status"] == "green", d
assert d["number_of_nodes"] == 3, d
assert d["unassigned_shards"] == 0, d
assert d["relocating_shards"] == 0, d
' <<<"$response" 2>/dev/null; then
      return 0
    fi
    sleep 2
  done
  printf 'Cluster did not reach green with all three nodes: %s\n' "${response:-unreachable}" >&2
  return 1
}

manager_name() {
  api GET '/_cat/master?format=json&h=node' | python3 -c '
import json, sys
rows = json.load(sys.stdin)
assert len(rows) == 1 and rows[0].get("node"), rows
print(rows[0]["node"])
'
}

document_count() {
  api GET "/$INDEX/_count" | python3 -c 'import json,sys; print(json.load(sys.stdin)["count"])'
}

cluster_uuid() {
  api GET '/' | python3 -c 'import json,sys; print(json.load(sys.stdin)["cluster_uuid"])'
}

recover() {
  local exit_code=$?
  set +e
  if [[ "$RECOVERY_REQUIRED" == true ]]; then
    printf 'Recovery: ensuring all Cluster resilience services are running...\n'
    "${compose[@]}" up -d >/dev/null 2>&1
    wait_for_api 120
    api DELETE "/$INDEX" >/dev/null 2>&1
  fi
  if ((exit_code != 0)); then
    printf 'CLUSTER_RESILIENCE_RESULT=FAIL exit=%s\n' "$exit_code"
  fi
  exit "$exit_code"
}
trap recover EXIT INT TERM

printf 'Cluster resilience index: %s\n' "$INDEX"
wait_for_green
initial_uuid="$(cluster_uuid)"
initial_manager="$(manager_name)"
printf 'initial_cluster_uuid=%s\n' "$initial_uuid"
printf 'initial_manager=%s\n' "$initial_manager"

# 1-4. Index, writes, reads/searches and distinct primary/replica placement.
api PUT "/$INDEX?wait_for_active_shards=all" '{"settings":{"number_of_shards":1,"number_of_replicas":1},"mappings":{"properties":{"sequence":{"type":"integer"},"message":{"type":"keyword"}}}}' >/dev/null
for sequence in 1 2 3; do
  api PUT "/$INDEX/_doc/$sequence?refresh=wait_for&wait_for_active_shards=all" \
    "{\"sequence\":$sequence,\"message\":\"resilience-initial-$sequence\"}" >/dev/null
done

api GET "/$INDEX/_doc/2" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["found"] and d["_source"]["sequence"] == 2, d'
api GET "/$INDEX/_search?q=message:resilience-initial-*&size=10" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["hits"]["total"]["value"] == 3, d'

shards="$(api GET "/_cat/shards/$INDEX?format=json&h=index,shard,prirep,state,node")"
read -r primary_node replica_node < <(python3 -c '
import json, sys
rows = json.load(sys.stdin)
p = [row["node"] for row in rows if row["prirep"] == "p" and row["state"] == "STARTED"]
r = [row["node"] for row in rows if row["prirep"] == "r" and row["state"] == "STARTED"]
assert len(p) == 1 and len(r) == 1 and p[0] != r[0], rows
print(p[0], r[0])
' <<<"$shards")
printf 'primary_node=%s replica_node=%s distinct=PASS\n' "$primary_node" "$replica_node"

# 5-6. Stop the primary holder; the replica must be promoted and accept writes.
printf 'Stopping primary data node: %s\n' "$primary_node"
"${compose[@]}" stop "$primary_node" >/dev/null
wait_for_api 60
api GET "/$INDEX/_doc/1" | python3 -c 'import json,sys; assert json.load(sys.stdin)["found"] is True'
api PUT "/$INDEX/_doc/4?refresh=wait_for" '{"sequence":4,"message":"written-during-data-node-loss"}' >/dev/null
[[ "$(document_count)" == "4" ]] || { printf 'Document count after data-node loss is not 4\n' >&2; exit 1; }
printf 'read_write_during_data_node_loss=PASS\n'

"${compose[@]}" start "$primary_node" >/dev/null
wait_for_api 120
wait_for_green
printf 'data_node_reintegration=PASS\n'

# 7-10. Stop the elected manager and prove a different node is elected.
old_manager="$(manager_name)"
printf 'Stopping elected cluster manager: %s\n' "$old_manager"
"${compose[@]}" stop "$old_manager" >/dev/null
new_manager=""
for _ in $(seq 1 90); do
  if candidate="$(manager_name 2>/dev/null)" && [[ -n "$candidate" && "$candidate" != "$old_manager" ]]; then
    new_manager="$candidate"
    break
  fi
  sleep 2
done
[[ -n "$new_manager" ]] || { printf 'No replacement cluster manager elected\n' >&2; exit 1; }
printf 'new_manager=%s election=PASS\n' "$new_manager"
api PUT "/$INDEX/_doc/5?refresh=wait_for" '{"sequence":5,"message":"written-after-manager-election"}' >/dev/null
[[ "$(document_count)" == "5" ]] || { printf 'Document count after manager election is not 5\n' >&2; exit 1; }

"${compose[@]}" start "$old_manager" >/dev/null
wait_for_api 120
wait_for_green
printf 'manager_reintegration_and_green=PASS\n'

# Expected quorum loss: stop the manager plus one other voter, leaving one node.
quorum_manager="$(manager_name)"
second_stopped=""
for node in "${nodes[@]}"; do
  if [[ "$node" != "$quorum_manager" ]]; then
    second_stopped="$node"
    break
  fi
done
printf 'Quorum test: stopping %s and %s\n' "$quorum_manager" "$second_stopped"
"${compose[@]}" stop "$quorum_manager" "$second_stopped" >/dev/null
sleep 12
quorum_body="$(mktemp)"
quorum_status="$(api_status GET '/_cluster/health' '' "$quorum_body")"
write_body="$(mktemp)"
write_status="$(api_status PUT "/$INDEX/_doc/quorum-test" '{"sequence":99,"message":"must-not-be-committed-without-quorum"}' "$write_body")"
printf 'quorum_health_http=%s write_http=%s\n' "$quorum_status" "$write_status"
if [[ "$quorum_status" =~ ^2 ]] || [[ "$write_status" =~ ^2 ]]; then
  printf 'Cluster unexpectedly accepted a quorum-dependent operation with one node\n' >&2
  cat "$quorum_body" "$write_body" >&2
  exit 1
fi
rm -f "$quorum_body" "$write_body"
printf 'two_node_loss_quorum_block=EXPECTED PASS\n'

"${compose[@]}" start "$quorum_manager" "$second_stopped" >/dev/null
wait_for_api 120
wait_for_green
[[ "$(document_count)" == "5" ]] || { printf 'Blocked quorum write was unexpectedly committed\n' >&2; exit 1; }
printf 'quorum_recovery_green=PASS\n'

# 11-12. Full Compose teardown/start must retain UUID and documents in volumes.
uuid_before_restart="$(cluster_uuid)"
count_before_restart="$(document_count)"
printf 'Full cluster restart (named volumes are preserved)...\n'
"${compose[@]}" down >/dev/null
"${compose[@]}" up -d >/dev/null
wait_for_api 150
wait_for_green
uuid_after_restart="$(cluster_uuid)"
count_after_restart="$(document_count)"
[[ "$uuid_after_restart" == "$uuid_before_restart" ]] || {
  printf 'cluster_uuid changed: %s -> %s\n' "$uuid_before_restart" "$uuid_after_restart" >&2
  exit 1
}
[[ "$count_after_restart" == "$count_before_restart" && "$count_after_restart" == "5" ]] || {
  printf 'Document count changed: %s -> %s\n' "$count_before_restart" "$count_after_restart" >&2
  exit 1
}
printf 'full_restart_cluster_uuid_preserved=PASS uuid=%s\n' "$uuid_after_restart"
printf 'full_restart_documents_preserved=PASS count=%s\n' "$count_after_restart"

api DELETE "/$INDEX" >/dev/null
wait_for_green
RECOVERY_REQUIRED=false
trap - EXIT INT TERM

printf 'index_creation=PASS\n'
printf 'document_write_read_search=PASS\n'
printf 'primary_replica_distinct_nodes=PASS\n'
printf 'data_node_failure_read_write=PASS\n'
printf 'cluster_manager_reelection=PASS\n'
printf 'node_reintegration_cluster_green=PASS\n'
printf 'two_node_quorum_loss=EXPECTED PASS\n'
printf 'complete_restart_persistence=PASS\n'
printf 'CLUSTER_RESILIENCE_RESULT=PASS\n'
