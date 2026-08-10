#!/usr/bin/env bash
set -euo pipefail

PROJECT_SOURCE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
TEST_ROOT="$(mktemp -d)"
trap 'rm -rf "$TEST_ROOT"' EXIT

mkdir -p \
    "$TEST_ROOT/bin" \
    "$TEST_ROOT/project/dev/compose" \
    "$TEST_ROOT/project/dev/generated" \
    "$TEST_ROOT/project/scripts"
cp "$PROJECT_SOURCE/oculox" "$TEST_ROOT/project/oculox"
chmod +x "$TEST_ROOT/project/oculox"
touch "$TEST_ROOT/project/docker-compose.yml"
touch "$TEST_ROOT/project/dev/compose/docker-compose.dev.yml"
printf 'OCULOX_ROLE=principal\n' > "$TEST_ROOT/project/dev/generated/deployment.env"

cat > "$TEST_ROOT/bin/docker" <<'EOF'
#!/usr/bin/env bash
printf 'docker %s\n' "$*" >> "$OCULOX_TEST_LOG"
if [[ " $* " == *" config "* ]]; then
    printf 'services: {}\n'
fi
EOF
chmod +x "$TEST_ROOT/bin/docker"

cat > "$TEST_ROOT/project/scripts/start" <<'EOF'
#!/usr/bin/env bash
printf 'official-start %s\n' "$*" >> "$OCULOX_TEST_LOG"
EOF
chmod +x "$TEST_ROOT/project/scripts/start"

export OCULOX_TEST_LOG="$TEST_ROOT/commands.log"
PATH="$TEST_ROOT/bin:$PATH" "$TEST_ROOT/project/oculox" restart nginx-proxy >/dev/null

grep -q '^official-start ' "$OCULOX_TEST_LOG"
grep -q ' config$' "$OCULOX_TEST_LOG"
grep -q ' restart nginx-proxy$' "$OCULOX_TEST_LOG"

printf 'PASS: restart reconciles the runtime configuration before restarting services\n'
