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
  dual-core
          Démarre OpenSearch, Logstash et Logstash 2 avec la surcharge locale.
  dual-ingest
          Prépare TLS puis démarre OpenSearch, Filebeat et les deux Logstash.
  single-ingest
          Prépare TLS puis démarre OpenSearch, Filebeat et un seul Logstash.
  dual-stop
          Arrête la composition locale à deux Logstash sans supprimer les volumes.
  full    Démarre la plateforme Malcolm complète pour les tests.
  status  Affiche les conteneurs Oculox actifs et l'état de la mémoire.
  check   Valide la configuration Compose sans démarrer de conteneur.
EOF
}

compose_dev() {
    docker compose \
        --project-directory "$PROJECT_DIR" \
        -f "$PROJECT_DIR/docker-compose.yml" \
        -f "$PROJECT_DIR/dev/compose/docker-compose.dev.yml" \
        "$@"
}

compose_single() {
    docker compose \
        --project-directory "$PROJECT_DIR" \
        -f "$PROJECT_DIR/docker-compose.yml" \
        -f "$PROJECT_DIR/dev/compose/docker-compose.dev.yml" \
        -f "$PROJECT_DIR/dev/compose/docker-compose.single-logstash.yml" \
        "$@"
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
        # La composition officielle ne connaît pas logstash-2. La surcharge
        # locale doit donc participer à l'arrêt pour ne laisser aucun service
        # de développement actif. Les volumes nommés sont conservés.
        compose_dev --profile malcolm down
        show_status
        ;;
    core)
        docker compose --profile malcolm up -d opensearch logstash
        show_status
        ;;
    dual-core)
        ./dev/scripts/prepare-phase6.sh
        compose_dev --profile malcolm up -d opensearch logstash logstash-2
        show_status
        ;;
    dual-ingest)
        ./dev/scripts/prepare-phase6.sh
        compose_dev --profile malcolm up -d opensearch logstash logstash-2 filebeat
        show_status
        ;;
    single-ingest)
        ./dev/scripts/prepare-phase6.sh
        # Un ancien mode dual peut avoir laissé le second conteneur actif.
        # Il est explicitement arrêté pour garantir un vrai mode simple.
        compose_dev --profile malcolm stop logstash-2 >/dev/null 2>&1 || true
        compose_single --profile malcolm up -d opensearch logstash filebeat
        show_status
        ;;
    dual-stop)
        compose_dev --profile malcolm down
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
