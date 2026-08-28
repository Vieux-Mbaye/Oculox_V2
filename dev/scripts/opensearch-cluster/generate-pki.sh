#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "${SCRIPT_DIR}/../../.." && pwd)"
OUTPUT_DIR="${PROJECT_DIR}/dev/generated/opensearch-cluster/pki"
ENDPOINT_IP=""
VALIDITY_DAYS=825
CA_VALIDITY_DAYS=3650
FORCE=false

usage() {
  cat <<'EOF'
Usage: generate-pki.sh [options]

Options:
  --output DIR         Repertoire de sortie des certificats generes
  --endpoint-ip IP     Adresse IP placee dans le SAN (obligatoire)
  --validity-days N    Validite des certificats feuilles (defaut: 825)
  --force              Remplace une PKI deja presente
  -h, --help           Affiche cette aide
EOF
}

while (($#)); do
  case "$1" in
    --output)
      OUTPUT_DIR="$2"
      shift 2
      ;;
    --endpoint-ip)
      ENDPOINT_IP="$2"
      shift 2
      ;;
    --validity-days)
      VALIDITY_DAYS="$2"
      shift 2
      ;;
    --force)
      FORCE=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Option inconnue: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

command -v openssl >/dev/null 2>&1 || {
  echo "openssl est requis" >&2
  exit 1
}

[[ "${ENDPOINT_IP}" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]] || {
  echo "Adresse IPv4 invalide: ${ENDPOINT_IP}" >&2
  exit 2
}
IFS=. read -r -a endpoint_octets <<<"${ENDPOINT_IP}"
for octet in "${endpoint_octets[@]}"; do
  ((10#${octet} <= 255)) || {
    echo "Adresse IPv4 invalide: ${ENDPOINT_IP}" >&2
    exit 2
  }
done
[[ "${VALIDITY_DAYS}" =~ ^[1-9][0-9]*$ ]] || {
  echo "Validite invalide: ${VALIDITY_DAYS}" >&2
  exit 2
}

OUTPUT_PARENT="$(dirname -- "${OUTPUT_DIR}")"
mkdir -p "${OUTPUT_PARENT}"

if [[ -e "${OUTPUT_DIR}" ]]; then
  if [[ "${FORCE}" != true ]]; then
    echo "La PKI existe deja: ${OUTPUT_DIR}" >&2
    echo "Utilisez --force uniquement pour une rotation volontaire." >&2
    exit 1
  fi
  if [[ ! -f "${OUTPUT_DIR}/.oculox-opensearch-pki" ]] && \
     ! grep -q '^endpoint_ip=' "${OUTPUT_DIR}/manifest.txt" 2>/dev/null; then
    echo "Rotation refusee: le repertoire n'est pas une PKI Oculox reconnue." >&2
    exit 1
  fi
  rm -rf -- "${OUTPUT_DIR}"
fi

umask 077
WORK_DIR="$(mktemp -d "${OUTPUT_PARENT}/.pki-build.XXXXXX")"
trap 'rm -rf -- "${WORK_DIR}"' EXIT

mkdir -p \
  "${WORK_DIR}/ca" \
  "${WORK_DIR}/admin" \
  "${WORK_DIR}/client-trust" \
  "${WORK_DIR}/endpoint" \
  "${WORK_DIR}/nodes"

openssl genpkey \
  -quiet \
  -algorithm RSA \
  -pkeyopt rsa_keygen_bits:4096 \
  -out "${WORK_DIR}/ca/ca.key"

openssl req -x509 -new -sha256 \
  -key "${WORK_DIR}/ca/ca.key" \
  -days "${CA_VALIDITY_DAYS}" \
  -subj "/C=SN/O=Oculox/OU=OpenSearch PKI/CN=Oculox OpenSearch Root CA" \
  -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
  -addext "keyUsage=critical,keyCertSign,cRLSign" \
  -addext "subjectKeyIdentifier=hash" \
  -out "${WORK_DIR}/ca/ca.crt"

issue_certificate() {
  local name="$1"
  local subject="$2"
  local san="$3"
  local extended_key_usage="$4"
  local destination="$5"
  local key_usage="digitalSignature,keyEncipherment"
  local ext_file="${WORK_DIR}/${name}.ext"
  local csr_file="${WORK_DIR}/${name}.csr"
  local serial_file="${WORK_DIR}/ca/ca.srl"

  mkdir -p "${destination}"
  openssl genpkey \
    -quiet \
    -algorithm RSA \
    -pkeyopt rsa_keygen_bits:3072 \
    -out "${destination}/${name}.key"

  openssl req -new -sha256 \
    -key "${destination}/${name}.key" \
    -subj "${subject}" \
    -out "${csr_file}"

  cat >"${ext_file}" <<EOF
basicConstraints=critical,CA:FALSE
keyUsage=critical,${key_usage}
extendedKeyUsage=${extended_key_usage}
subjectAltName=${san}
subjectKeyIdentifier=hash
authorityKeyIdentifier=keyid,issuer
EOF

  local serial_args=(-CAserial "${serial_file}")
  [[ -f "${serial_file}" ]] || serial_args=(-CAcreateserial)

  openssl x509 -req -sha256 \
    -in "${csr_file}" \
    -CA "${WORK_DIR}/ca/ca.crt" \
    -CAkey "${WORK_DIR}/ca/ca.key" \
    "${serial_args[@]}" \
    -days "${VALIDITY_DAYS}" \
    -extfile "${ext_file}" \
    -out "${destination}/${name}.crt"
}

for node in opensearch-1 opensearch-2 opensearch-3; do
  node_dir="${WORK_DIR}/nodes/${node}"
  issue_certificate \
    node \
    "/C=SN/O=Oculox/OU=OpenSearch Nodes/CN=${node}" \
    "DNS:${node}" \
    "serverAuth,clientAuth" \
    "${node_dir}"
  cp "${WORK_DIR}/ca/ca.crt" "${node_dir}/ca.crt"
done

issue_certificate \
  endpoint \
  "/C=SN/O=Oculox/OU=OpenSearch HTTP/CN=${ENDPOINT_IP}" \
  "IP:${ENDPOINT_IP}" \
  "serverAuth" \
  "${WORK_DIR}/endpoint"
cp "${WORK_DIR}/ca/ca.crt" "${WORK_DIR}/endpoint/ca.crt"

issue_certificate \
  admin \
  "/C=SN/O=Oculox/OU=OpenSearch Administration/CN=oculox-opensearch-admin" \
  "DNS:oculox-opensearch-admin" \
  "clientAuth" \
  "${WORK_DIR}/admin"
cp "${WORK_DIR}/ca/ca.crt" "${WORK_DIR}/admin/ca.crt"
cp "${WORK_DIR}/ca/ca.crt" "${WORK_DIR}/client-trust/oculox-opensearch-ca.crt"

rm -f -- "${WORK_DIR}"/*.csr "${WORK_DIR}"/*.ext "${WORK_DIR}/ca/ca.srl"

find "${WORK_DIR}" -type d -exec chmod 700 {} +
find "${WORK_DIR}" -type f -name '*.key' -exec chmod 600 {} +
find "${WORK_DIR}" -type f -name '*.crt' -exec chmod 644 {} +

{
  echo "endpoint_ip=${ENDPOINT_IP}"
  echo "leaf_validity_days=${VALIDITY_DAYS}"
  echo "ca_validity_days=${CA_VALIDITY_DAYS}"
  echo "generated_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo
  for cert in \
    "${WORK_DIR}/ca/ca.crt" \
    "${WORK_DIR}/nodes/opensearch-1/node.crt" \
    "${WORK_DIR}/nodes/opensearch-2/node.crt" \
    "${WORK_DIR}/nodes/opensearch-3/node.crt" \
    "${WORK_DIR}/endpoint/endpoint.crt" \
    "${WORK_DIR}/admin/admin.crt"; do
    echo "[$(realpath --relative-to="${WORK_DIR}" "${cert}")]"
    openssl x509 -in "${cert}" -noout \
      -subject -issuer -serial -fingerprint -sha256 -dates
    echo
  done
} >"${WORK_DIR}/manifest.txt"
chmod 600 "${WORK_DIR}/manifest.txt"
touch "${WORK_DIR}/.oculox-opensearch-pki"
chmod 600 "${WORK_DIR}/.oculox-opensearch-pki"

mv "${WORK_DIR}" "${OUTPUT_DIR}"
trap - EXIT

echo "PKI OpenSearch generee dans ${OUTPUT_DIR}"
echo "CA a distribuer aux clients: ${OUTPUT_DIR}/ca/ca.crt"
echo "Certificat endpoint: ${OUTPUT_DIR}/endpoint/endpoint.crt"
echo "Certificat administrateur: ${OUTPUT_DIR}/admin/admin.crt"
