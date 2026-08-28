#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"
FAILURES=0
CREATED_ENV_FILES=()

cleanup() {
    rm -f "${CREATED_ENV_FILES[@]}"
}
trap cleanup EXIT

cd "$PROJECT_DIR"

pass() {
    printf '[PASS] %s\n' "$1"
}

fail() {
    printf '[FAIL] %s\n' "$1" >&2
    FAILURES=$((FAILURES + 1))
}

check_command() {
    if command -v "$1" >/dev/null 2>&1; then
        pass "outil disponible : $1"
    else
        fail "outil requis absent : $1"
    fi
}

printf '=== Dépendances ===\n'
for command_name in bash docker git jq openssl python3 rg; do
    check_command "$command_name"
done

printf '\n=== Version Et Hygiène Git ===\n'
if git merge-base --is-ancestor v26.07.1 HEAD; then
    pass 'la branche contient Malcolm v26.07.1'
else
    fail 'la branche ne contient pas Malcolm v26.07.1'
fi

if git diff --check; then
    pass 'aucune erreur d’espace ou de fin de ligne dans le diff'
else
    fail 'git diff --check a détecté une erreur'
fi

for forbidden_path in dev/generated dev/tests/results dev/monitoring/data; do
    if [[ -z "$(git ls-files "$forbidden_path")" ]]; then
        pass "aucun artefact versionné sous $forbidden_path"
    else
        fail "des artefacts sont versionnés sous $forbidden_path"
    fi
done

if rg -l '^-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----$' dev \
    --glob '!generated/**' \
    --glob '!tests/results/**' \
    --glob '!monitoring/data/**' >/dev/null 2>&1; then
    fail 'une clé privée est présente dans les sources livrables de dev/'
else
    pass 'aucune clé privée dans les sources livrables de dev/'
fi

printf '\n=== Syntaxe Et Configuration ===\n'
mapfile -d '' bash_files < <(find dev/scripts dev/tests -type f -name '*.sh' -print0)
if [[ -f oculox ]]; then
    bash_files+=(oculox)
fi
if ((${#bash_files[@]})) && bash -n "${bash_files[@]}"; then
    pass 'syntaxe Bash valide'
else
    fail 'syntaxe Bash invalide'
fi

if PYTHONPYCACHEPREFIX=/tmp/oculox-python-cache \
    python3 -m py_compile dev/scripts/*.py dev/tests/*.py; then
    pass 'syntaxe Python valide'
else
    fail 'syntaxe Python invalide'
fi

if python3 - <<'PY'
from pathlib import Path

import yaml


class ComposeLoader(yaml.SafeLoader):
    pass


def compose_value(loader, node):
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    return loader.construct_scalar(node)


for tag in ("!reset", "!override"):
    ComposeLoader.add_constructor(tag, compose_value)


excluded = {"generated", "results", "data"}
for path in Path("dev").rglob("*"):
    if path.suffix not in {".yml", ".yaml"}:
        continue
    if excluded.intersection(path.parts):
        continue
    yaml.load(path.read_text(encoding="utf-8"), Loader=ComposeLoader)
PY
then
    pass 'syntaxe YAML valide'
else
    fail 'syntaxe YAML invalide'
fi

for example in config/*.env.example; do
    destination="${example%.example}"
    if [[ ! -e "$destination" ]]; then
        install -m 0600 "$example" "$destination"
        CREATED_ENV_FILES+=("$destination")
    fi
done

if ./dev/scripts/validate-compose.sh; then
    pass 'configurations Compose Principal et Hedgehog valides'
else
    fail 'configuration Docker Compose invalide'
fi

if ./dev/tests/test-branding.sh; then
    pass 'identité visuelle Oculox et déploiement validés'
else
    fail 'identité visuelle Oculox invalide'
fi

cleanup
CREATED_ENV_FILES=()

printf '\n=== Protection Des Données Locales ===\n'
ignore_failures=0
for ignored_path in \
    dev/generated/pki/ca.key \
    dev/tests/results/example/result.json \
    dev/monitoring/data/example/snapshot.json \
    dev/tests/example.pcap; do
    if ! git check-ignore -q "$ignored_path"; then
        printf '[FAIL] chemin non ignoré : %s\n' "$ignored_path" >&2
        ignore_failures=$((ignore_failures + 1))
    fi
done
if ((ignore_failures == 0)); then
    pass 'clés, résultats, métriques et PCAP exclus de Git'
else
    FAILURES=$((FAILURES + ignore_failures))
fi

if find config -maxdepth 1 -type f -name '*.env' ! -perm 600 -print -quit | grep -q .; then
    fail 'au moins un fichier config/*.env n’est pas en permission 600'
else
    pass 'fichiers config/*.env protégés en permission 600'
fi

if [[ -d dev/generated/pki ]] && \
    find dev/generated/pki -maxdepth 1 -type f -name '*.key' ! -perm 600 -print -quit | grep -q .; then
    fail 'au moins une clé privée générée n’est pas en permission 600'
else
    pass 'clés privées générées protégées en permission 600'
fi

printf '\n=== État De Livraison ===\n'
if [[ -n "$(git status --short)" ]]; then
    printf '[INFO] l’arbre Git contient des changements non livrés.\n'
    git status --short
else
    pass 'arbre Git propre'
fi

if ((FAILURES > 0)); then
    printf '\nAudit en échec : %d contrôle(s) à corriger.\n' "$FAILURES" >&2
    exit 1
fi

printf '\nAudit technique réussi. Les performances de production restent à qualifier sur le serveur cible.\n'
