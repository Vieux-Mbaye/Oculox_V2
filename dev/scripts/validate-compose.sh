#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

docker compose \
  --project-directory "${REPOSITORY_ROOT}" \
  -f "${REPOSITORY_ROOT}/docker-compose.yml" \
  -f "${REPOSITORY_ROOT}/dev/compose/docker-compose.dev.yml" \
  --profile malcolm \
  config --quiet

docker compose \
  --project-directory "${REPOSITORY_ROOT}" \
  -f "${REPOSITORY_ROOT}/docker-compose.yml" \
  -f "${REPOSITORY_ROOT}/dev/compose/docker-compose.dev.yml" \
  -f "${REPOSITORY_ROOT}/dev/compose/docker-compose.single-logstash.yml" \
  --profile malcolm \
  config --quiet

docker compose \
  --project-directory "${REPOSITORY_ROOT}" \
  -f "${REPOSITORY_ROOT}/docker-compose.yml" \
  -f "${REPOSITORY_ROOT}/dev/compose/docker-compose.dev.yml" \
  --profile hedgehog \
  config --quiet

printf 'Configurations Principal simple/double et Hedgehog valides.\n'
