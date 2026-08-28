#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "${SCRIPT_DIR}/../../.." && pwd)"
ROLES_FILE="${PROJECT_DIR}/dev/config/opensearch-cluster/security/roles.yml"
ADMIN_DIR=""
NETWORK="oculox-opensearch-transport"
TARGET="opensearch-1"
IMAGE="ghcr.io/idaholab/malcolm/opensearch:26.07.1"
CLUSTER_NAME="oculox-opensearch"

usage() {
  cat <<'EOF'
Usage: update-security-roles.sh --admin-dir DIR [options]

Met a jour uniquement la categorie roles du plugin OpenSearch Security.

Options:
  --admin-dir DIR       Repertoire contenant admin.crt/admin.key/ca.crt
  --roles-file FILE     Fichier roles.yml a appliquer
  --network NAME        Reseau Docker prive du cluster
  --target HOST         Noeud OpenSearch cible
  --image IMAGE         Image contenant securityadmin.sh
EOF
}

while (($#)); do
  case "$1" in
    --admin-dir) ADMIN_DIR="$2"; shift 2 ;;
    --roles-file) ROLES_FILE="$2"; shift 2 ;;
    --network) NETWORK="$2"; shift 2 ;;
    --target) TARGET="$2"; shift 2 ;;
    --image) IMAGE="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Option inconnue: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ -n "${ADMIN_DIR}" ]] || { echo "--admin-dir est obligatoire" >&2; exit 2; }
[[ -r "${ROLES_FILE}" ]] || { echo "Fichier roles absent: ${ROLES_FILE}" >&2; exit 1; }
for file in admin.crt admin.key ca.crt; do
  [[ -r "${ADMIN_DIR}/${file}" ]] || { echo "Fichier administrateur absent: ${ADMIN_DIR}/${file}" >&2; exit 1; }
done

docker network inspect "${NETWORK}" >/dev/null 2>&1 || {
  echo "Reseau Docker absent: ${NETWORK}" >&2
  exit 1
}

docker run --rm \
  --network "${NETWORK}" \
  --entrypoint /usr/share/opensearch/plugins/opensearch-security/tools/securityadmin.sh \
  --mount "type=bind,src=${ROLES_FILE},dst=/security/roles.yml,readonly" \
  --mount "type=bind,src=${ADMIN_DIR},dst=/admin,readonly" \
  "${IMAGE}" \
  -f /security/roles.yml \
  -t roles \
  -cn "${CLUSTER_NAME}" \
  -h "${TARGET}" \
  -cacert /admin/ca.crt \
  -cert /admin/admin.crt \
  -key /admin/admin.key

echo "SECURITY_ROLES_UPDATE_RESULT=PASS"
