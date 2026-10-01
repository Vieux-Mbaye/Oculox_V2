#!/usr/bin/env bash

set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"

usage() {
    cat <<'EOF'
Usage: install-host-telemetry-deps.sh [--project-dir <dir>]

Installe les dépendances OS nécessaires aux dashboards hôte Oculox :
Fluent Bit, auditd, AIDE, jq et les règles sudo contrôlées.
EOF
}

while (($#)); do
    case "$1" in
        --project-dir)
            shift
            PROJECT_DIR="$(cd -- "${1:-}" && pwd)"
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            printf 'Option inconnue : %s\n' "$1" >&2
            usage >&2
            exit 2
            ;;
    esac
    shift
done

[[ "$(id -u)" -eq 0 ]] || {
    printf '%s\n' 'Ce script doit être exécuté avec sudo/root.' >&2
    exit 1
}

if [[ ! -r /etc/os-release ]]; then
    printf '%s\n' '/etc/os-release introuvable : distribution non reconnue.' >&2
    exit 1
fi

# shellcheck source=/dev/null
. /etc/os-release

repo_family=""
repo_codename="${VERSION_CODENAME:-}"
case "${ID:-}" in
    ubuntu)
        repo_family="ubuntu"
        ;;
    debian)
        repo_family="debian"
        ;;
    *)
        if [[ " ${ID_LIKE:-} " == *" debian "* ]]; then
            repo_family="debian"
        fi
        ;;
esac

if [[ "$repo_family" == "debian" ]]; then
    case "$repo_codename" in
        bullseye|bookworm|trixie) ;;
        *)
            debian_major="$(sed -n 's/^\([0-9][0-9]*\).*/\1/p' /etc/debian_version 2>/dev/null | head -1 || true)"
            case "$debian_major" in
                11) repo_codename="bullseye" ;;
                12) repo_codename="bookworm" ;;
                13) repo_codename="trixie" ;;
            esac
            ;;
    esac
fi

if [[ -z "$repo_family" || -z "$repo_codename" ]]; then
    cat >&2 <<EOF
Distribution non supportée automatiquement pour Fluent Bit :
  ID=${ID:-}
  ID_LIKE=${ID_LIKE:-}
  VERSION_CODENAME=${VERSION_CODENAME:-}

Installez fluent-bit manuellement, puis relancez :
  ./oculox host-telemetry start
EOF
    exit 1
fi

if ! command -v apt-get >/dev/null 2>&1; then
    printf '%s\n' 'Installation automatique disponible seulement pour les systèmes apt Debian/Ubuntu.' >&2
    exit 1
fi

export DEBIAN_FRONTEND=noninteractive

apt-get update
apt-get install -y ca-certificates curl gnupg jq sudo aide auditd

install -d -m 0755 /etc/apt/keyrings /etc/apt/sources.list.d
gpg --dearmor --batch --yes \
    -o /etc/apt/keyrings/fluentbit.gpg \
    "$PROJECT_DIR/malcolm-iso/config/archives/fluentbit.key.chroot"

cat > /etc/apt/sources.list.d/fluentbit.list <<EOF
deb [signed-by=/etc/apt/keyrings/fluentbit.gpg] https://packages.fluentbit.io/${repo_family}/${repo_codename} ${repo_codename} main
EOF

apt-get update
apt-get install -y fluent-bit

install -m 0755 \
    "$PROJECT_DIR/malcolm-iso/config/includes.chroot/usr/local/bin/aide_integrity_check.sh" \
    /usr/local/bin/aide_integrity_check.sh
install -m 0440 \
    "$PROJECT_DIR/malcolm-iso/config/includes.chroot/etc/sudoers.d/fluent-bit" \
    /etc/sudoers.d/oculox-fluent-bit
install -m 0440 \
    "$PROJECT_DIR/malcolm-iso/config/includes.chroot/etc/sudoers.d/aide_integrity_check" \
    /etc/sudoers.d/oculox-aide-integrity-check

visudo -cf /etc/sudoers.d/oculox-fluent-bit >/dev/null
visudo -cf /etc/sudoers.d/oculox-aide-integrity-check >/dev/null

# The package may install a global fluent-bit system service. Oculox uses
# explicit per-source user services instead, so keep the vendor service quiet.
systemctl disable --now fluent-bit >/dev/null 2>&1 || true
systemctl enable --now auditd >/dev/null 2>&1 || true

if command -v aideinit >/dev/null 2>&1; then
    aideinit >/dev/null 2>&1 || true
elif command -v aide >/dev/null 2>&1; then
    aide --init >/dev/null 2>&1 || true
fi

printf 'Dépendances de télémétrie hôte installées : fluent-bit, auditd, aide, jq.\n'
