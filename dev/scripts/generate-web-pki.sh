#!/usr/bin/env bash

set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
IDENTITY_ENV="${PROJECT_DIR}/dev/generated/public-endpoint.env"
PKI_DIR="${PROJECT_DIR}/dev/generated/web-pki"
CERT_DIR="${PROJECT_DIR}/nginx/certs"
TRUST_DIR="${PROJECT_DIR}/nginx/ca-trust"
BUNDLE_DIR="${PROJECT_DIR}/dev/generated/web-trust"
MODE=development
FORCE=false
PROVIDED_CERT=""
PROVIDED_KEY=""
PROVIDED_CA=""

usage() {
  cat >&2 <<'EOF'
Usage: generate-web-pki.sh [--identity-env file] [--mode development|provided]
       [--certificate file --private-key file --ca-certificate file]
       [--pki-dir dir --cert-dir dir --trust-dir dir --bundle-dir dir] [--force]
EOF
}

while (($#)); do
  case "$1" in
    --identity-env) shift; IDENTITY_ENV="${1:-}" ;;
    --mode) shift; MODE="${1:-}" ;;
    --certificate) shift; PROVIDED_CERT="${1:-}" ;;
    --private-key) shift; PROVIDED_KEY="${1:-}" ;;
    --ca-certificate) shift; PROVIDED_CA="${1:-}" ;;
    --pki-dir) shift; PKI_DIR="${1:-}" ;;
    --cert-dir) shift; CERT_DIR="${1:-}" ;;
    --trust-dir) shift; TRUST_DIR="${1:-}" ;;
    --bundle-dir) shift; BUNDLE_DIR="${1:-}" ;;
    --force) FORCE=true ;;
    *) usage; exit 2 ;;
  esac
  shift
done

[[ "${MODE}" == development || "${MODE}" == provided ]] || { usage; exit 2; }
[[ -s "${IDENTITY_ENV}" ]] || { echo "Public identity file is missing: ${IDENTITY_ENV}" >&2; exit 1; }

env_value() {
  sed -n "s/^${1}=//p" "${IDENTITY_ENV}"
}

PUBLIC_HOST="$(env_value OCULOX_PUBLIC_HOST)"
IDENTITY_TYPE="$(env_value OCULOX_PUBLIC_IDENTITY_TYPE)"
PUBLIC_SAN="$(env_value OCULOX_PUBLIC_SAN)"
PUBLIC_URL="$(env_value OCULOX_PUBLIC_URL)"
[[ -n "${PUBLIC_HOST}" && -n "${PUBLIC_SAN}" && "${PUBLIC_URL}" == https://* ]] || {
  echo "Public identity file is incomplete" >&2
  exit 1
}

case "${IDENTITY_TYPE}" in
  ipv4|ipv6) CHECK_ARGUMENT=(-checkip "${PUBLIC_HOST}") ;;
  dns) CHECK_ARGUMENT=(-checkhost "${PUBLIC_HOST}") ;;
  *) echo "Unsupported public identity type: ${IDENTITY_TYPE}" >&2; exit 1 ;;
esac

certificate_matches_key() {
  local certificate="$1"
  local private_key="$2"
  local cert_hash key_hash
  cert_hash=$(openssl x509 -in "${certificate}" -pubkey -noout | openssl sha256)
  key_hash=$(openssl pkey -in "${private_key}" -pubout 2>/dev/null | openssl sha256)
  [[ "${cert_hash}" == "${key_hash}" ]]
}

validate_material() {
  local certificate="$1"
  local private_key="$2"
  local ca_certificate="$3"
  local identity_check
  identity_check=$(openssl x509 -in "${certificate}" -noout "${CHECK_ARGUMENT[@]}")
  [[ "${identity_check}" == *"does match certificate"* ]] || return 1
  openssl verify -CAfile "${ca_certificate}" "${certificate}" >/dev/null || return 1
  certificate_matches_key "${certificate}" "${private_key}" || return 1
}

publish_material() {
  local certificate="$1"
  local private_key="$2"
  local ca_certificate="$3"
  install -d -m 0700 "${CERT_DIR}" "${BUNDLE_DIR}"
  install -d -m 0755 "${TRUST_DIR}"
  if [[ ! "${certificate}" -ef "${CERT_DIR}/cert.pem" ]]; then
    install -m 0644 "${certificate}" "${CERT_DIR}/cert.pem"
  fi
  if [[ ! "${private_key}" -ef "${CERT_DIR}/key.pem" ]]; then
    install -m 0600 "${private_key}" "${CERT_DIR}/key.pem"
  fi
  if [[ ! "${ca_certificate}" -ef "${TRUST_DIR}/oculox-web-ca.crt" ]]; then
    install -m 0644 "${ca_certificate}" "${TRUST_DIR}/oculox-web-ca.crt"
  fi
  install -m 0644 "${ca_certificate}" "${BUNDLE_DIR}/oculox-web-ca.crt"
  cat > "${BUNDLE_DIR}/endpoint.env" <<EOF
OCULOX_PUBLIC_HOST=${PUBLIC_HOST}
OCULOX_PUBLIC_URL=${PUBLIC_URL}
OCULOX_PUBLIC_SAN=${PUBLIC_SAN}
EOF
  chmod 0644 "${BUNDLE_DIR}/endpoint.env"
  (
    cd "${BUNDLE_DIR}"
    sha256sum oculox-web-ca.crt endpoint.env > SHA256SUMS
  )
  chmod 0644 "${BUNDLE_DIR}/SHA256SUMS"
  if find "${BUNDLE_DIR}" -type f \( -name '*.key' -o -name '*key.pem' \) | grep -q .; then
    echo "A private key was found in the public trust bundle" >&2
    exit 1
  fi
}

umask 077

CA_KEY="${PKI_DIR}/ca.key"
CA_CERT="${PKI_DIR}/ca.crt"
SERVER_KEY="${PKI_DIR}/server.key"
SERVER_CERT="${PKI_DIR}/server.crt"

if [[ "${MODE}" == provided ]]; then
  [[ -s "${PROVIDED_CERT}" && -s "${PROVIDED_KEY}" && -s "${PROVIDED_CA}" ]] || {
    echo "Provided mode requires --certificate, --private-key and --ca-certificate" >&2
    exit 2
  }
  validate_material "${PROVIDED_CERT}" "${PROVIDED_KEY}" "${PROVIDED_CA}" || {
    echo "Provided TLS material failed certificate, SAN, chain or key validation" >&2
    exit 1
  }
  publish_material "${PROVIDED_CERT}" "${PROVIDED_KEY}" "${PROVIDED_CA}"
  echo "Provided web certificate installed for ${PUBLIC_URL}"
  exit 0
fi

# An externally issued certificate must never fall back to a development CA.
if [[ -s "${CERT_DIR}/cert.pem" ]] && {
  [[ ! -s "${CA_KEY}" ]] || ! openssl verify -CAfile "${CA_CERT}" "${CERT_DIR}/cert.pem" >/dev/null 2>&1
}; then
  [[ "${FORCE}" == false ]] || {
    echo "External web PKI: renew through its issuer, not --force" >&2
    exit 1
  }
  validate_material "${CERT_DIR}/cert.pem" "${CERT_DIR}/key.pem" "${TRUST_DIR}/oculox-web-ca.crt" || {
    echo "External web certificate invalid for ${PUBLIC_HOST}; enroll a replacement with its issuer" >&2
    exit 1
  }
  publish_material "${CERT_DIR}/cert.pem" "${CERT_DIR}/key.pem" "${TRUST_DIR}/oculox-web-ca.crt"
  echo "External web PKI retained for ${PUBLIC_URL}"
  exit 0
fi

[[ "${OCULOX_ALLOW_LOCAL_DEV_PKI:-0}" == 1 ]] || {
  echo "Local CA generation disabled. Enroll with ./oculox pki using EJBCA." >&2
  exit 1
}
if [[ "${FORCE}" == true ]]; then
  rm -f \
    "${CA_KEY}" \
    "${CA_CERT}" \
    "${SERVER_KEY}" \
    "${SERVER_CERT}" \
    "${PKI_DIR}/server.csr" \
    "${PKI_DIR}/server.ext" \
    "${PKI_DIR}/ca.srl"
fi
install -d -m 0700 "${PKI_DIR}"

if [[ ! -s "${CA_KEY}" || ! -s "${CA_CERT}" ]]; then
  openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:4096 -out "${CA_KEY}" >/dev/null 2>&1
  openssl req -x509 -new -sha256 -days 3650 \
    -key "${CA_KEY}" \
    -subj "/O=Oculox/OU=Development Web PKI/CN=Oculox Development Web CA" \
    -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
    -addext "keyUsage=critical,keyCertSign,cRLSign" \
    -out "${CA_CERT}"
fi

if [[ -s "${SERVER_KEY}" && -s "${SERVER_CERT}" ]] && \
   validate_material "${SERVER_CERT}" "${SERVER_KEY}" "${CA_CERT}"; then
  publish_material "${SERVER_CERT}" "${SERVER_KEY}" "${CA_CERT}"
  echo "Existing web PKI is valid for ${PUBLIC_URL}"
  exit 0
fi

cat > "${PKI_DIR}/server.ext" <<EOF
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=${PUBLIC_SAN}
EOF

openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out "${SERVER_KEY}" >/dev/null 2>&1
openssl req -new -sha256 \
  -key "${SERVER_KEY}" \
  -subj "/O=Oculox/OU=Web/CN=${PUBLIC_HOST}" \
  -out "${PKI_DIR}/server.csr"
openssl x509 -req -sha256 -days 397 \
  -in "${PKI_DIR}/server.csr" \
  -CA "${CA_CERT}" \
  -CAkey "${CA_KEY}" \
  -CAcreateserial \
  -extfile "${PKI_DIR}/server.ext" \
  -out "${SERVER_CERT}" >/dev/null 2>&1

rm -f "${PKI_DIR}/server.csr" "${PKI_DIR}/server.ext" "${PKI_DIR}"/*.srl
chmod 0600 "${CA_KEY}" "${SERVER_KEY}"
chmod 0644 "${CA_CERT}" "${SERVER_CERT}"
validate_material "${SERVER_CERT}" "${SERVER_KEY}" "${CA_CERT}"
publish_material "${SERVER_CERT}" "${SERVER_KEY}" "${CA_CERT}"

openssl x509 -in "${SERVER_CERT}" -noout -subject -issuer -dates -ext subjectAltName
echo "Development web PKI generated for ${PUBLIC_URL}"
