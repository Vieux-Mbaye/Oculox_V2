#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "${SCRIPT_DIR}/../../.." && pwd)"
SECURITY_DIR="${PROJECT_DIR}/dev/generated/opensearch-cluster/security/oidc-config"
ADMIN_DIR=""
NETWORK="oculox-opensearch-transport"
TARGET="opensearch-1"
IMAGE="ghcr.io/idaholab/malcolm/opensearch:26.07.1"
CLUSTER_NAME="oculox-opensearch"

usage() {
  cat <<'EOF'
Usage: update-security-config.sh --admin-dir DIR [options]

Met a jour les categories config et rolesmapping du plugin OpenSearch Security.
Les utilisateurs internes, roles et comptes techniques ne sont pas regeneres.

Options:
  --admin-dir DIR       Repertoire contenant admin.crt/admin.key/ca.crt
  --security-dir DIR    Repertoire contenant config.yml et roles_mapping.yml
  --network NAME        Reseau Docker prive du cluster
  --target HOST         Noeud OpenSearch cible
  --image IMAGE         Image contenant securityadmin.sh
EOF
}

while (($#)); do
  case "$1" in
    --admin-dir) ADMIN_DIR="$2"; shift 2 ;;
    --security-dir) SECURITY_DIR="$2"; shift 2 ;;
    --network) NETWORK="$2"; shift 2 ;;
    --target) TARGET="$2"; shift 2 ;;
    --image) IMAGE="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Option inconnue: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ -n "${ADMIN_DIR}" ]] || { echo "--admin-dir est obligatoire" >&2; exit 2; }
for file in admin.crt admin.key ca.crt; do
  [[ -r "${ADMIN_DIR}/${file}" ]] || { echo "Fichier administrateur absent: ${ADMIN_DIR}/${file}" >&2; exit 1; }
done
for file in config.yml roles_mapping.yml; do
  [[ -r "${SECURITY_DIR}/${file}" ]] || { echo "Configuration OIDC absente: ${SECURITY_DIR}/${file}" >&2; exit 1; }
done

docker network inspect "${NETWORK}" >/dev/null 2>&1 || {
  echo "Reseau Docker absent: ${NETWORK}" >&2
  exit 1
}

for category in config rolesmapping; do
  docker run --rm \
    --network "${NETWORK}" \
    --entrypoint /usr/share/opensearch/plugins/opensearch-security/tools/securityadmin.sh \
    --mount "type=bind,src=${SECURITY_DIR},dst=/security,readonly" \
    --mount "type=bind,src=${ADMIN_DIR},dst=/admin,readonly" \
    "${IMAGE}" \
    -f "/security/${category/rolesmapping/roles_mapping}.yml" \
    -t "${category}" \
    -cn "${CLUSTER_NAME}" \
    -h "${TARGET}" \
    -cacert /admin/ca.crt \
    -cert /admin/admin.crt \
    -key /admin/admin.key
done

echo "SECURITY_OIDC_UPDATE_RESULT=PASS"
