#!/usr/bin/env bash

set -e

# L'image Malcolm force le mode mono-noeud avec une variable ENV dont le nom
# contient un point. Bash ne peut pas la retirer avec unset, env -u le peut.
# OpenSearch active nativement la decouverte multi-noeud lorsqu'elle est absente.
exec env -u 'discovery.type' /usr/local/bin/docker-uid-gid-setup.sh \
  /usr/local/bin/service_check_passthrough.sh -s opensearch "$@"
