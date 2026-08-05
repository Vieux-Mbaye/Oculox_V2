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

for file in ca.crt ca.key server.crt; do
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
mkdir -p "$OUTPUT_DIR"
WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

cat >"${WORK_DIR}/client.ext" <<EOF
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=clientAuth
subjectAltName=DNS:${COLLECTOR_NAME}
EOF

openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 \
    -out "${WORK_DIR}/client.key" >/dev/null 2>&1
openssl req -new -sha256 -key "${WORK_DIR}/client.key" \
    -subj "/O=Oculox/OU=Hedgehog/CN=${COLLECTOR_NAME}" \
    -out "${WORK_DIR}/client.csr"
openssl x509 -req -sha256 -days 825 \
    -in "${WORK_DIR}/client.csr" \
    -CA "${PKI_DIR}/ca.crt" \
    -CAkey "${PKI_DIR}/ca.key" \
    -CAcreateserial \
    -extfile "${WORK_DIR}/client.ext" \
    -out "${WORK_DIR}/client.crt" >/dev/null 2>&1

install -m 0644 "${PKI_DIR}/ca.crt" "${OUTPUT_DIR}/ca.crt"
install -m 0644 "${WORK_DIR}/client.crt" "${OUTPUT_DIR}/client.crt"
install -m 0600 "${WORK_DIR}/client.key" "${OUTPUT_DIR}/client.key"
cat >"${OUTPUT_DIR}/endpoints.env" <<EOF
OCULOX_COLLECTOR_NAME=${COLLECTOR_NAME}
OCULOX_PRINCIPAL_HOST=${PRINCIPAL_HOST}
OCULOX_LOGSTASH_ENDPOINT_1=${PRINCIPAL_HOST}:5044
OCULOX_LOGSTASH_ENDPOINT_2=${PRINCIPAL_HOST}:5045
EOF
chmod 0600 "${OUTPUT_DIR}/endpoints.env"

(
    cd "$OUTPUT_DIR"
    sha256sum ca.crt client.crt client.key endpoints.env > SHA256SUMS
    chmod 0600 SHA256SUMS
)

openssl verify -CAfile "${OUTPUT_DIR}/ca.crt" "${OUTPUT_DIR}/client.crt"
printf 'Bundle collecteur créé : %s\n' "$OUTPUT_DIR"
printf 'Transférez ce répertoire par un canal sécurisé vers le collecteur %s.\n' "$COLLECTOR_NAME"
