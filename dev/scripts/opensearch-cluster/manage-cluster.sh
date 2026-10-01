#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "$SCRIPT_DIR/../../.." && pwd)"
COMPOSE_FILE="$PROJECT_DIR/dev/compose/opensearch-cluster/compose.yml"
BOOTSTRAP_FILE="$PROJECT_DIR/dev/compose/opensearch-cluster/compose.bootstrap.yml"
GENERATED_DIR="$PROJECT_DIR/dev/generated/opensearch-cluster"
ENV_FILE="$GENERATED_DIR/cluster.env"
CONFIG_FILE="$GENERATED_DIR/cluster.yml"
PKI_DIR="$GENERATED_DIR/pki"
SECURITY_DIR="$GENERATED_DIR/security"
IDP_TRUST_DIR="$GENERATED_DIR/idp-trust"
STATE_DIR="$GENERATED_DIR/state"
ACCOUNTS_ENV="$SECURITY_DIR/accounts.env"
CA_FILE="$PKI_DIR/client-trust/oculox-opensearch-ca.crt"
OPERATOR="${SUDO_USER:-$(id -un)}"
ORIGINAL_ARGS=("$@")

usage() {
  cat <<'EOF'
Gestion du cluster OpenSearch Oculox

  ./oculox install cluster --endpoint-ip <adresse-IP> [--heap 2g]
  ./oculox install cluster --config <cluster.yml> [--endpoint-ip <adresse-IP>]
  ./oculox cluster start
  ./oculox cluster prepare-host
  ./oculox cluster stop
  ./oculox cluster restart
  ./oculox cluster status
  ./oculox cluster logs [service]
  ./oculox cluster validate
  ./oculox cluster config
  ./oculox cluster apply --config <cluster.yml>
  ./oculox cluster configure-oidc --keycloak-auth-url <URL> [--realm oculox] [--keycloak-ca <ca.crt>]
  ./oculox cluster oidc-trust
  ./oculox cluster verify-oidc
  ./oculox cluster client-bundle core <sortie>
  ./oculox cluster client-bundle hedgehog <sortie>
  ./oculox cluster pki-migrate status|trust|leaf|retire|rotate|rollback [--check] [--backup DIR]

La commande install est réexécutable après une interruption. Elle ne supprime
jamais les volumes de données et ne remplace jamais une PKI existante.
EOF
}

compose() {
  docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

compose_bootstrap() {
  docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" -f "$BOOTSTRAP_FILE" "$@"
}

require_runtime_state() {
  [[ -s "$ENV_FILE" ]] || {
    printf 'Cluster non installé. Exécutez ./oculox install cluster --endpoint-ip <IP>.\n' >&2
    exit 1
  }
}

ensure_docker_access() {
  if docker info >/dev/null 2>&1; then
    return
  fi
  if sudo docker info >/dev/null 2>&1; then
    exec sudo -u "$OPERATOR" -g docker -- "$PROJECT_DIR/oculox" cluster "${ORIGINAL_ARGS[@]}"
  fi
  printf 'Docker est installé mais son service ne répond pas. Vérifiez systemctl status docker.\n' >&2
  exit 1
}

render_config() {
  local output_env="$1" output_config="$2" config_path="$3" endpoint_ip="$4" heap="$5"
  local args=(
    --output-env "$output_env"
    --output-config "$output_config"
    --proxy-uid "$(id -u "$OPERATOR")"
    --proxy-gid "$(id -g "$OPERATOR")"
  )
  [[ -z "$config_path" ]] || args+=(--config "$config_path")
  [[ -z "$endpoint_ip" ]] || args+=(--endpoint-ip "$endpoint_ip")
  [[ -z "$heap" ]] || args+=(--heap "$heap")
  "$SCRIPT_DIR/render-cluster-config.py" "${args[@]}"
}

env_value() {
  sed -n "s/^$1=//p" "$ENV_FILE"
}

wait_for_nodes() {
  local attempt healthy node
  for attempt in $(seq 1 120); do
    healthy=0
    for node in opensearch-1 opensearch-2 opensearch-3; do
      if [[ "$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "oculox-opensearch-cluster-${node}-1" 2>/dev/null || true)" == healthy ]]; then
        healthy=$((healthy + 1))
      fi
    done
    if [[ "$healthy" == 3 ]]; then
      return
    fi
    sleep 2
  done
  printf 'Les trois nœuds OpenSearch ne sont pas opérationnels.\n' >&2
  compose ps >&2
  exit 1
}

wait_for_endpoint() {
  local endpoint password
  endpoint="$(env_value OPENSEARCH_CLUSTER_ENDPOINT)"
  password="$(sed -n 's/^OCULOX_PLATFORM_ADMIN_PASSWORD=//p' "$ACCOUNTS_ENV")"
  for _ in $(seq 1 150); do
    if curl --silent --fail --max-time 5 --cacert "$CA_FILE" \
      --user "oculox_platform_admin:$password" \
      "$endpoint/_cluster/health?wait_for_status=yellow&timeout=3s" >/dev/null 2>&1; then
      return
    fi
    sleep 2
  done
  printf 'L’endpoint OpenSearch n’est pas devenu disponible.\n' >&2
  exit 1
}

wait_for_cluster_green() {
  local endpoint password response
  endpoint="$(env_value OPENSEARCH_CLUSTER_ENDPOINT)"
  password="$(sed -n 's/^OCULOX_PLATFORM_ADMIN_PASSWORD=//p' "$ACCOUNTS_ENV")"
  for _ in $(seq 1 180); do
    response="$(curl --silent --fail --max-time 8 --cacert "$CA_FILE" \
      --user "oculox_platform_admin:$password" \
      "$endpoint/_cluster/health" 2>/dev/null || true)"
    if python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["status"] == "green"; assert d["number_of_nodes"] == 3; assert d["unassigned_shards"] == 0' <<<"$response" 2>/dev/null; then
      return
    fi
    sleep 2
  done
  printf 'Le cluster n’est pas revenu à green avec trois nœuds.\n' >&2
  exit 1
}

recreate_endpoint() {
  compose up -d --no-deps --force-recreate opensearch-endpoint
}

check_host_capacity() {
  local profile="$1" memory_kib cpu_count disk_kib min_memory_mib min_disk_gib failures=0
  if [[ "$profile" == lab ]]; then
    min_memory_mib=6144
    min_disk_gib=25
  else
    min_memory_mib=12288
    min_disk_gib=100
  fi
  memory_kib="$(awk '/^MemTotal:/ {print $2}' /proc/meminfo)"
  cpu_count="$(getconf _NPROCESSORS_ONLN)"
  disk_kib="$(df -Pk "$PROJECT_DIR" | awk 'NR == 2 {print $4}')"
  if ((memory_kib < min_memory_mib * 1024)); then
    printf 'RAM insuffisante pour le profil %s : %d Mio disponibles, %d Mio requis.\n' "$profile" "$((memory_kib / 1024))" "$min_memory_mib" >&2
    failures=$((failures + 1))
  fi
  if ((cpu_count < 4)); then
    printf 'CPU insuffisants : %d disponibles, 4 requis.\n' "$cpu_count" >&2
    failures=$((failures + 1))
  fi
  if ((disk_kib < min_disk_gib * 1048576)); then
    printf 'Disque insuffisant pour le profil %s : %d Gio libres, %d Gio requis.\n' "$profile" "$((disk_kib / 1048576))" "$min_disk_gib" >&2
    failures=$((failures + 1))
  fi
  ((failures == 0)) || exit 1
}

check_endpoint_bindings() {
  local endpoint_ip="$1" endpoint_port="$2" monitoring_port="$3" octet port
  IFS=. read -r -a octets <<<"$endpoint_ip"
  for octet in "${octets[@]}"; do
    ((10#$octet <= 255)) || { printf 'Adresse IPv4 invalide : %s\n' "$endpoint_ip" >&2; exit 2; }
  done
  ip -o -4 address show | awk '{print $4}' | cut -d/ -f1 | grep -Fxq "$endpoint_ip" || {
    printf 'L’adresse %s n’est attribuée à aucune interface locale.\n' "$endpoint_ip" >&2
    exit 1
  }
  if [[ ! -s "$ENV_FILE" ]]; then
    for port in "$endpoint_port" "$monitoring_port"; do
      if ss -H -lnt "sport = :$port" | grep -q .; then
        printf 'Le port TCP %s est déjà utilisé sur cet hôte.\n' "$port" >&2
        exit 1
      fi
    done
  fi
}

ensure_ejbca_opensearch_pki() {
  local -a entries=(
    opensearch_node_1
    opensearch_node_2
    opensearch_node_3
    opensearch_admin_client
    opensearch_endpoint
  )
  local entry

  [[ -s "$PROJECT_DIR/dev/generated/pki/remote-agent/config.json" ]] || {
    printf '%s\n' 'Agent PKI Cluster absent. Exécutez ./oculox pki agent-init, puis faites autoriser sa CSR sur le Core.' >&2
    exit 1
  }
  printf '%s\n' 'Enrolement PKI OpenSearch via EJBCA distant...'
  for entry in "${entries[@]}"; do
    if [[ ! -s "$(python3 - "$PROJECT_DIR" "$entry" <<'PY'
from pathlib import Path
import sys, yaml
root = Path(sys.argv[1])
with (root / 'dev/ejbca/pki-manifest.yml').open(encoding='utf-8') as stream:
    manifest = yaml.safe_load(stream)
print(root / manifest['certificates'][sys.argv[2]]['cert'])
PY
)" ]]; then
      "$PROJECT_DIR/oculox" pki request --service "$entry" --install
    fi
  done
  install -d -m 0700 "$PKI_DIR/ca" "$PKI_DIR/client-trust"
  install -m 0644 "$PROJECT_DIR/dev/generated/pki/remote-agent/service-ca.crt" "$PKI_DIR/ca/ca.crt"
  install -m 0644 "$PROJECT_DIR/dev/generated/pki/remote-agent/service-ca.crt" "$CA_FILE"
  # Web trust is separate from the CA signing OpenSearch certificates.
  install -d -m 0755 "$IDP_TRUST_DIR"
  if [[ ! -s "$IDP_TRUST_DIR/keycloak-ca.crt" ]]; then
    install -m 0644 "$PROJECT_DIR/dev/generated/pki/remote-agent/api-ca.crt" "$IDP_TRUST_DIR/keycloak-ca.crt"
  elif ! cmp -s "$PROJECT_DIR/dev/generated/pki/remote-agent/api-ca.crt" "$IDP_TRUST_DIR/keycloak-ca.crt"; then
    printf '%s\n' 'Confiance Keycloak obsolete: executer ./oculox cluster oidc-trust avant de reprendre.' >&2
    exit 1
  fi
  [[ ! -e "$PKI_DIR/ca/ca.key" ]] || {
    printf '%s\n' 'Cle de CA locale detectee: migration explicite requise, installation refusee.' >&2
    exit 1
  }
  {
    printf 'provider=ejbca\n'
    printf 'issuer=Oculox OpenSearch CA\n'
    printf 'endpoint=%s\n' "$(env_value OPENSEARCH_CLUSTER_ENDPOINT)"
    printf 'generated_at=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  } > "$PKI_DIR/manifest.txt"
  chmod 0600 "$PKI_DIR/manifest.txt"
  touch "$PKI_DIR/.oculox-opensearch-pki"
  chmod 0600 "$PKI_DIR/.oculox-opensearch-pki"
}

create_default_bundles() {
  local endpoint output role
  endpoint="$(env_value OPENSEARCH_CLUSTER_ENDPOINT)"
  for role in core hedgehog; do
    output="$GENERATED_DIR/client-bundles/$role"
    if [[ ! -e "$output" ]]; then
      "$SCRIPT_DIR/create-client-bundle.py" --role "$role" --endpoint "$endpoint" --output "$output"
    fi
  done
}

apply_cluster_config() {
  local config_path="" candidate_dir candidate_env candidate_config current_endpoint requested_endpoint
  shift
  while (($#)); do
    case "$1" in
      --config) shift; config_path="${1:-}" ;;
      *) printf 'Option inconnue : %s\n' "$1" >&2; usage; exit 2 ;;
    esac
    shift
  done
  [[ -n "$config_path" && -f "$config_path" ]] || {
    printf '%s\n' './oculox cluster apply exige --config <cluster.yml>.' >&2
    exit 2
  }
  require_runtime_state
  ensure_docker_access
  candidate_dir="$(mktemp -d)"
  candidate_env="$candidate_dir/cluster.env"
  candidate_config="$candidate_dir/cluster.yml"
  render_config "$candidate_env" "$candidate_config" "$config_path" "" ""
  current_endpoint="$(env_value OPENSEARCH_CLUSTER_ENDPOINT)"
  requested_endpoint="$(sed -n 's/^OPENSEARCH_CLUSTER_ENDPOINT=//p' "$candidate_env")"
  [[ "$current_endpoint" == "$requested_endpoint" ]] || {
    printf 'Le changement d’endpoint %s -> %s exige une migration explicite.\n' "$current_endpoint" "$requested_endpoint" >&2
    exit 1
  }
  [[ "$(env_value OPENSEARCH_CLUSTER_NAME)" == "$(sed -n 's/^OPENSEARCH_CLUSTER_NAME=//p' "$candidate_env")" ]] || {
    printf '%s\n' 'Le nom d’un cluster existant ne peut pas être modifié par apply.' >&2
    exit 1
  }
  install -m 0600 "$candidate_env" "$ENV_FILE"
  install -m 0600 "$candidate_config" "$CONFIG_FILE"
  "$SCRIPT_DIR/render-endpoint-proxy-config.sh"
  compose config --quiet
  compose pull
  compose up -d
  wait_for_endpoint
  # Reconcile templates and existing index settings before requiring green.
  # This is what releases replicas stranded by a legacy per-index shard cap.
  "$SCRIPT_DIR/apply-storage-policy.py" --env-file "$ENV_FILE"
  wait_for_cluster_green
  create_default_bundles
  compose ps
  rm -rf -- "$candidate_dir"
  printf '%s\n' 'Configuration du cluster appliquée.'
}

configure_oidc() {
  shift
  require_runtime_state
  ensure_docker_access
  python3 "$SCRIPT_DIR/oidc-trust.py" configure "$@"
}

install_cluster() {
  local endpoint_ip="" heap="" config_path="" check_only=false
  local candidate_dir candidate_env candidate_config configured_ip configured_port monitoring_port profile
  shift
  while (($#)); do
    case "$1" in
      --endpoint-ip) shift; endpoint_ip="${1:-}" ;;
      --heap) shift; heap="${1:-}" ;;
      --config) shift; config_path="${1:-}" ;;
      --check) check_only=true ;;
      *) printf 'Option inconnue : %s\n' "$1" >&2; usage; exit 2 ;;
    esac
    shift
  done
  [[ -z "$config_path" || -f "$config_path" ]] || {
    printf 'Fichier de configuration absent : %s\n' "$config_path" >&2
    exit 2
  }
  [[ -z "$heap" || "$heap" =~ ^[1-9][0-9]*[gGmM]$ ]] || {
    printf '%s\n' '--heap doit utiliser un format tel que 2g ou 2048m.' >&2
    exit 2
  }

  if [[ "$check_only" == false ]]; then
    check_host_capacity lab
    sudo "$SCRIPT_DIR/prepare-host.py" --operator "$OPERATOR" --dependencies-only
  elif ! python3 -c 'import yaml' >/dev/null 2>&1; then
    printf '%s\n' 'PyYAML est requis pour --check. Installez python3-yaml ou lancez l’installation complète.' >&2
    exit 1
  fi

  candidate_dir="$(mktemp -d)"
  candidate_env="$candidate_dir/cluster.env"
  candidate_config="$candidate_dir/cluster.yml"
  render_config "$candidate_env" "$candidate_config" "$config_path" "$endpoint_ip" "$heap"
  configured_ip="$(sed -n 's/^OPENSEARCH_ENDPOINT_BIND_IP=//p' "$candidate_env")"
  configured_port="$(sed -n 's/^OPENSEARCH_ENDPOINT_PORT=//p' "$candidate_env")"
  monitoring_port="$(sed -n 's/^OPENSEARCH_MONITORING_PORT=//p' "$candidate_env")"
  profile="$(sed -n 's/^OCULOX_CLUSTER_PROFILE=//p' "$candidate_env")"
  check_host_capacity "$profile"
  check_endpoint_bindings "$configured_ip" "$configured_port" "$monitoring_port"

  if [[ -s "$ENV_FILE" ]]; then
    [[ "$(env_value OPENSEARCH_CLUSTER_ENDPOINT)" == "$(sed -n 's/^OPENSEARCH_CLUSTER_ENDPOINT=//p' "$candidate_env")" ]] || {
      printf 'L’installation existante utilise l’endpoint %s. Une migration explicite est requise pour le modifier.\n' "$(env_value OPENSEARCH_CLUSTER_ENDPOINT)" >&2
      exit 1
    }
  fi

  if [[ "$check_only" == true ]]; then
    ensure_docker_access
    docker compose --env-file "$candidate_env" -f "$COMPOSE_FILE" config --quiet
    "$SCRIPT_DIR/render-cluster-config.py" --config "$candidate_config" --print
    rm -rf -- "$candidate_dir"
    printf '%s\n' 'CLUSTER_CONFIGURATION_CHECK=PASS'
    return
  fi

  sudo "$SCRIPT_DIR/prepare-host.py" --operator "$OPERATOR"
  ensure_docker_access

  install -d -m 0700 "$GENERATED_DIR"
  install -d -m 0755 "$IDP_TRUST_DIR"
  install -m 0600 "$candidate_env" "$ENV_FILE"
  install -m 0600 "$candidate_config" "$CONFIG_FILE"

  ensure_ejbca_opensearch_pki
  [[ -d "$SECURITY_DIR" ]] || "$SCRIPT_DIR/generate-security-config.sh"
  "$SCRIPT_DIR/render-endpoint-proxy-config.sh"
  compose config --quiet
  compose pull

  if [[ ! -s "$STATE_DIR/security-initialized" ]]; then
    compose_bootstrap up -d opensearch-1 opensearch-2 opensearch-3
    wait_for_nodes
    "$SCRIPT_DIR/initialize-security.sh" --admin-dir "$PKI_DIR/admin"
    recreate_endpoint
    wait_for_endpoint
    for node in opensearch-1 opensearch-2 opensearch-3; do
      compose up -d --no-deps --force-recreate "$node"
      wait_for_endpoint
    done
  fi

  compose up -d
  recreate_endpoint
  wait_for_endpoint
  wait_for_cluster_green
  "$SCRIPT_DIR/apply-storage-policy.py" --env-file "$ENV_FILE"
  create_default_bundles
  compose ps
  rm -rf -- "$candidate_dir"
  printf 'Cluster installé. Bundles clients : %s/client-bundles/{core,hedgehog}\n' "$GENERATED_DIR"
}

COMMAND="${1:-}"
case "$COMMAND" in
  prepare-host)
    sudo "$SCRIPT_DIR/prepare-host.py" --operator "$OPERATOR"
    printf '%s\n' 'Ouvrez une nouvelle session si le groupe Docker vient d etre attribue.'
    ;;
  install)
    install_cluster "$@"
    ;;
  start)
    require_runtime_state; ensure_docker_access; compose up -d; recreate_endpoint; wait_for_endpoint; wait_for_cluster_green; compose ps
    ;;
  stop)
    require_runtime_state; ensure_docker_access; compose down
    ;;
  restart)
    require_runtime_state; ensure_docker_access; compose up -d --force-recreate; wait_for_endpoint; wait_for_cluster_green; compose ps
    ;;
  status)
    require_runtime_state; ensure_docker_access; compose ps
    ;;
  logs)
    require_runtime_state; ensure_docker_access; shift; compose logs --tail 200 "$@"
    ;;
  validate)
    require_runtime_state; ensure_docker_access
    compose config --quiet
    OPENSEARCH_CLUSTER_ENV_FILE="$ENV_FILE" python3 "$PROJECT_DIR/dev/tests/opensearch-cluster/test_compose_structure.py"
    OPENSEARCH_CLUSTER_ENV_FILE="$ENV_FILE" python3 "$PROJECT_DIR/dev/tests/opensearch-cluster/test_discovery_config.py"
    OPENSEARCH_CLUSTER_ENV_FILE="$ENV_FILE" python3 "$PROJECT_DIR/dev/tests/opensearch-cluster/test_pki.py"
    python3 "$PROJECT_DIR/dev/tests/opensearch-cluster/test_security_config.py"
    OPENSEARCH_CLUSTER_ENV_FILE="$ENV_FILE" python3 "$PROJECT_DIR/dev/tests/opensearch-cluster/test_endpoint_proxy.py"
    python3 "$SCRIPT_DIR/oidc-trust.py" verify --if-configured
    ;;
  config)
    require_runtime_state
    [[ -s "$CONFIG_FILE" ]] || { printf 'Configuration normalisée absente : %s\n' "$CONFIG_FILE" >&2; exit 1; }
    cat "$CONFIG_FILE"
    ;;
  apply)
    apply_cluster_config "$@"
    ;;
  configure-oidc)
    configure_oidc "$@"
    ;;
  oidc-trust|verify-oidc)
    require_runtime_state; ensure_docker_access
    action=trust
    [[ "$1" != verify-oidc ]] || action=verify
    shift
    python3 "$SCRIPT_DIR/oidc-trust.py" "$action" "$@"
    ;;
  client-bundle)
    require_runtime_state
    role="${2:-}"; output="${3:-}"
    [[ "$role" == core || "$role" == hedgehog ]] || { usage; exit 2; }
    [[ -n "$output" ]] || { usage; exit 2; }
    "$SCRIPT_DIR/create-client-bundle.py" --role "$role" \
      --endpoint "$(env_value OPENSEARCH_CLUSTER_ENDPOINT)" --output "$output"
    ;;
  pki-migrate)
    shift
    python3 "$SCRIPT_DIR/migrate-ejbca.py" "$@"
    ;;
  *) usage; exit 2 ;;
esac
