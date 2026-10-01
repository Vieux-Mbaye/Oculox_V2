#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "${SCRIPT_DIR}/../../.." && pwd)"
EJBCA_DIR="${PROJECT_DIR}/dev/ejbca"
COMPOSE_FILE="${EJBCA_DIR}/compose/docker-compose.ejbca.yml"
EXAMPLE_ENV="${EJBCA_DIR}/config/ejbca.env.example"
GENERATED_DIR="${EJBCA_DIR}/generated"
ENV_FILE="${GENERATED_DIR}/ejbca.env"
ADMIN_DIR="${GENERATED_DIR}/admin"

usage() {
    cat <<'EOF'
Usage: ./oculox pki-ca <commande>

Commandes:
  init       Cree le fichier runtime dev/ejbca/generated/ejbca.env
  config     Valide la syntaxe Docker Compose EJBCA
  pull       Telecharge les images EJBCA et base de donnees
  start      Demarre EJBCA localement
  stop       Arrete EJBCA localement
  restart    Redemarre EJBCA localement
  status     Affiche l'etat des conteneurs EJBCA
  logs       Affiche les logs EJBCA
  validate   Valide env, compose, conteneurs et plan CA
  ca-plan    Valide le plan CA/profils EJBCA
  create-ca-plan
             Cree dans EJBCA les CA Oculox declarees dans le plan
  harden     Cree un admin par certificat et retire l acces public bootstrap
  verify-hardening
             Verifie que l acces public bootstrap est retire
  provision-profiles
             Cree les profils EJBCA Oculox a CA et usages controles
  configure-api --public-host <IP-ou-DNS>
             Publie l API EJBCA avec certificat TLS signe et verifie

EJBCA est separe du runtime Oculox principal. Il tourne sur la meme machine que
le Core, mais il ne doit pas etre requis pour ./oculox start.
EOF
}

compose() {
    docker compose \
        --project-directory "$PROJECT_DIR" \
        --env-file "$ENV_FILE" \
        -f "$COMPOSE_FILE" \
        "$@"
}

require_env() {
    if [[ ! -s "$ENV_FILE" ]]; then
        printf 'Configuration EJBCA absente. Lancez ./oculox pki-ca init\n' >&2
        exit 1
    fi
}

load_runtime_env() {
    require_env
    ensure_env_defaults
    local key value
    while IFS='=' read -r key value || [[ -n "$key" ]]; do
        [[ -n "$key" && "$key" != \#* ]] || continue
        case "$key" in
            EJBCA_CA_TOKEN_PASSWORD|EJBCA_ADMIN_USERNAME|EJBCA_ADMIN_CN|EJBCA_ADMIN_DN|EJBCA_ADMIN_CA|EJBCA_ADMIN_PASSWORD|OCULOX_EJBCA_BIND_ADDRESS|OCULOX_EJBCA_HTTPS_PORT)
                export "${key}=${value}"
                ;;
        esac
    done < "$ENV_FILE"
}

random_secret() {
    openssl rand -base64 36 | tr -d '\n'
}

admin_password_secret() {
    openssl rand -base64 24 | tr -d '\n'
}

init_env() {
    install -d -m 0700 "$GENERATED_DIR"
    if [[ -s "$ENV_FILE" ]]; then
        ensure_env_defaults
        printf 'Configuration EJBCA deja presente : %s\n' "$ENV_FILE"
        return
    fi
    [[ -s "$EXAMPLE_ENV" ]] || {
        printf 'Fichier exemple absent : %s\n' "$EXAMPLE_ENV" >&2
        exit 1
    }
    python3 - "$EXAMPLE_ENV" "$ENV_FILE" "$(random_secret)" "$(random_secret)" "$(random_secret)" <<'PY'
from pathlib import Path
import sys

source = Path(sys.argv[1])
destination = Path(sys.argv[2])
password = sys.argv[3]
root_password = sys.argv[4]
ca_token_password = sys.argv[5]
text = source.read_text(encoding="utf-8")
marker = "change-me-generate-with-oculox-pki-ca-init"
text = text.replace(marker, password, 1)
text = text.replace(marker, root_password, 1)
text = text.replace(marker, ca_token_password, 1)
destination.write_text(text, encoding="utf-8")
PY
    chmod 0600 "$ENV_FILE"
    printf 'Configuration EJBCA generee : %s\n' "$ENV_FILE"
}

ensure_env_defaults() {
    if ! grep -q '^EJBCA_CA_TOKEN_PASSWORD=' "$ENV_FILE"; then
        {
            printf '\n'
            printf 'EJBCA_CA_TOKEN_PASSWORD=%s\n' "$(random_secret)"
        } >> "$ENV_FILE"
        chmod 0600 "$ENV_FILE"
    fi
    if ! grep -q '^EJBCA_ADMIN_USERNAME=' "$ENV_FILE"; then
        {
            printf '\n'
            printf '# Local certificate administrator used after bootstrap hardening.\n'
            printf 'EJBCA_ADMIN_USERNAME=oculox-superadmin\n'
            printf 'EJBCA_ADMIN_CN=OculoxSuperAdmin\n'
            printf 'EJBCA_ADMIN_DN=CN=OculoxSuperAdmin,OU=Oculox PKI Administration,O=Oculox,C=SN\n'
            printf 'EJBCA_ADMIN_CA=ManagementCA\n'
            printf 'EJBCA_ADMIN_PASSWORD=%s\n' "$(admin_password_secret)"
        } >> "$ENV_FILE"
        chmod 0600 "$ENV_FILE"
    fi
}

validate_ca_plan() {
    python3 "$PROJECT_DIR/dev/scripts/ejbca/validate-ca-plan.py"
}

validate_runtime() {
    require_env
    ensure_env_defaults
    compose config --quiet
    validate_ca_plan
    if compose ps --services --status running | grep -qx ejbca; then
        compose exec -T ejbca curl -kfsS https://127.0.0.1:8443/ejbca/publicweb/healthcheck/ejbcahealth >/dev/null
        printf 'EJBCA repond en HTTPS dans le conteneur.\n'
    else
        printf 'EJBCA n est pas demarre; compose et plan CA valides.\n'
    fi
}

ejbca_cli() {
    compose exec -T ejbca /opt/keyfactor/bin/ejbca.sh "$@"
}

ejbca_running() {
    compose ps --services --status running | grep -qx ejbca
}

require_running() {
    if ! ejbca_running; then
        printf 'EJBCA n est pas demarre. Lancez ./oculox pki-ca start.\n' >&2
        exit 1
    fi
    compose exec -T ejbca curl -kfsS https://127.0.0.1:8443/ejbca/publicweb/healthcheck/ejbcahealth >/dev/null
}

ca_exists() {
    local ca_name="$1"
    ejbca_cli ca listcas | grep -F "CA Name: ${ca_name}" >/dev/null
}

ca_id() {
    local ca_name="$1"
    ejbca_cli ca listcas | awk -v name="$ca_name" '
        index($0, "CA Name: " name) { found=1; next }
        found && index($0, " Id: ") { sub(/^.* Id: /, "", $0); print $0; exit }
    '
}

create_ca() {
    local ca_name="$1"
    local subject_dn="$2"
    local validity_days="$3"
    local signed_by="${4:-}"

    if ca_exists "$ca_name"; then
        printf 'CA deja presente : %s\n' "$ca_name"
        return
    fi

    local -a args=(
        ca init
        --caname "$ca_name"
        --dn "$subject_dn"
        --tokenName "$ca_name Token"
        --tokenType soft
        --tokenPass "$EJBCA_CA_TOKEN_PASSWORD"
        --keyspec 4096
        --keytype RSA
        -v "$validity_days"
        --policy null
        -s SHA256WithRSA
    )
    if [[ -n "$signed_by" ]]; then
        args+=(--signedby "$signed_by" -certprofile SUBCA)
    else
        args+=(-certprofile ROOTCA)
    fi

    printf 'Creation CA : %s\n' "$ca_name"
    ejbca_cli "${args[@]}" >/dev/null
}

set_ca_field() {
    local ca_name="$1"
    local field="$2"
    local value="$3"
    ejbca_cli ca editca "$ca_name" "$field" "$value" >/dev/null
}

create_ca_plan() {
    load_runtime_env
    validate_ca_plan
    require_running

    create_ca \
        "Oculox Root CA" \
        "CN=Oculox Root CA,OU=Oculox PKI,O=Oculox,C=SN" \
        3650

    local root_id
    root_id="$(ca_id "Oculox Root CA")"
    [[ -n "$root_id" ]] || {
        printf 'Impossible de determiner l ID de Oculox Root CA.\n' >&2
        exit 1
    }

    create_ca \
        "Oculox Web CA" \
        "CN=Oculox Web CA,OU=Oculox Web PKI,O=Oculox,C=SN" \
        1825 \
        "$root_id"
    create_ca \
        "Oculox Internal Services CA" \
        "CN=Oculox Internal Services CA,OU=Oculox Services PKI,O=Oculox,C=SN" \
        1825 \
        "$root_id"
    create_ca \
        "Oculox OpenSearch CA" \
        "CN=Oculox OpenSearch CA,OU=Oculox OpenSearch PKI,O=Oculox,C=SN" \
        1825 \
        "$root_id"
    set_ca_field "Oculox OpenSearch CA" "doEnforceUniqueDistinguishedName" "false"

    printf 'CA Oculox presentes dans EJBCA :\n'
    ejbca_cli ca listcas | grep -E 'CA Name: (Oculox|Management)' || true
}

admin_cert_member_present() {
    ejbca_cli roles listadmins --role "Super Administrator Role" \
        | grep -F "WITH_COMMONNAME" \
        | grep -F "\"${EJBCA_ADMIN_CN}\"" >/dev/null
}

public_superadmin_present() {
    ejbca_cli roles listadmins --role "Super Administrator Role" \
        | grep -E 'PublicAccessAuthenticationToken|TRANSPORT_CONFIDENTIAL' >/dev/null
}

public_access_role_present() {
    ejbca_cli roles listroles | grep -F "'Public Access Role'" >/dev/null
}

generate_admin_certificate() {
    install -d -m 0700 "$ADMIN_DIR"
    local p12_path="${ADMIN_DIR}/${EJBCA_ADMIN_USERNAME}.p12"
    if [[ -s "$p12_path" ]]; then
        chmod 0600 "$p12_path"
        printf 'Certificat admin deja present : %s\n' "$p12_path"
        return
    fi

    printf 'Creation de l entite admin certificat : %s\n' "$EJBCA_ADMIN_USERNAME"
    if ! ejbca_cli ra addendentity \
        --username "$EJBCA_ADMIN_USERNAME" \
        --dn "$EJBCA_ADMIN_DN" \
        --caname "$EJBCA_ADMIN_CA" \
        --type 1 \
        --token P12 \
        --password "$EJBCA_ADMIN_PASSWORD" \
        --certprofile ENDUSER \
        --eeprofile EMPTY >/tmp/oculox-ejbca-addendentity.log 2>&1; then
        if ! grep -qiE 'already exists|exists already|existe' /tmp/oculox-ejbca-addendentity.log; then
            cat /tmp/oculox-ejbca-addendentity.log >&2
            exit 1
        fi
        printf 'Entite admin deja presente dans EJBCA : %s\n' "$EJBCA_ADMIN_USERNAME"
    fi

    compose exec -T ejbca rm -rf /tmp/oculox-admin-p12
    compose exec -T ejbca mkdir -p /tmp/oculox-admin-p12
    ejbca_cli ra setclearpwd "$EJBCA_ADMIN_USERNAME" --password "$EJBCA_ADMIN_PASSWORD" >/dev/null
    ejbca_cli ra setendentitystatus "$EJBCA_ADMIN_USERNAME" 10 >/dev/null
    printf 'Export du certificat client admin P12.\n'
    ejbca_cli batch \
        --username "$EJBCA_ADMIN_USERNAME" \
        -dir /tmp/oculox-admin-p12 \
        --keyalg RSA \
        --keyspec 3072 >/dev/null
    local remote_file
    remote_file="$(compose exec -T ejbca sh -lc 'ls -1 /tmp/oculox-admin-p12/*.p12 2>/dev/null | head -1' | tr -d '\r')"
    [[ -n "$remote_file" ]] || {
        printf 'Impossible de trouver le fichier P12 admin genere dans EJBCA.\n' >&2
        exit 1
    }
    docker cp "oculox-ejbca:${remote_file}" "$p12_path"
    chmod 0600 "$p12_path"
    printf 'Certificat admin exporte : %s\n' "$p12_path"
}

map_admin_certificate_role() {
    if admin_cert_member_present; then
        printf 'Role Super Administrator deja mappe au certificat CN=%s.\n' "$EJBCA_ADMIN_CN"
        return
    fi
    printf 'Mappage du certificat admin au role Super Administrator.\n'
    ejbca_cli roles addrolemember \
        --role "Super Administrator Role" \
        --caname "$EJBCA_ADMIN_CA" \
        --with CertificateAuthenticationToken:WITH_COMMONNAME \
        --value "$EJBCA_ADMIN_CN" >/dev/null
}

install_admin_ca_in_tls_truststore() {
    local ca_file="/tmp/oculox-admin-ca.pem"
    local truststore="/opt/keyfactor/wildfly-39.0.1.Final/standalone/configuration/truststore.p12"
    local truststore_password

    truststore_password="$(compose exec -T ejbca sh -lc "grep -o 'key-store name=\"httpsTS\".*' /opt/keyfactor/wildfly-39.0.1.Final/standalone/configuration/standalone.xml >/dev/null; sed -n '/<key-store name=\"httpsTS\"/,/<\\/key-store>/p' /opt/keyfactor/wildfly-39.0.1.Final/standalone/configuration/standalone.xml | sed -n 's/.*clear-text=\"\\([^\"]*\\)\".*/\\1/p' | head -1" | tr -d '\r')"
    [[ -n "$truststore_password" ]] || {
        printf 'Impossible de determiner le mot de passe de la truststore HTTPS EJBCA.\n' >&2
        exit 1
    }

    ejbca_cli ca getcacert "$EJBCA_ADMIN_CA" "$ca_file" >/dev/null
    if compose exec -T ejbca keytool -list \
        -storetype PKCS12 \
        -keystore "$truststore" \
        -storepass "$truststore_password" \
        -alias oculox-admin-ca >/dev/null 2>&1; then
        printf 'CA admin deja presente dans la truststore TLS EJBCA.\n'
        return
    fi

    printf 'Ajout de %s dans la truststore TLS EJBCA.\n' "$EJBCA_ADMIN_CA"
    compose exec -T ejbca keytool -importcert \
        -noprompt \
        -trustcacerts \
        -alias oculox-admin-ca \
        -file "$ca_file" \
        -storetype PKCS12 \
        -keystore "$truststore" \
        -storepass "$truststore_password" >/dev/null
}

remove_public_bootstrap_access() {
    if public_superadmin_present; then
        printf 'Suppression du membre public dans Super Administrator Role.\n'
        ejbca_cli roles removeadmin \
            --role "Super Administrator Role" \
            --caname "" \
            --with PublicAccessAuthenticationToken:TRANSPORT_CONFIDENTIAL \
            --value "" >/dev/null
    else
        printf 'Aucun membre public dans Super Administrator Role.\n'
    fi

    if public_access_role_present; then
        printf 'Suppression du role Public Access Role.\n'
        ejbca_cli roles removerole --role "Public Access Role" >/dev/null
    else
        printf 'Role Public Access Role absent.\n'
    fi
}

verify_hardening() {
    load_runtime_env
    require_running

    local failed=0
    if admin_cert_member_present; then
        printf 'ADMIN CERT ROLE        OK\n'
    else
        printf 'ADMIN CERT ROLE        FAIL\n' >&2
        failed=1
    fi
    if public_superadmin_present; then
        printf 'PUBLIC SUPERADMIN      FAIL\n' >&2
        failed=1
    else
        printf 'PUBLIC SUPERADMIN      OK\n'
    fi
    if public_access_role_present; then
        printf 'PUBLIC ACCESS ROLE     FAIL\n' >&2
        failed=1
    else
        printf 'PUBLIC ACCESS ROLE     OK\n'
    fi
    if [[ -s "${ADMIN_DIR}/${EJBCA_ADMIN_USERNAME}.p12" ]]; then
        printf 'ADMIN P12 EXPORT       OK\n'
    else
        printf 'ADMIN P12 EXPORT       FAIL\n' >&2
        failed=1
    fi
    local bind_address="${OCULOX_EJBCA_BIND_ADDRESS:-127.0.0.1}"
    local https_port="${OCULOX_EJBCA_HTTPS_PORT:-18443}"
    local check_host="$bind_address"
    if [[ "$check_host" == "0.0.0.0" || "$check_host" == "::" ]]; then
        check_host="127.0.0.1"
    fi
    if curl -ksS "https://${check_host}:${https_port}/ejbca/adminweb/" \
        | grep -qE 'Authorization Denied|Aucun certificat client|No client certificate|承認拒否'; then
        printf 'WEB WITHOUT CERT       OK\n'
    else
        printf 'WEB WITHOUT CERT       FAIL\n' >&2
        failed=1
    fi
    local tmp_dir cert_pem key_pem
    tmp_dir="$(mktemp -d)"
    cert_pem="${tmp_dir}/admin-cert.pem"
    key_pem="${tmp_dir}/admin-key.pem"
    if openssl pkcs12 \
        -in "${ADMIN_DIR}/${EJBCA_ADMIN_USERNAME}.p12" \
        -clcerts \
        -nokeys \
        -out "$cert_pem" \
        -passin "pass:${EJBCA_ADMIN_PASSWORD}" >/dev/null 2>&1 \
        && openssl pkcs12 \
            -in "${ADMIN_DIR}/${EJBCA_ADMIN_USERNAME}.p12" \
            -nocerts \
            -nodes \
            -out "$key_pem" \
            -passin "pass:${EJBCA_ADMIN_PASSWORD}" >/dev/null 2>&1 \
        && curl -ksS \
            --cert "$cert_pem" \
            --key "$key_pem" \
            "https://${check_host}:${https_port}/ejbca/adminweb/" \
            | grep -q "Welcome ${EJBCA_ADMIN_CN}"; then
        printf 'WEB WITH ADMIN CERT    OK\n'
    else
        printf 'WEB WITH ADMIN CERT    FAIL\n' >&2
        failed=1
    fi
    rm -rf "$tmp_dir"
    return "$failed"
}

harden_ejbca() {
    load_runtime_env
    require_running

    generate_admin_certificate
    map_admin_certificate_role
    install_admin_ca_in_tls_truststore
    if ! admin_cert_member_present; then
        printf 'Blocage securite : le certificat admin n est pas mappe, acces public conserve.\n' >&2
        exit 1
    fi
    remove_public_bootstrap_access
    verify_hardening
    printf '\nEJBCA durci. Importez %s dans le navigateur pour l administration Web.\n' "${ADMIN_DIR}/${EJBCA_ADMIN_USERNAME}.p12"
    printf 'Le mot de passe P12 est dans %s, variable EJBCA_ADMIN_PASSWORD.\n' "$ENV_FILE"
}

COMMAND="${1:-}"
shift || true

case "$COMMAND" in
    init)
        init_env
        ;;
    config)
        require_env
        compose config --quiet
        validate_ca_plan
        printf 'Configuration EJBCA valide.\n'
        ;;
    pull)
        init_env
        compose pull "$@"
        ;;
    start)
        init_env
        compose up -d --wait --wait-timeout 600
        compose ps
        ;;
    stop)
        require_env
        compose down
        ;;
    restart)
        require_env
        compose up -d --force-recreate --wait --wait-timeout 600
        compose ps
        ;;
    status)
        require_env
        compose ps
        ;;
    logs)
        require_env
        compose logs --tail 200 "$@"
        ;;
    validate)
        validate_runtime
        ;;
    ca-plan)
        validate_ca_plan
        ;;
    create-ca-plan)
        create_ca_plan
        ;;
    provision-profiles)
        python3 "$SCRIPT_DIR/provision-profiles.py" "$@"
        ;;
    configure-api)
        python3 "$SCRIPT_DIR/configure-api.py" "$@"
        ;;
    harden)
        harden_ejbca
        ;;
    verify-hardening)
        verify_hardening
        ;;
    -h|--help|help)
        usage
        ;;
    *)
        usage >&2
        exit 2
        ;;
esac
