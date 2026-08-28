#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../../.." && pwd)"
COMPOSE_FILE="$PROJECT_DIR/dev/compose/opensearch-cluster/compose.yml"
ENV_FILE="${OPENSEARCH_CLUSTER_ENV_FILE:-$PROJECT_DIR/dev/config/opensearch-cluster/cluster.env}"
ACCOUNTS_ENV="${OPENSEARCH_ACCOUNTS_ENV:-$PROJECT_DIR/dev/generated/opensearch-cluster/security/accounts.env}"
CA_FILE="${OPENSEARCH_CA_FILE:-$PROJECT_DIR/dev/generated/opensearch-cluster/pki/client-trust/oculox-opensearch-ca.crt}"
ENDPOINT="${OPENSEARCH_CLUSTER_ENDPOINT:-}"

for file in "$ENV_FILE" "$ACCOUNTS_ENV" "$CA_FILE"; do
  if [[ ! -f "$file" ]]; then
    printf 'Required file not found: %s\n' "$file" >&2
    exit 1
  fi
done

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
# shellcheck disable=SC1090
source "$ACCOUNTS_ENV"
set +a

[[ -n "$ENDPOINT" ]] || ENDPOINT="$OPENSEARCH_CLUSTER_ENDPOINT"

compose=(docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE")
auth=(--user "oculox_api:$OCULOX_API_PASSWORD")
tls=(--cacert "$CA_FILE")

status="$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' "${tls[@]}" "$ENDPOINT/healthz")"
[[ "$status" == "200" ]] || { printf 'healthz returned %s\n' "$status" >&2; exit 1; }

anonymous_status="$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' "${tls[@]}" "$ENDPOINT/")"
[[ "$anonymous_status" == "401" ]] || { printf 'anonymous request returned %s\n' "$anonymous_status" >&2; exit 1; }

if curl --silent --show-error --output /dev/null "$ENDPOINT/" 2>/dev/null; then
  printf 'untrusted TLS request unexpectedly succeeded\n' >&2
  exit 1
fi

cluster="$(curl --silent --show-error "${tls[@]}" "${auth[@]}" "$ENDPOINT/_cluster/health")"
python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["number_of_nodes"] == 3; assert d["status"] == "green"' <<<"$cluster"

names="$(for _ in 1 2 3 4 5 6 7 8 9; do
  curl --silent --show-error "${tls[@]}" "${auth[@]}" "$ENDPOINT/_nodes/_local/name"
  printf '\n'
done | python3 -c 'import json,sys; print("\n".join(next(iter(json.loads(line)["nodes"].values()))["name"] for line in sys.stdin if line.strip()))' | sort -u)"
name_count="$(wc -l <<<"$names" | tr -d ' ')"
[[ "$name_count" == "3" ]] || { printf 'Expected 3 backend nodes, got %s: %s\n' "$name_count" "$names" >&2; exit 1; }

printf 'endpoint_health=PASS\n'
printf 'anonymous_authentication=REJECTED PASS\n'
printf 'untrusted_ca=REJECTED PASS\n'
printf 'cluster_green_nodes=3/3 PASS\n'
printf 'roundrobin_nodes=3/3 PASS\n'
printf 'ENDPOINT_PROXY_RUNTIME_RESULT=PASS\n'
