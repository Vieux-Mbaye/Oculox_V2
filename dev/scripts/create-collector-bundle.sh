#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"
PKI_DIR="${PROJECT_DIR}/dev/generated/pki"

usage() {
    printf 'Usage: %s <nom-collecteur> <nom-ou-ip-principal> [repertoire-sortie]\n' "$0" >&2
}

COLLECTOR_NAME="${1:-}"
PRINCIPAL_HOST="${2:-}"
OUTPUT_DIR="${3:-${PROJECT_DIR}/dev/generated/collector-bundles/${COLLECTOR_NAME}}"

[[ "$COLLECTOR_NAME" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || { usage; exit 2; }
[[ "$PRINCIPAL_HOST" =~ ^[A-Za-z0-9][A-Za-z0-9.:_-]*$ ]] || { usage; exit 2; }

for file in ca.crt server.crt; do
    [[ -s "${PKI_DIR}/${file}" ]] || {
        printf 'PKI principale incomplète : %s est absent.\n' "${PKI_DIR}/${file}" >&2
        exit 1
    }
done

if python3 - "$PRINCIPAL_HOST" <<'PY'
import ipaddress
import sys

try:
    ipaddress.ip_address(sys.argv[1])
except ValueError:
    raise SystemExit(1)
PY
then
    openssl verify -CAfile "${PKI_DIR}/ca.crt" \
        -verify_ip "$PRINCIPAL_HOST" "${PKI_DIR}/server.crt" >/dev/null || {
        printf 'Le certificat serveur ne contient pas l’adresse IP %s.\n' "$PRINCIPAL_HOST" >&2
        exit 1
    }
else
    openssl verify -CAfile "${PKI_DIR}/ca.crt" \
        -verify_hostname "$PRINCIPAL_HOST" "${PKI_DIR}/server.crt" >/dev/null || {
        printf 'Le certificat serveur ne contient pas le nom DNS %s.\n' "$PRINCIPAL_HOST" >&2
        exit 1
    }
fi

umask 077
if [[ -e "${OUTPUT_DIR}/client.key" || -e "${OUTPUT_DIR}/client.crt" ]]; then
    printf 'Ancien bundle avec cle client detecte; choisissez un repertoire de sortie neuf.\n' >&2
    exit 1
fi
mkdir -p "$OUTPUT_DIR"
install -m 0644 "${PKI_DIR}/ca.crt" "${OUTPUT_DIR}/ca.crt"
cat >"${OUTPUT_DIR}/endpoints.env" <<EOF
OCULOX_COLLECTOR_NAME=${COLLECTOR_NAME}
OCULOX_PRINCIPAL_HOST=${PRINCIPAL_HOST}
OCULOX_LOGSTASH_ENDPOINT_1=${PRINCIPAL_HOST}:5044
OCULOX_LOGSTASH_ENDPOINT_2=${PRINCIPAL_HOST}:5045
EOF
chmod 0600 "${OUTPUT_DIR}/endpoints.env"

(
    cd "$OUTPUT_DIR"
    sha256sum ca.crt endpoints.env > SHA256SUMS
    chmod 0600 SHA256SUMS
)

printf 'Bundle collecteur créé : %s\n' "$OUTPUT_DIR"
printf 'Bundle public uniquement; aucun certificat ou cle privee client. Enrolez le Collecteur sur sa VM.\n'
