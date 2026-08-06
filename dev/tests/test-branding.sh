#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"

cd "$PROJECT_DIR"

required_files=(
    dev/branding/install-nginx-branding.sh
    dev/branding/oculox-icon.png
    docs/images/logo/logo_Oculox.png
    nginx/landingpage/index.html
)

for path in "${required_files[@]}"; do
    [[ -s "$path" ]] || {
        printf 'Fichier de branding absent ou vide : %s\n' "$path" >&2
        exit 1
    }
done

grep -q '<title>Oculox | Sécurité OT</title>' nginx/landingpage/index.html
grep -q 'assets/img/Oculox_logo.png' nginx/landingpage/index.html
grep -q 'Oculox — Import de données' file-upload/site/index.html
grep -q "Oculox — Gestion des comptes" htadmin/src/includes/head.php

if rg -n 'Talixman_logo|href="[^\"]*X\.ico"|<title>Malcolm' \
    nginx/landingpage file-upload/site htadmin/src/includes; then
    printf 'Une ancienne identité visuelle reste référencée.\n' >&2
    exit 1
fi

rendered="$(mktemp)"
trap 'rm -f "$rendered"' EXIT

docker compose \
    --project-directory "$PROJECT_DIR" \
    -f "$PROJECT_DIR/docker-compose.yml" \
    -f "$PROJECT_DIR/dev/compose/docker-compose.dev.yml" \
    --profile malcolm \
    config > "$rendered"

grep -q '/opt/oculox-branding/install-nginx-branding.sh' "$rendered"
grep -q '/opt/oculox-branding/Oculox_logo.png' "$rendered"
grep -q '/var/www/upload/Oculox_logo.png' "$rendered"
grep -q '/var/www/htadmin/Oculox_logo.png' "$rendered"

printf 'Identité visuelle Oculox et déploiement Compose validés.\n'
