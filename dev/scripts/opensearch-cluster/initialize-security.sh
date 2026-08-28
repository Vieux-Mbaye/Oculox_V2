#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "${SCRIPT_DIR}/../../.." && pwd)"
SECURITY_DIR="${PROJECT_DIR}/dev/generated/opensearch-cluster/security/config"
STATE_DIR="${PROJECT_DIR}/dev/generated/opensearch-cluster/state"
ADMIN_DIR=""
NETWORK="oculox-opensearch-transport"
TARGET="opensearch-1"
IMAGE="ghcr.io/idaholab/malcolm/opensearch:26.07.1"
CLUSTER_NAME="oculox-opensearch"

usage() {
  cat <<'EOF'
Usage: initialize-security.sh --admin-dir DIR [options]

Options:
  --admin-dir DIR       Repertoire temporaire contenant admin.crt/admin.key/ca.crt
  --security-dir DIR    Configuration Security rendue
  --state-dir DIR       Repertoire du marqueur d'initialisation
  --network NAME        Reseau Docker du cluster
  --target HOST         Noeud OpenSearch cible
  --image IMAGE         Image OpenSearch contenant securityadmin.sh
EOF
}

while (($#)); do
  case "$1" in
    --admin-dir)
      ADMIN_DIR="$2"
      shift 2
      ;;
    --security-dir)
      SECURITY_DIR="$2"
      shift 2
      ;;
    --state-dir)
      STATE_DIR="$2"
      shift 2
      ;;
    --network)
      NETWORK="$2"
      shift 2
      ;;
    --target)
      TARGET="$2"
      shift 2
      ;;
    --image)
      IMAGE="$2"
      shift 2
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

[[ -n "${ADMIN_DIR}" ]] || {
  echo "--admin-dir est obligatoire" >&2
  exit 2
}
ADMIN_DIR="$(realpath -- "${ADMIN_DIR}")"
SECURITY_DIR="$(realpath -- "${SECURITY_DIR}")"
STATE_DIR="$(realpath -m -- "${STATE_DIR}")"
for file in admin.crt admin.key ca.crt; do
  [[ -r "${ADMIN_DIR}/${file}" ]] || {
    echo "Fichier administrateur absent: ${ADMIN_DIR}/${file}" >&2
    exit 1
  }
done
for file in config.yml internal_users.yml roles.yml roles_mapping.yml; do
  [[ -r "${SECURITY_DIR}/${file}" ]] || {
    echo "Configuration Security absente: ${SECURITY_DIR}/${file}" >&2
    exit 1
  }
done

mkdir -p "${STATE_DIR}"
MARKER="${STATE_DIR}/security-initialized"
[[ ! -e "${MARKER}" ]] || {
  echo "Initialisation refusee: marqueur deja present (${MARKER})." >&2
  exit 1
}

docker network inspect "${NETWORK}" >/dev/null 2>&1 || {
  echo "Reseau Docker absent: ${NETWORK}" >&2
  exit 1
}

for node in opensearch-1 opensearch-2 opensearch-3; do
  [[ "$(docker inspect -f '{{.State.Running}}' "oculox-opensearch-cluster-${node}-1" 2>/dev/null || true)" == "true" ]] || {
    echo "Noeud non demarre: ${node}" >&2
    exit 1
  }
done

probe_security() {
  docker run --rm \
    --network "${NETWORK}" \
    --entrypoint curl \
    --mount "type=bind,src=${ADMIN_DIR},dst=/admin,readonly" \
    "${IMAGE}" \
    --silent --show-error --fail \
    --cacert /admin/ca.crt \
    --cert /admin/admin.crt \
    --key /admin/admin.key \
    "https://${TARGET}:9200/_plugins/_security/api/account" \
    >/dev/null 2>&1
}

if probe_security; then
  echo "Initialisation refusee: le Security index repond deja." >&2
  exit 1
fi

echo "Initialisation unique du plugin OpenSearch Security..."
docker run --rm \
  --network "${NETWORK}" \
  --entrypoint /usr/share/opensearch/plugins/opensearch-security/tools/securityadmin.sh \
  --mount "type=bind,src=${SECURITY_DIR},dst=/security,readonly" \
  --mount "type=bind,src=${ADMIN_DIR},dst=/admin,readonly" \
  "${IMAGE}" \
  -cd /security \
  -cn "${CLUSTER_NAME}" \
  -h "${TARGET}" \
  -cacert /admin/ca.crt \
  -cert /admin/admin.crt \
  -key /admin/admin.key

probe_security || {
  echo "Security ne repond pas apres initialisation." >&2
  exit 1
}

{
  echo "initialized_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "cluster_name=${CLUSTER_NAME}"
  echo "target=${TARGET}"
  echo "security_config_sha256=$(find "${SECURITY_DIR}" -maxdepth 1 -type f -print0 | sort -z | xargs -0 sha256sum | sha256sum | awk '{print $1}')"
} >"${MARKER}"
chmod 600 "${MARKER}"

echo "SECURITY_INITIALIZATION_RESULT=PASS"
echo "Marqueur cree: ${MARKER}"
