#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"

cd "$PROJECT_DIR"

FULL_LOGO_SHA256="6d1b4ed7c79e78c4443d918e932cad09d5afd5b488dc0f0cafd593a96f16e231"
ICON_SHA256="e540553cde260589e2f2e06f2665df2988f34c2fe30812e4e577cadd6bdd8fae"

required_files=(
    dev/branding/install-nginx-branding.sh
    dev/branding/logo_Oculox.png
    dev/branding/icone_logo.png
    dashboards/opensearch_dashboards.yml
    nginx/landingpage/index.html
)

for path in "${required_files[@]}"; do
    [[ -s "$path" ]] || {
        printf 'Fichier de branding absent ou vide : %s\n' "$path" >&2
        exit 1
    }
done

check_sha256() {
    local expected="$1"
    local path="$2"
    local actual
    actual="$(sha256sum "$path" | awk '{print $1}')"
    [[ "$actual" == "$expected" ]] || {
        printf 'Visuel inattendu : %s\nAttendu : %s\nObtenu : %s\n' "$path" "$expected" "$actual" >&2
        exit 1
    }
}

check_sha256 "$FULL_LOGO_SHA256" dev/branding/logo_Oculox.png
check_sha256 "$ICON_SHA256" dev/branding/icone_logo.png
check_sha256 "$FULL_LOGO_SHA256" docs/images/logo/logo_Oculox.png

grep -q '<title>Oculox | Sécurité OT</title>' nginx/landingpage/index.html
grep -q 'class="brand-logo" src="assets/img/icone_logo.png"' nginx/landingpage/index.html
grep -q 'class="hero-logo" src="assets/img/logo_Oculox.png"' nginx/landingpage/index.html
grep -q 'class="traffic-canvas" id="trafficCanvas"' nginx/landingpage/index.html
grep -q 'class="hero-blue-glow"' nginx/landingpage/index.html
grep -q 'const buildTrafficScene = () =>' nginx/landingpage/index.html
grep -q 'window.requestAnimationFrame(animateTraffic)' nginx/landingpage/index.html
grep -q 'upload/icone_logo.png' file-upload/site/index.html
grep -q 'upload/logo_Oculox.png' file-upload/site/index.html
grep -q 'src="icone_logo.png"' htadmin/src/includes/head.php

grep -q 'applicationTitle: "Oculox Dashboards"' dashboards/opensearch_dashboards.yml
grep -q 'defaultUrl: "/assets/img/logo_Oculox.png"' dashboards/opensearch_dashboards.yml
grep -q 'defaultUrl: "/assets/img/icone_logo.png"' dashboards/opensearch_dashboards.yml
grep -q 'faviconUrl: "/assets/img/icone_logo.png"' dashboards/opensearch_dashboards.yml

if rg -n 'Talixman_logo|/assets/img/X\.png|<title>Malcolm|Welcome to Malcolm|Malcolm Configuration Menu' \
    nginx/landingpage dashboards/opensearch_dashboards.yml file-upload/site \
    htadmin/src/includes scripts/installer/ui; then
    printf 'Une ancienne identité visuelle reste référencée dans une interface.\n' >&2
    exit 1
fi

sh -n dev/branding/install-nginx-branding.sh
python3 -m py_compile \
    scripts/installer/ui/shared/splash_screen.py \
    scripts/installer/ui/gui/views/welcome_view.py

rendered="$(mktemp)"
trap 'rm -f "$rendered"' EXIT

docker compose \
    --project-directory "$PROJECT_DIR" \
    -f "$PROJECT_DIR/docker-compose.yml" \
    -f "$PROJECT_DIR/dev/compose/docker-compose.dev.yml" \
    --profile malcolm \
    config > "$rendered"

grep -q '/opt/oculox-branding/install-nginx-branding.sh' "$rendered"
grep -q '/tmp/oculox/opensearch_dashboards.orig.yml' "$rendered"
grep -q '/var/www/upload/logo_Oculox.png' "$rendered"
grep -q '/var/www/upload/icone_logo.png' "$rendered"
grep -q '/var/www/htadmin/icone_logo.png' "$rendered"

printf 'Identité visuelle Oculox et déploiement Compose validés.\n'
