#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
BASE_COMPOSE="$(mktemp "$PROJECT_DIR/.compose-exposed-ports.XXXXXX.yml")"
trap 'rm -f "$BASE_COMPOSE"' EXIT

cp "$PROJECT_DIR/docker-compose.yml" "$BASE_COMPOSE"

# Reproduce the changes made by the official "Expose Oculox Service Ports"
# option for the two Beats-related services. The Nginx 9200 publication does
# not conflict and therefore does not need to be simulated here.
perl -0pi -e 's|(    stop_grace_period: 2m\n)(  filebeat:)|$1    ports:\n    - 0.0.0.0:5044:5044/tcp\n$2|' "$BASE_COMPOSE"
perl -0pi -e 's|(    stop_grace_period: 30s\n)(  arkime:)|$1    ports:\n    - 0.0.0.0:5045:5045/tcp\n$2|' "$BASE_COMPOSE"

docker compose \
    --project-directory "$PROJECT_DIR" \
    -f "$BASE_COMPOSE" \
    -f "$PROJECT_DIR/dev/compose/docker-compose.dev.yml" \
    --profile malcolm \
    config --format json |
python3 -c '
import json
import sys

services = json.load(sys.stdin)["services"]

def published(service):
    return sorted(
        (str(port.get("published")), int(port["target"]))
        for port in services[service].get("ports", [])
    )

assert published("logstash") == [("5044", 5044)], published("logstash")
assert published("logstash-2") == [("5045", 5044)], published("logstash-2")
assert published("filebeat") == [], published("filebeat")
'

printf 'PASS: exposed service ports remain compatible with dual Logstash\n'
