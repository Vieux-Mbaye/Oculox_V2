#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)
OUTPUT_DIR="${1:-${ROOT_DIR}/dev/generated/keycloak-baseline/$(date -u +%Y%m%dT%H%M%SZ)}"
POSTGRES_CONTAINER="${OCULOX_POSTGRES_CONTAINER:-oculox-postgres-1}"
NGINX_CONTAINER="${OCULOX_NGINX_CONTAINER:-oculox-nginx-proxy-1}"

mkdir -p "${OUTPUT_DIR}/inventory" "${OUTPUT_DIR}/private"
chmod 700 "${OUTPUT_DIR}" "${OUTPUT_DIR}/private"

cd "${ROOT_DIR}"

git branch --show-current > "${OUTPUT_DIR}/inventory/git-branch.txt"
git rev-parse HEAD > "${OUTPUT_DIR}/inventory/git-revision.txt"
git status --short > "${OUTPUT_DIR}/inventory/git-status.txt"

docker version --format '{{.Server.Version}}' > "${OUTPUT_DIR}/inventory/docker-version.txt"
docker compose version --short > "${OUTPUT_DIR}/inventory/docker-compose-version.txt"
docker ps --filter 'name=oculox-' \
  --format '{{.Names}}|{{.Image}}|{{.Status}}|{{.Ports}}' \
  | sort > "${OUTPUT_DIR}/inventory/containers.txt"

{
  docker exec oculox-keycloak-1 /opt/keycloak/bin/kc.sh --version | head -n 1
  docker exec "${NGINX_CONTAINER}" nginx -v 2>&1
  docker exec "${POSTGRES_CONTAINER}" postgres --version
  docker exec oculox-logstash-1 /usr/share/logstash/bin/logstash --version 2>&1 | tail -n 1
  docker exec oculox-filebeat-1 filebeat version
} > "${OUTPUT_DIR}/inventory/component-versions.txt"

docker exec "${NGINX_CONTAINER}" nginx -T \
  > "${OUTPUT_DIR}/inventory/nginx-effective.conf" 2> "${OUTPUT_DIR}/inventory/nginx-effective.stderr"

CONFIG_PATHS=(
  config/auth-common.env
  config/keycloak.env
  config/postgres.env
  config/nginx.env
  config/opensearch.env
  config/dashboards.env
  dashboards/opensearch_dashboards.yml
  .opensearch.primary.curlrc
  nginx/htpasswd
  nginx/certs
  nginx/ca-trust
)

EXISTING_PATHS=()
for path in "${CONFIG_PATHS[@]}"; do
  [[ -e "${path}" ]] && EXISTING_PATHS+=("${path}")
done

tar -czf "${OUTPUT_DIR}/private/runtime-configs.tar.gz" "${EXISTING_PATHS[@]}"
chmod 600 "${OUTPUT_DIR}/private/runtime-configs.tar.gz"

find "${EXISTING_PATHS[@]}" -type f -print0 \
  | sort -z \
  | xargs -0 sha256sum > "${OUTPUT_DIR}/inventory/runtime-config-hashes.sha256"

docker exec "${POSTGRES_CONTAINER}" sh -c \
  'PGPASSWORD="$POSTGRES_KEYCLOAK_PASSWORD" pg_dump --format=custom --no-owner --no-privileges --username="$POSTGRES_KEYCLOAK_USER" --dbname="$POSTGRES_KEYCLOAK_DB"' \
  > "${OUTPUT_DIR}/private/keycloak-postgresql.dump"
chmod 600 "${OUTPUT_DIR}/private/keycloak-postgresql.dump"

sha256sum \
  "${OUTPUT_DIR}/private/runtime-configs.tar.gz" \
  "${OUTPUT_DIR}/private/keycloak-postgresql.dump" \
  > "${OUTPUT_DIR}/inventory/private-backup-hashes.sha256"

cat > "${OUTPUT_DIR}/README.txt" <<EOF
Oculox Keycloak K0 baseline
Captured at: $(date -u +%Y-%m-%dT%H:%M:%SZ)
Git branch: $(cat "${OUTPUT_DIR}/inventory/git-branch.txt")
Git revision: $(cat "${OUTPUT_DIR}/inventory/git-revision.txt")

inventory/ contains non-secret evidence.
private/ contains credentials, private keys and the Keycloak PostgreSQL dump.
Keep OUTPUT_DIR mode 700 and private files mode 600.
Never add this directory to Git.
EOF
chmod 600 "${OUTPUT_DIR}/README.txt"

printf 'BASELINE_DIR=%s\n' "${OUTPUT_DIR}"
