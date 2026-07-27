#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"

cd "$PROJECT_DIR"

usage() {
    cat <<'EOF'
Usage: ./dev/scripts/platform-mode.sh <mode>

Modes:
  stop    Arrête proprement tous les services Oculox/Malcolm.
  core    Démarre uniquement OpenSearch et Logstash.
  full    Démarre la plateforme Malcolm complète pour les tests.
  status  Affiche les conteneurs Oculox actifs et l'état de la mémoire.
  check   Valide la configuration Compose sans démarrer de conteneur.
EOF
}

show_status() {
    printf '\nConteneurs Oculox actifs :\n'
    docker ps \
        --filter 'name=oculox-' \
        --format 'table {{.Names}}\t{{.Status}}\t{{.Image}}'

    printf '\nMémoire de l’hôte :\n'
    free -h
}

case "${1:-}" in
    stop)
        ./scripts/stop --quiet
        show_status
        ;;
    core)
        docker compose --profile malcolm up -d opensearch logstash
        show_status
        ;;
    full)
        ./scripts/start --quiet
        show_status
        ;;
    status)
        show_status
        ;;
    check)
        ./dev/scripts/validate-compose.sh
        ;;
    *)
        usage
        exit 2
        ;;
esac
