#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

docker compose \
  --project-directory "${REPOSITORY_ROOT}" \
  -f "${REPOSITORY_ROOT}/docker-compose.yml" \
  -f "${REPOSITORY_ROOT}/dev/compose/docker-compose.dev.yml" \
  config --quiet

printf 'Configuration Docker Compose valide.\n'

