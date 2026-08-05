#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"
PKI_DIR="${PROJECT_DIR}/dev/generated/pki"
FORCE=false
SERVER_NAME=""

while (($#)); do
    case "$1" in
        --force) FORCE=true ;;
        --server-name)
            shift
            SERVER_NAME="${1:-}"
            [[ -n "$SERVER_NAME" ]] || { printf '%s\n' '--server-name exige une valeur' >&2; exit 2; }
            ;;
        *)
            printf 'Usage: %s [--force] [--server-name nom-ou-ip]\n' "$0" >&2
            exit 2
            ;;
    esac
    shift
done

required_files=(ca.crt server.crt server.key client.crt client.key)
complete=true
for file in "${required_files[@]}"; do
    [[ -s "${PKI_DIR}/${file}" ]] || complete=false
done

if [[ "$complete" == true && -n "$SERVER_NAME" ]]; then
    openssl x509 -in "${PKI_DIR}/server.crt" -noout -ext subjectAltName 2>/dev/null \
        | grep -Fq "$SERVER_NAME" || complete=false
fi

if [[ "$complete" == true && "$FORCE" == false ]]; then
    openssl verify -CAfile "${PKI_DIR}/ca.crt" \
        "${PKI_DIR}/server.crt" "${PKI_DIR}/client.crt" >/dev/null
    printf 'PKI existante valide : %s\n' "$PKI_DIR"
    exit 0
fi

umask 077
rm -rf "$PKI_DIR"
mkdir -p "$PKI_DIR"

SERVER_SAN="DNS:logstash,DNS:logstash-2"
if [[ -n "$SERVER_NAME" ]]; then
    if [[ "$SERVER_NAME" =~ ^[0-9a-fA-F:.]+$ ]]; then
        SERVER_SAN+=",IP:${SERVER_NAME}"
    elif [[ "$SERVER_NAME" =~ ^[A-Za-z0-9][A-Za-z0-9.-]*$ ]]; then
        SERVER_SAN+=",DNS:${SERVER_NAME}"
    else
        printf 'Nom de serveur invalide : %s\n' "$SERVER_NAME" >&2
        exit 2
    fi
fi

cat >"${PKI_DIR}/server.ext" <<EOF
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=${SERVER_SAN}
EOF

cat >"${PKI_DIR}/client.ext" <<'EOF'
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=clientAuth
subjectAltName=DNS:filebeat
EOF

openssl genpkey -algorithm RSA \
    -pkeyopt rsa_keygen_bits:4096 \
    -out "${PKI_DIR}/ca.key" >/dev/null 2>&1
openssl req -x509 -new -sha256 -days 3650 \
    -key "${PKI_DIR}/ca.key" \
    -subj "/O=Oculox/OU=Ingestion PKI/CN=Oculox Beats CA" \
    -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
    -addext "keyUsage=critical,keyCertSign,cRLSign" \
    -out "${PKI_DIR}/ca.crt"

openssl genpkey -algorithm RSA \
    -pkeyopt rsa_keygen_bits:3072 \
    -out "${PKI_DIR}/server.key" >/dev/null 2>&1
openssl req -new -sha256 \
    -key "${PKI_DIR}/server.key" \
    -subj "/O=Oculox/OU=Logstash/CN=logstash" \
    -out "${PKI_DIR}/server.csr"
openssl x509 -req -sha256 -days 825 \
    -in "${PKI_DIR}/server.csr" \
    -CA "${PKI_DIR}/ca.crt" \
    -CAkey "${PKI_DIR}/ca.key" \
    -CAcreateserial \
    -extfile "${PKI_DIR}/server.ext" \
    -out "${PKI_DIR}/server.crt" >/dev/null 2>&1

openssl genpkey -algorithm RSA \
    -pkeyopt rsa_keygen_bits:3072 \
    -out "${PKI_DIR}/client.key" >/dev/null 2>&1
openssl req -new -sha256 \
    -key "${PKI_DIR}/client.key" \
    -subj "/O=Oculox/OU=Filebeat/CN=principal-filebeat" \
    -out "${PKI_DIR}/client.csr"
openssl x509 -req -sha256 -days 825 \
    -in "${PKI_DIR}/client.csr" \
    -CA "${PKI_DIR}/ca.crt" \
    -CAkey "${PKI_DIR}/ca.key" \
    -CAcreateserial \
    -extfile "${PKI_DIR}/client.ext" \
    -out "${PKI_DIR}/client.crt" >/dev/null 2>&1

rm -f "${PKI_DIR}"/*.csr "${PKI_DIR}"/*.ext "${PKI_DIR}"/*.srl
chmod 600 "${PKI_DIR}"/*.key
chmod 644 "${PKI_DIR}"/*.crt

openssl verify -CAfile "${PKI_DIR}/ca.crt" \
    "${PKI_DIR}/server.crt" "${PKI_DIR}/client.crt"
openssl x509 -in "${PKI_DIR}/server.crt" -noout \
    -subject -issuer -dates -ext subjectAltName -ext extendedKeyUsage

printf 'PKI generee dans %s\n' "$PKI_DIR"
