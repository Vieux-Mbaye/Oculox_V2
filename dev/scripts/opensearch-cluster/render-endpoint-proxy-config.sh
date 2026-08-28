#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../../.." && pwd)"
TEMPLATE="$PROJECT_DIR/dev/config/opensearch-cluster/haproxy.cfg.template"
ACCOUNTS_ENV="$PROJECT_DIR/dev/generated/opensearch-cluster/security/accounts.env"
PKI_DIR="$PROJECT_DIR/dev/generated/opensearch-cluster/pki"
OUTPUT_DIR="$PROJECT_DIR/dev/generated/opensearch-cluster/endpoint-proxy"

usage() {
  cat <<'EOF'
Usage: render-endpoint-proxy-config.sh [--accounts-env FILE] [--pki-dir DIR] [--output-dir DIR]

Renders the HAProxy configuration and TLS material for the stable OpenSearch
endpoint. Generated files contain a health-check credential and must not be
committed.
EOF
}

while (($#)); do
  case "$1" in
    --accounts-env)
      ACCOUNTS_ENV="$2"
      shift 2
      ;;
    --pki-dir)
      PKI_DIR="$2"
      shift 2
      ;;
    --output-dir)
      OUTPUT_DIR="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      printf 'Unknown argument: %s\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

for file in \
  "$TEMPLATE" \
  "$ACCOUNTS_ENV" \
  "$PKI_DIR/endpoint/endpoint.crt" \
  "$PKI_DIR/endpoint/endpoint.key" \
  "$PKI_DIR/endpoint/ca.crt" \
  "$PKI_DIR/client-trust/oculox-opensearch-ca.crt"; do
  if [[ ! -f "$file" ]]; then
    printf 'Required file not found: %s\n' "$file" >&2
    exit 1
  fi
done

set -a
# shellcheck disable=SC1090
source "$ACCOUNTS_ENV"
set +a

if [[ -z "${OCULOX_API_PASSWORD:-}" ]]; then
  printf 'OCULOX_API_PASSWORD is missing from %s\n' "$ACCOUNTS_ENV" >&2
  exit 1
fi

health_authorization="$(printf 'oculox_api:%s' "$OCULOX_API_PASSWORD" | base64 | tr -d '\n')"

umask 077
mkdir -p "$OUTPUT_DIR"
sed "s|__HEALTH_AUTHORIZATION__|$health_authorization|g" \
  "$TEMPLATE" > "$OUTPUT_DIR/haproxy.cfg"
cat \
  "$PKI_DIR/endpoint/endpoint.crt" \
  "$PKI_DIR/endpoint/ca.crt" \
  "$PKI_DIR/endpoint/endpoint.key" \
  > "$OUTPUT_DIR/endpoint.pem"
cp "$PKI_DIR/client-trust/oculox-opensearch-ca.crt" \
  "$OUTPUT_DIR/backend-ca.crt"
chmod 600 "$OUTPUT_DIR/haproxy.cfg" "$OUTPUT_DIR/endpoint.pem" "$OUTPUT_DIR/backend-ca.crt"

printf 'OpenSearch endpoint proxy configuration rendered in %s\n' "$OUTPUT_DIR"
