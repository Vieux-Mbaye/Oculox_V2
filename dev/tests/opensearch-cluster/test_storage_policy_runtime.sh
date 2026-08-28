#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../../.." && pwd)"
ENV_FILE="${OPENSEARCH_CLUSTER_ENV_FILE:-$PROJECT_DIR/dev/config/opensearch-cluster/cluster.env.example}"
ACCOUNTS_ENV="${OPENSEARCH_ACCOUNTS_ENV:-$PROJECT_DIR/dev/generated/opensearch-cluster/security/accounts.env}"
CA_FILE="${OPENSEARCH_CA_FILE:-$PROJECT_DIR/dev/generated/opensearch-cluster/pki/client-trust/oculox-opensearch-ca.crt}"
COMPOSE_FILE="$PROJECT_DIR/dev/compose/opensearch-cluster/compose.yml"
APPLY_SCRIPT="$PROJECT_DIR/dev/scripts/opensearch-cluster/apply-storage-policy.py"

for file in "$ENV_FILE" "$ACCOUNTS_ENV" "$CA_FILE" "$COMPOSE_FILE" "$APPLY_SCRIPT"; do
  [[ -f "$file" ]] || { printf 'Required file not found: %s\n' "$file" >&2; exit 1; }
done

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
# shellcheck disable=SC1090
source "$ACCOUNTS_ENV"
set +a

ENDPOINT="${OPENSEARCH_CLUSTER_ENDPOINT:?missing endpoint}"
auth=(--user "oculox_platform_admin:$OCULOX_PLATFORM_ADMIN_PASSWORD")
tls=(--cacert "$CA_FILE")
compose=(docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE")
index="malcolm_beats_storage-test-$(date -u +%Y%m%d%H%M%S)"
stopped_service=""

api() {
  local method="$1"
  local path="$2"
  local data="${3:-}"
  local args=(--silent --show-error --fail "${tls[@]}" "${auth[@]}" --request "$method")
  if [[ -n "$data" ]]; then
    args+=(--header 'Content-Type: application/json' --data "$data")
  fi
  curl "${args[@]}" "$ENDPOINT$path"
}

cleanup() {
  if [[ -n "$stopped_service" ]]; then
    "${compose[@]}" start "$stopped_service" >/dev/null 2>&1 || true
    stopped_service=""
  fi
  api DELETE "/$index" >/dev/null 2>&1 || true
}
trap cleanup EXIT

"$APPLY_SCRIPT" --env-file "$ENV_FILE" --accounts-env "$ACCOUNTS_ENV" --ca-file "$CA_FILE"

api PUT "/$index" '{"settings":{"number_of_shards":1}}' >/dev/null
api POST "/$index/_doc/storage-test?refresh=true" '{"test":"storage-policy","replica_test":true}' >/dev/null

# A second application proves idempotency and attaches the policy immediately
# instead of waiting for the periodic ISM scheduler.
"$APPLY_SCRIPT" --env-file "$ENV_FILE" --accounts-env "$ACCOUNTS_ENV" --ca-file "$CA_FILE"

api GET '/_cluster/settings?flat_settings=true' | python3 -c '
import json, sys
p = json.load(sys.stdin)["persistent"]
assert p["cluster.default_number_of_replicas"] == "1"
assert p["cluster.routing.allocation.disk.threshold_enabled"] == "true"
assert p["cluster.routing.allocation.disk.watermark.low"] == "75%"
assert p["cluster.routing.allocation.disk.watermark.high"] == "85%"
assert p["cluster.routing.allocation.disk.watermark.flood_stage"] == "90%"
'

api GET '/_all/_settings?expand_wildcards=all' | python3 -c '
import json, sys
d = json.load(sys.stdin)
bad = {name: value["settings"]["index"].get("number_of_replicas") for name, value in d.items()
       if int(value["settings"]["index"].get("number_of_replicas", 1)) < 1}
assert not bad, bad
'

arkime_settings="$(api GET '/arkime_sessions3-*/_settings?flat_settings=true')"
if [[ "$arkime_settings" != "{}" ]]; then
  printf '%s' "$arkime_settings" | python3 -c '
import json, sys
d = json.load(sys.stdin)
for name, value in d.items():
    settings = value["settings"]
    assert settings["index.number_of_shards"] == "1", (name, settings)
    assert settings["index.number_of_replicas"] == "1", (name, settings)
    assert settings["index.max_docvalue_fields_search"] == "200", (name, settings)
'
  arkime_contract="PASS"
else
  arkime_contract="PENDING_FIRST_INGESTION"
fi

for policy in arkime_sessions arkime_history oculox_malcolm_beats; do
  api GET "/_plugins/_ism/policies/$policy" >/dev/null
done

api GET "/_plugins/_ism/explain/$index" | python3 -c '
import json, sys
d = json.load(sys.stdin)
item = next(iter(d.values()))
assert item.get("policy_id") == "oculox_malcolm_beats", item
'

api GET "/$index/_settings" | python3 -c '
import json, sys
item = next(iter(json.load(sys.stdin).values()))["settings"]["index"]
assert item["number_of_shards"] == "1", item
assert item["number_of_replicas"] == "1", item
'

primary_node="$(api GET "/_cat/shards/$index?format=json" | python3 -c '
import json, sys
for shard in json.load(sys.stdin):
    if shard["prirep"] == "p":
        print(shard["node"])
        break
')"
[[ "$primary_node" =~ ^opensearch-[123]$ ]] || { printf 'Unknown primary node: %s\n' "$primary_node" >&2; exit 1; }
stopped_service="$primary_node"
"${compose[@]}" stop "$stopped_service" >/dev/null

for _ in $(seq 1 60); do
  if result="$(api GET "/$index/_doc/storage-test" 2>/dev/null)" && \
    python3 -c 'import json,sys; assert json.load(sys.stdin)["found"] is True' <<<"$result"; then
    break
  fi
  sleep 2
done
result="$(api GET "/$index/_doc/storage-test")"
python3 -c 'import json,sys; assert json.load(sys.stdin)["found"] is True' <<<"$result"

"${compose[@]}" start "$stopped_service" >/dev/null
stopped_service=""
for _ in $(seq 1 120); do
  if recovery="$(api GET '/_cluster/health?wait_for_status=green&timeout=3s' 2>/dev/null)" && \
    python3 -c 'import json, sys; d = json.load(sys.stdin); assert d["status"] == "green" and not d.get("timed_out"), d' <<<"$recovery"; then
    break
  fi
  sleep 2
done
python3 -c '
import json, sys
d = json.loads(sys.argv[1])
assert d["status"] == "green" and not d.get("timed_out"), d
' "$recovery"

api DELETE "/$index" >/dev/null
trap - EXIT

printf 'cluster_disk_watermarks=PASS\n'
printf 'all_indices_minimum_one_replica=PASS\n'
printf 'arkime_index_contract=%s\n' "$arkime_contract"
printf 'ism_policies=PASS\n'
printf 'fixture_primary_shards=1 PASS\n'
printf 'fixture_replicas=1 PASS\n'
printf 'replica_survives_primary_node_loss=PASS\n'
printf 'cluster_recovery_green=PASS\n'
printf 'STORAGE_POLICY_RUNTIME_RESULT=PASS\n'
