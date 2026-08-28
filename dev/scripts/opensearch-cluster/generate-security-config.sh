#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "${SCRIPT_DIR}/../../.." && pwd)"
SOURCE_DIR="${PROJECT_DIR}/dev/config/opensearch-cluster/security"
OUTPUT_DIR="${PROJECT_DIR}/dev/generated/opensearch-cluster/security"
FORCE=false

usage() {
  cat <<'EOF'
Usage: generate-security-config.sh [--output DIR] [--force]

Genere les mots de passe, leurs hashes bcrypt et la configuration initiale du
plugin OpenSearch Security. Aucun secret n'est affiche sur la sortie standard.
EOF
}

while (($#)); do
  case "$1" in
    --output)
      OUTPUT_DIR="$2"
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

for command in openssl htpasswd; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "${command} est requis" >&2
    exit 1
  }
done

[[ -d "${SOURCE_DIR}" ]] || {
  echo "Sources Security absentes: ${SOURCE_DIR}" >&2
  exit 1
}

OUTPUT_PARENT="$(dirname -- "${OUTPUT_DIR}")"
mkdir -p "${OUTPUT_PARENT}"
if [[ -e "${OUTPUT_DIR}" ]]; then
  if [[ "${FORCE}" != true ]]; then
    echo "La configuration Security existe deja: ${OUTPUT_DIR}" >&2
    echo "Utilisez --force uniquement pour une rotation volontaire." >&2
    exit 1
  fi
  if [[ ! -f "${OUTPUT_DIR}/.oculox-opensearch-security" ]]; then
    echo "Rotation refusee: repertoire Security Oculox non reconnu." >&2
    exit 1
  fi
  rm -rf -- "${OUTPUT_DIR}"
fi

umask 077
WORK_DIR="$(mktemp -d "${OUTPUT_PARENT}/.security-build.XXXXXX")"
trap 'rm -rf -- "${WORK_DIR}"' EXIT
mkdir -p "${WORK_DIR}/config"
cp "${SOURCE_DIR}"/*.yml "${WORK_DIR}/config/"

declare -a ACCOUNTS=(
  "oculox_platform_admin:oculox_platform_admin:Oculox platform administrator"
  "oculox_logstash:oculox_logstash_writer:Logstash ingestion service"
  "oculox_arkime:oculox_arkime_service:Arkime and Arkime Live service"
  "oculox_dashboards:oculox_dashboards_server:OpenSearch Dashboards server"
  "oculox_dashboards_helper:oculox_dashboards_helper:Dashboards initialization service"
  "oculox_api:oculox_api_reader:Oculox API and pcap-monitor reader"
  "oculox_snapshot:oculox_snapshot_operator:Snapshot operator"
)

cat >"${WORK_DIR}/config/internal_users.yml" <<'EOF'
---
_meta:
  type: "internalusers"
  config_version: 2

EOF

: >"${WORK_DIR}/accounts.env"
cat >"${WORK_DIR}/accounts.txt" <<'EOF'
username|backend_role|purpose
EOF

for account in "${ACCOUNTS[@]}"; do
  IFS=: read -r username backend_role purpose <<<"${account}"
  password="$(openssl rand -base64 32 | tr '/+' '_-' | tr -d '=\n')"
  password_hash="$(htpasswd -bnBC 12 "${username}" "${password}" | cut -d: -f2 | tr -d '\n')"
  variable_name="$(printf '%s_PASSWORD' "${username}" | tr '[:lower:]' '[:upper:]')"

  cat >>"${WORK_DIR}/config/internal_users.yml" <<EOF
${username}:
  hash: '${password_hash}'
  reserved: false
  hidden: false
  backend_roles:
    - "${backend_role}"
  description: "${purpose}"

EOF
  printf '%s=%s\n' "${variable_name}" "${password}" >>"${WORK_DIR}/accounts.env"
  printf '%s|%s|%s\n' "${username}" "${backend_role}" "${purpose}" >>"${WORK_DIR}/accounts.txt"
done

touch "${WORK_DIR}/.oculox-opensearch-security"
find "${WORK_DIR}" -type d -exec chmod 700 {} +
find "${WORK_DIR}/config" -type f -exec chmod 600 {} +
chmod 600 \
  "${WORK_DIR}/accounts.env" \
  "${WORK_DIR}/accounts.txt" \
  "${WORK_DIR}/.oculox-opensearch-security"

mv "${WORK_DIR}" "${OUTPUT_DIR}"
trap - EXIT

echo "Configuration Security generee dans ${OUTPUT_DIR}"
echo "Comptes generes: ${#ACCOUNTS[@]}"
echo "Les mots de passe sont conserves dans accounts.env (mode 600)."
