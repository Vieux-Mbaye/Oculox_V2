#!/usr/bin/env bash

set -euo pipefail

LOGSTASH_CONTAINERS=(oculox-logstash-1 oculox-logstash-2-1)

echo "=== Conteneurs ==="
docker ps --filter 'name=oculox-' \
    --format 'table {{.Names}}\t{{.Status}}\t{{.Image}}'

for container in "${LOGSTASH_CONTAINERS[@]}"; do
    echo
    echo "=== Files persistantes : ${container} ==="
    if ! docker inspect "$container" >/dev/null 2>&1; then
        echo "Conteneur absent."
        continue
    fi

    if ! payload="$(docker exec "$container" sh -c \
        'curl -fsS http://127.0.0.1:9600/_node/stats/pipelines' 2>/dev/null)"; then
        echo "API Logstash indisponible : le service démarre ou est arrêté."
        continue
    fi

    printf '%s' "$payload" | python3 -c '
import json
import sys

data = json.load(sys.stdin)
for pipeline_id, stats in sorted(data.get("pipelines", {}).items()):
    queue = stats.get("queue", {})
    print(
        "{}: type={} events={} bytes={} max={}".format(
            pipeline_id,
            queue.get("type"),
            queue.get("events_count"),
            queue.get("queue_size_in_bytes"),
            queue.get("max_queue_size_in_bytes"),
        )
    )
'
done

echo
echo "=== Registres Filebeat ==="
if docker inspect oculox-filebeat-1 >/dev/null 2>&1; then
    docker exec oculox-filebeat-1 sh -c \
        'for directory in /usr/share/filebeat-*/data; do du -sh "$directory" 2>/dev/null; done'
else
    echo "Conteneur Filebeat absent."
fi

echo
echo "=== Disque hôte ==="
df -h .
