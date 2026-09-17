#!/usr/bin/env bash

set -euo pipefail

ADM_SCRIPT=/opt/keycloak/bin/kcadm.sh
TARGET_REALM="${KEYCLOAK_AUTH_REALM:-}"
BOOTSTRAP_REALM="${KEYCLOAK_BOOTSTRAP_REALM:-master}"
KEYCLOAK_SERVER="http://localhost:8080${KC_HTTP_RELATIVE_PATH:-/keycloak}"
ACTION="${1:-apply}"

usage() {
  printf '%s\n' 'Usage: realm-setup.sh [apply|--verify|--retire-bootstrap]' >&2
}

keycloak_requested() {
  [[ "${NGINX_AUTH_MODE:-basic}" == "keycloak" ]] || \
    [[ "${KEYCLOAK_PROVISIONING_ENABLED:-false}" == "true" ]]
}

case "${ACTION}" in
  apply|--check-access|--verify|--retire-bootstrap) ;;
  *) usage; exit 2 ;;
esac

if ! keycloak_requested || [[ ! -x "${ADM_SCRIPT}" ]]; then
  exit 0
fi

[[ -n "${TARGET_REALM}" && "${TARGET_REALM}" != "master" ]] || {
  echo 'Keycloak provisioning requires a non-master application realm.' >&2
  exit 1
}
[[ -n "${KEYCLOAK_PROVISIONER_CLIENT_ID:-}" && -n "${KEYCLOAK_PROVISIONER_CLIENT_SECRET:-}" ]] || {
  echo 'Keycloak provisioning requires a provisioner client identity.' >&2
  exit 1
}

TMP_DIR=$(mktemp -d)
trap 'rm -rf "${TMP_DIR}"' EXIT

wait_for_keycloak() {
  echo 'Waiting for the Keycloak master realm...' >&2
  until curl -sSf --output /dev/null "${KEYCLOAK_SERVER}/realms/${BOOTSTRAP_REALM}"; do
    sleep 2
  done
}

authenticate_client() {
  local client_id="$1"
  local client_secret="$2"
  "${ADM_SCRIPT}" config credentials \
    --server "${KEYCLOAK_SERVER}" \
    --realm "${BOOTSTRAP_REALM}" \
    --client "${client_id}" \
    --secret "${client_secret}" >/dev/null 2>&1 && \
    "${ADM_SCRIPT}" get serverinfo >/dev/null 2>&1
}

authenticate_provisioner() {
  if authenticate_client "${KEYCLOAK_PROVISIONER_CLIENT_ID}" "${KEYCLOAK_PROVISIONER_CLIENT_SECRET}"; then
    AUTH_METHOD=provisioner
    return
  fi
  if [[ -n "${KEYCLOAK_RECOVERY_CLIENT_ID:-}" && -n "${KEYCLOAK_RECOVERY_CLIENT_SECRET:-}" ]] && \
     authenticate_client "${KEYCLOAK_RECOVERY_CLIENT_ID}" "${KEYCLOAK_RECOVERY_CLIENT_SECRET}"; then
    AUTH_METHOD=recovery
    return
  fi
  echo 'The Keycloak provisioner service account is unavailable or unauthorized.' >&2
  exit 1
}

ensure_provisioner_client() {
  local client_uuid service_username
  if [[ "${AUTH_METHOD}" != recovery ]]; then
    return 0
  fi
  client_uuid=$("${ADM_SCRIPT}" get clients -r "${BOOTSTRAP_REALM}" \
    --query "clientId=${KEYCLOAK_PROVISIONER_CLIENT_ID}" --fields id | jq -r '.[0].id // empty')
  if [[ -z "${client_uuid}" ]]; then
    jq -n --arg client_id "${KEYCLOAK_PROVISIONER_CLIENT_ID}" \
      --arg client_secret "${KEYCLOAK_PROVISIONER_CLIENT_SECRET}" '{
        clientId: $client_id,
        name: "Oculox realm provisioner",
        enabled: true,
        publicClient: false,
        clientAuthenticatorType: "client-secret",
        secret: $client_secret,
        standardFlowEnabled: false,
        directAccessGrantsEnabled: false,
        implicitFlowEnabled: false,
        serviceAccountsEnabled: true
      }' > "${TMP_DIR}/provisioner-client.json"
    "${ADM_SCRIPT}" create clients -r "${BOOTSTRAP_REALM}" -f "${TMP_DIR}/provisioner-client.json" >/dev/null
    client_uuid=$("${ADM_SCRIPT}" get clients -r "${BOOTSTRAP_REALM}" \
      --query "clientId=${KEYCLOAK_PROVISIONER_CLIENT_ID}" --fields id | jq -r '.[0].id // empty')
  fi
  [[ -n "${client_uuid}" ]] || { echo 'Unable to create Keycloak provisioner client.' >&2; exit 1; }
  service_username=$("${ADM_SCRIPT}" get "clients/${client_uuid}/service-account-user" -r "${BOOTSTRAP_REALM}" | jq -r '.username // empty')
  [[ -n "${service_username}" ]] || { echo 'Provisioner service account is missing.' >&2; exit 1; }
  # Keycloak 26 grants master-realm administration through its composite
  # realm role "admin". It supersedes the legacy realm-management client
  # mapping used by older Keycloak releases.
  "${ADM_SCRIPT}" add-roles -r "${BOOTSTRAP_REALM}" --uusername "${service_username}" \
    --rolename admin >/dev/null
}

find_user_id() {
  local realm="$1"
  local username="$2"
  "${ADM_SCRIPT}" get users -r "${realm}" --query "username=${username}" | \
    jq -r --arg username "${username}" '.[] | select(.username == $username) | .id' | head -n 1
}

find_group_id() {
  local group_name="$1"
  "${ADM_SCRIPT}" get groups -r "${TARGET_REALM}" --query "search=${group_name}" | \
    jq -r --arg group_name "${group_name}" '.[] | select(.name == $group_name) | .id' | head -n 1
}

ensure_realm_role() {
  local role_name="$1"
  if ! "${ADM_SCRIPT}" get roles -r "${TARGET_REALM}" --query "search=${role_name}" | \
      jq -e --arg name "${role_name}" '.[] | select(.name == $name)' >/dev/null; then
    echo "Creating realm role ${role_name}..." >&2
    "${ADM_SCRIPT}" create roles -r "${TARGET_REALM}" -s "name=${role_name}" >/dev/null
  fi
}

ensure_group() {
  local group_name="$1"
  local group_id
  group_id=$(find_group_id "${group_name}")
  if [[ -z "${group_id}" ]]; then
    echo "Creating group /${group_name}..." >&2
    "${ADM_SCRIPT}" create groups -r "${TARGET_REALM}" -s "name=${group_name}" >/dev/null
    group_id=$(find_group_id "${group_name}")
  fi
  [[ -n "${group_id}" ]] || { echo "Unable to find group ${group_name}." >&2; exit 1; }
}

assign_group_role() {
  local group_name="$1"
  local role_name="$2"
  "${ADM_SCRIPT}" add-roles -r "${TARGET_REALM}" \
    --gname "${group_name}" --rolename "${role_name}" >/dev/null
}

ensure_group_roles() {
  local group_name="$1"
  shift
  for role_name in "$@"; do
    [[ -n "${role_name}" ]] || continue
    ensure_realm_role "${role_name}"
    assign_group_role "${group_name}" "${role_name}"
  done
}

ensure_user_membership() {
  local user_id="$1"
  local group_name="$2"
  local group_id
  group_id=$(find_group_id "${group_name}")
  [[ -n "${group_id}" ]] || { echo "Missing group ${group_name}." >&2; exit 1; }
  "${ADM_SCRIPT}" update "users/${user_id}/groups/${group_id}" -r "${TARGET_REALM}" -n >/dev/null
}

ensure_user() {
  local username="$1"
  local password="$2"
  shift 2
  [[ -n "${username}" ]] || { echo 'An initial administrator username is required.' >&2; exit 1; }
  local user_id user_created=false
  user_id=$(find_user_id "${TARGET_REALM}" "${username}")
  if [[ -z "${user_id}" ]]; then
    [[ -n "${password}" ]] || {
      echo "User ${username} is missing and no initial password was supplied." >&2
      exit 1
    }
    echo "Creating user ${username}..." >&2
    "${ADM_SCRIPT}" create users -r "${TARGET_REALM}" \
      -s "username=${username}" -s enabled=true -s emailVerified=false >/dev/null
    user_id=$(find_user_id "${TARGET_REALM}" "${username}")
    [[ -n "${user_id}" ]] || { echo "Unable to find user ${username}." >&2; exit 1; }
    user_created=true
  fi
  if [[ "${user_created}" == true && -n "${password}" ]]; then
    "${ADM_SCRIPT}" set-password -r "${TARGET_REALM}" --username "${username}" \
      --new-password "${password}" --temporary >/dev/null
  fi
  for group_name in "$@"; do
    ensure_user_membership "${user_id}" "${group_name}"
  done
}

remove_user_if_present() {
  local realm="$1"
  local username="$2"
  local user_id
  user_id=$(find_user_id "${realm}" "${username}")
  if [[ -n "${user_id}" ]]; then
    echo "Removing legacy user ${username}..." >&2
    "${ADM_SCRIPT}" delete "users/${user_id}" -r "${realm}" >/dev/null
  fi
}

ensure_console_admin() {
  local username="${KEYCLOAK_CONSOLE_ADMIN_USERNAME:-}"
  local password="${KEYCLOAK_CONSOLE_ADMIN_PASSWORD:-}"
  local user_id
  [[ -n "${username}" ]] || { echo 'A Keycloak console administrator username is required.' >&2; exit 1; }
  user_id=$(find_user_id "${BOOTSTRAP_REALM}" "${username}")
  if [[ -z "${user_id}" ]]; then
    [[ -n "${password}" ]] || {
      echo "Keycloak console administrator ${username} is missing and no password was supplied." >&2
      exit 1
    }
    echo "Creating Keycloak console administrator ${username}..." >&2
    "${ADM_SCRIPT}" create users -r "${BOOTSTRAP_REALM}" \
      -s "username=${username}" -s enabled=true -s emailVerified=false >/dev/null
    user_id=$(find_user_id "${BOOTSTRAP_REALM}" "${username}")
    [[ -n "${user_id}" ]] || { echo "Unable to find Keycloak console administrator ${username}." >&2; exit 1; }
  fi
  if [[ -n "${password}" ]]; then
    "${ADM_SCRIPT}" set-password -r "${BOOTSTRAP_REALM}" --username "${username}" \
      --new-password "${password}" >/dev/null
  fi
  "${ADM_SCRIPT}" add-roles -r "${BOOTSTRAP_REALM}" --uusername "${username}" \
    --rolename admin >/dev/null
}

public_origin() {
  local auth_url="${KEYCLOAK_AUTH_URL%/}"
  local relative_path="${KC_HTTP_RELATIVE_PATH:-/keycloak}"
  local origin="${auth_url%${relative_path}}"
  printf '%s' "${origin%/}"
}

portal_redirect_uri() {
  local origin
  origin=$(public_origin)
  if [[ "${KEYCLOAK_AUTH_REDIRECT_URI}" == /* ]]; then
    printf '%s%s' "${origin}" "${KEYCLOAK_AUTH_REDIRECT_URI}"
  else
    printf '%s' "${KEYCLOAK_AUTH_REDIRECT_URI}"
  fi
}

ensure_mapper() {
  local client_uuid="$1"
  local mapper_name="$2"
  local mapper_file="$3"
  local mapper_id
  mapper_id=$("${ADM_SCRIPT}" get "clients/${client_uuid}/protocol-mappers/models" -r "${TARGET_REALM}" | \
    jq -r --arg name "${mapper_name}" '.[] | select(.name == $name) | .id' | head -n 1)
  if [[ -n "${mapper_id}" ]]; then
    jq --arg id "${mapper_id}" '.id = $id' "${mapper_file}" > "${TMP_DIR}/${mapper_name}-update.json"
    "${ADM_SCRIPT}" update "clients/${client_uuid}/protocol-mappers/models/${mapper_id}" \
      -r "${TARGET_REALM}" -f "${TMP_DIR}/${mapper_name}-update.json" >/dev/null
  else
    "${ADM_SCRIPT}" create "clients/${client_uuid}/protocol-mappers/models" \
      -r "${TARGET_REALM}" -f "${mapper_file}" >/dev/null
  fi
}

ensure_client() {
  local client_id="$1"
  local client_secret="$2"
  local client_name="$3"
  local redirect_uri="$4"
  local origin web_origin client_uuid post_logout_uri
  origin=$(public_origin)
  web_origin="${origin}"
  post_logout_uri="${origin}/"
  if [[ "${redirect_uri}" == */dashboards/auth/openid/login ]]; then
    post_logout_uri="${redirect_uri%/auth/openid/login}"
    web_origin="${redirect_uri%/dashboards/auth/openid/login}"
  fi
  [[ -n "${client_id}" && -n "${client_secret}" && -n "${redirect_uri}" ]] || {
    echo "Client ${client_name} has incomplete configuration." >&2
    exit 1
  }
  jq -n \
    --arg client_id "${client_id}" \
    --arg client_secret "${client_secret}" \
    --arg client_name "${client_name}" \
    --arg origin "${origin}" \
    --arg web_origin "${web_origin}" \
    --arg redirect_uri "${redirect_uri}" \
    --arg post_logout_uri "${post_logout_uri}" \
    '{
      clientId: $client_id,
      secret: $client_secret,
      name: $client_name,
      enabled: true,
      publicClient: false,
      clientAuthenticatorType: "client-secret",
      standardFlowEnabled: true,
      directAccessGrantsEnabled: false,
      implicitFlowEnabled: false,
      serviceAccountsEnabled: false,
      rootUrl: $origin,
      baseUrl: $origin,
      adminUrl: $origin,
      redirectUris: [$redirect_uri, $post_logout_uri],
      webOrigins: [$web_origin],
      attributes: {"post.logout.redirect.uris": $post_logout_uri}
    }' > "${TMP_DIR}/${client_id}.json"

  client_uuid=$("${ADM_SCRIPT}" get clients -r "${TARGET_REALM}" \
    --query "clientId=${client_id}" --fields id | jq -r '.[0].id // empty')
  if [[ -n "${client_uuid}" ]]; then
    echo "Updating OIDC client ${client_id}..." >&2
    "${ADM_SCRIPT}" update "clients/${client_uuid}" -r "${TARGET_REALM}" \
      -f "${TMP_DIR}/${client_id}.json" >/dev/null
  else
    echo "Creating OIDC client ${client_id}..." >&2
    "${ADM_SCRIPT}" create clients -r "${TARGET_REALM}" -f "${TMP_DIR}/${client_id}.json" >/dev/null
    client_uuid=$("${ADM_SCRIPT}" get clients -r "${TARGET_REALM}" \
      --query "clientId=${client_id}" --fields id | jq -r '.[0].id // empty')
  fi
  [[ -n "${client_uuid}" ]] || { echo "OIDC client lookup failed: ${client_id}." >&2; exit 1; }

  jq -n '{
    name: "user_realm_role",
    protocol: "openid-connect",
    protocolMapper: "oidc-usermodel-realm-role-mapper",
    consentRequired: false,
    config: {
      "introspection.token.claim": "true", multivalued: "true",
      "userinfo.token.claim": "true", "id.token.claim": "true",
      "access.token.claim": "true", "claim.name": "realm_access.roles",
      "jsonType.label": "String"
    }
  }' > "${TMP_DIR}/${client_id}-roles.json"
  jq -n '{
    name: "user_realm_roles_flat",
    protocol: "openid-connect",
    protocolMapper: "oidc-usermodel-realm-role-mapper",
    consentRequired: false,
    config: {
      "introspection.token.claim": "true", multivalued: "true",
      "userinfo.token.claim": "true", "id.token.claim": "true",
      "access.token.claim": "true", "claim.name": "roles",
      "jsonType.label": "String"
    }
  }' > "${TMP_DIR}/${client_id}-roles-flat.json"
  jq -n '{
    name: "group_membership",
    protocol: "openid-connect",
    protocolMapper: "oidc-group-membership-mapper",
    consentRequired: false,
    config: {
      "full.path": "true", "introspection.token.claim": "true",
      "userinfo.token.claim": "true", "id.token.claim": "true",
      "access.token.claim": "true", "claim.name": "groups"
    }
  }' > "${TMP_DIR}/${client_id}-groups.json"
  jq -n --arg audience "${client_id}" --arg mapper_name "${client_id}_audience" '{
    name: $mapper_name,
    protocol: "openid-connect",
    protocolMapper: "oidc-audience-mapper",
    consentRequired: false,
    config: {
      "included.client.audience": $audience,
      "id.token.claim": "false",
      "access.token.claim": "true"
    }
  }' > "${TMP_DIR}/${client_id}-audience.json"
  ensure_mapper "${client_uuid}" user_realm_role "${TMP_DIR}/${client_id}-roles.json"
  ensure_mapper "${client_uuid}" user_realm_roles_flat "${TMP_DIR}/${client_id}-roles-flat.json"
  ensure_mapper "${client_uuid}" group_membership "${TMP_DIR}/${client_id}-groups.json"
  ensure_mapper "${client_uuid}" "${client_id}_audience" "${TMP_DIR}/${client_id}-audience.json"
}

apply_realm() {
  ensure_provisioner_client
  ensure_console_admin
  if ! "${ADM_SCRIPT}" get "realms/${TARGET_REALM}" >/dev/null 2>&1; then
    echo "Creating realm ${TARGET_REALM}..." >&2
    "${ADM_SCRIPT}" create realms -s "realm=${TARGET_REALM}" -s enabled=true >/dev/null
  fi

  local password_policy role_var role_name
  password_policy="length(${KEYCLOAK_PASSWORD_MIN_LENGTH:-14}) and upperCase(1) and lowerCase(1) and digits(1) and specialChars(1) and passwordHistory(5)"
  echo 'Applying realm security policy...' >&2
  "${ADM_SCRIPT}" update "realms/${TARGET_REALM}" \
    -s enabled=true \
    -s "passwordPolicy=${password_policy}" \
    -s bruteForceProtected=true \
    -s failureFactor=5 \
    -s waitIncrementSeconds=60 \
    -s maxFailureWaitSeconds=900 \
    -s maxDeltaTimeSeconds=43200 \
    -s permanentLockout=false \
    -s "accessTokenLifespan=${KEYCLOAK_ACCESS_TOKEN_LIFESPAN_SECONDS:-300}" \
    -s "ssoSessionIdleTimeout=${KEYCLOAK_SSO_SESSION_IDLE_SECONDS:-1800}" \
    -s "ssoSessionMaxLifespan=${KEYCLOAK_SSO_SESSION_MAX_SECONDS:-28800}" \
    -s revokeRefreshToken=true \
    -s refreshTokenMaxReuse=0 \
    -s eventsEnabled=true \
    -s adminEventsEnabled=true \
    -s adminEventsDetailsEnabled=true \
    -s "eventsExpiration=${KEYCLOAK_EVENTS_EXPIRATION_SECONDS:-604800}" >/dev/null
  if [[ "${KEYCLOAK_MFA_REQUIRED:-true}" == "true" ]]; then
    "${ADM_SCRIPT}" update authentication/required-actions/CONFIGURE_TOTP \
      -r "${TARGET_REALM}" -s enabled=true -s defaultAction=true >/dev/null
  fi

  while IFS= read -r role_var; do
    [[ "${role_var}" != ROLE_BASED_ACCESS ]] || continue
    role_name="${!role_var}"
    [[ -n "${role_name}" ]] && ensure_realm_role "${role_name}"
  done < <(compgen -e | grep '^ROLE_' | sort)

  for group_name in oculox-users oculox-admins oculox-analysts oculox-viewers oculox-incident-response; do
    ensure_group "${group_name}"
  done
  ensure_group_roles oculox-admins "${ROLE_ADMIN}"
  ensure_group_roles oculox-analysts "${ROLE_READ_WRITE_ACCESS}" "${ROLE_DASHBOARDS_READ_WRITE_ACCESS}" "${ROLE_ARKIME_HUNT_ACCESS}"
  ensure_group_roles oculox-viewers "${ROLE_READ_ACCESS}" "${ROLE_DASHBOARDS_READ_ACCESS}" "${ROLE_ARKIME_READ_ACCESS}"
  ensure_group_roles oculox-incident-response "${ROLE_READ_ACCESS}" "${ROLE_DASHBOARDS_READ_ACCESS}" \
    "${ROLE_ARKIME_PCAP_ACCESS}" "${ROLE_ARKIME_HUNT_ACCESS}"

  ensure_client "${KEYCLOAK_PORTAL_CLIENT_ID:-${KEYCLOAK_CLIENT_ID:-}}" \
    "${KEYCLOAK_PORTAL_CLIENT_SECRET:-${KEYCLOAK_CLIENT_SECRET:-}}" \
    'Oculox Portal' "$(portal_redirect_uri)"
  ensure_client "${KEYCLOAK_DASHBOARDS_CLIENT_ID:-}" \
    "${KEYCLOAK_DASHBOARDS_CLIENT_SECRET:-}" \
    'Oculox Dashboards' "${KEYCLOAK_DASHBOARDS_REDIRECT_URI:-}"

  ensure_user "${KEYCLOAK_INITIAL_ADMIN_USERNAME:-}" "${KEYCLOAK_INITIAL_ADMIN_PASSWORD:-}" oculox-users oculox-admins
  ensure_user oculox-admin "${KEYCLOAK_USER_ADMIN_PASSWORD:-}" oculox-users oculox-admins
  ensure_user oculox-analyst "${KEYCLOAK_USER_ANALYST_PASSWORD:-}" oculox-users oculox-analysts
  ensure_user oculox-viewer "${KEYCLOAK_USER_VIEWER_PASSWORD:-}" oculox-users oculox-viewers
  ensure_user oculox-incident-response "${KEYCLOAK_USER_INCIDENT_RESPONSE_PASSWORD:-}" oculox-users oculox-incident-response
  ensure_user oculox-denied "${KEYCLOAK_USER_DENIED_PASSWORD:-}"
  remove_user_if_present "${TARGET_REALM}" oculox-test-admin
  remove_user_if_present "${TARGET_REALM}" oculox-test-analyst
  remove_user_if_present "${TARGET_REALM}" oculox-test-viewer
  remove_user_if_present "${TARGET_REALM}" oculox-test-incident-response
  remove_user_if_present "${TARGET_REALM}" oculox-test-denied
}

verify_realm() {
  local expected_roles expected_groups expected_clients role_json group_json client_json realm_json totp_action
  local admins_roles analysts_roles viewers_roles incident_response_roles
  local initial_admin_groups admin_groups analyst_groups viewer_groups incident_response_groups denied_groups
  local portal_client dashboards_client console_admin_roles console_admin_id
  local initial_admin_id admin_id analyst_id viewer_id incident_response_id denied_id
  expected_roles=$(printf '%s\n' "${ROLE_ADMIN}" "${ROLE_READ_ACCESS}" "${ROLE_READ_WRITE_ACCESS}" \
    "${ROLE_ARKIME_HUNT_ACCESS}" "${ROLE_ARKIME_PCAP_ACCESS}" \
    "${ROLE_DASHBOARDS_READ_ACCESS}" "${ROLE_DASHBOARDS_READ_WRITE_ACCESS}" | jq -R . | jq -s .)
  expected_groups='["oculox-users","oculox-admins","oculox-analysts","oculox-viewers","oculox-incident-response"]'
  expected_clients=$(printf '%s\n' "${KEYCLOAK_PORTAL_CLIENT_ID}" "${KEYCLOAK_DASHBOARDS_CLIENT_ID}" | jq -R . | jq -s .)
  role_json=$("${ADM_SCRIPT}" get roles -r "${TARGET_REALM}")
  group_json=$("${ADM_SCRIPT}" get groups -r "${TARGET_REALM}")
  client_json=$("${ADM_SCRIPT}" get clients -r "${TARGET_REALM}")
  realm_json=$("${ADM_SCRIPT}" get "realms/${TARGET_REALM}")
  totp_action=$("${ADM_SCRIPT}" get authentication/required-actions/CONFIGURE_TOTP -r "${TARGET_REALM}")
  admins_roles=$("${ADM_SCRIPT}" get "groups/$(find_group_id oculox-admins)/role-mappings/realm" -r "${TARGET_REALM}")
  analysts_roles=$("${ADM_SCRIPT}" get "groups/$(find_group_id oculox-analysts)/role-mappings/realm" -r "${TARGET_REALM}")
  viewers_roles=$("${ADM_SCRIPT}" get "groups/$(find_group_id oculox-viewers)/role-mappings/realm" -r "${TARGET_REALM}")
  incident_response_roles=$("${ADM_SCRIPT}" get "groups/$(find_group_id oculox-incident-response)/role-mappings/realm" -r "${TARGET_REALM}")
  initial_admin_id=$(find_user_id "${TARGET_REALM}" "${KEYCLOAK_INITIAL_ADMIN_USERNAME}")
  admin_id=$(find_user_id "${TARGET_REALM}" oculox-admin)
  analyst_id=$(find_user_id "${TARGET_REALM}" oculox-analyst)
  viewer_id=$(find_user_id "${TARGET_REALM}" oculox-viewer)
  incident_response_id=$(find_user_id "${TARGET_REALM}" oculox-incident-response)
  denied_id=$(find_user_id "${TARGET_REALM}" oculox-denied)
  console_admin_id=$(find_user_id "${BOOTSTRAP_REALM}" "${KEYCLOAK_CONSOLE_ADMIN_USERNAME:-}")
  initial_admin_groups=$("${ADM_SCRIPT}" get "users/${initial_admin_id}/groups" -r "${TARGET_REALM}")
  admin_groups=$("${ADM_SCRIPT}" get "users/${admin_id}/groups" -r "${TARGET_REALM}")
  analyst_groups=$("${ADM_SCRIPT}" get "users/${analyst_id}/groups" -r "${TARGET_REALM}")
  viewer_groups=$("${ADM_SCRIPT}" get "users/${viewer_id}/groups" -r "${TARGET_REALM}")
  incident_response_groups=$("${ADM_SCRIPT}" get "users/${incident_response_id}/groups" -r "${TARGET_REALM}")
  denied_groups=$("${ADM_SCRIPT}" get "users/${denied_id}/groups" -r "${TARGET_REALM}")
  portal_client=$("${ADM_SCRIPT}" get "clients/$("${ADM_SCRIPT}" get clients -r "${TARGET_REALM}" --query "clientId=${KEYCLOAK_PORTAL_CLIENT_ID}" --fields id | jq -r '.[0].id // empty')" -r "${TARGET_REALM}")
  dashboards_client=$("${ADM_SCRIPT}" get "clients/$("${ADM_SCRIPT}" get clients -r "${TARGET_REALM}" --query "clientId=${KEYCLOAK_DASHBOARDS_CLIENT_ID}" --fields id | jq -r '.[0].id // empty')" -r "${TARGET_REALM}")
  console_admin_roles=$("${ADM_SCRIPT}" get "users/${console_admin_id}/role-mappings/realm" -r "${BOOTSTRAP_REALM}")
  jq -n \
    --arg realm "${TARGET_REALM}" \
    --argjson expected_roles "${expected_roles}" \
    --argjson expected_groups "${expected_groups}" \
    --argjson expected_clients "${expected_clients}" \
    --argjson roles "${role_json}" \
    --argjson groups "${group_json}" \
    --argjson clients "${client_json}" '
      def present($items; $name): any($items[]; .name == $name or .clientId == $name);
      {
        realm: $realm,
        roles: ([$expected_roles[] | select(present($roles; .))]),
        groups: ([$expected_groups[] | select(present($groups; .))]),
        clients: ([$expected_clients[] | select(present($clients; .))])
      } as $result |
      $result + {
        result: (if ($result.roles|length) == ($expected_roles|length) and
                      ($result.groups|length) == ($expected_groups|length) and
                      ($result.clients|length) == ($expected_clients|length)
                 then "PASS" else "FAIL" end)
      }' > "${TMP_DIR}/existence-report.json"
  jq -n \
    --arg admin "${ROLE_ADMIN}" \
    --arg read_write "${ROLE_READ_WRITE_ACCESS}" \
    --arg dashboards_write "${ROLE_DASHBOARDS_READ_WRITE_ACCESS}" \
    --arg hunt "${ROLE_ARKIME_HUNT_ACCESS}" \
    --arg read "${ROLE_READ_ACCESS}" \
    --arg dashboards_read "${ROLE_DASHBOARDS_READ_ACCESS}" \
    --arg arkime_read "${ROLE_ARKIME_READ_ACCESS}" \
    --arg pcap "${ROLE_ARKIME_PCAP_ACCESS}" \
    --argjson admins "${admins_roles}" \
    --argjson analysts "${analysts_roles}" \
    --argjson viewers "${viewers_roles}" \
    --argjson incident_response "${incident_response_roles}" \
    --argjson initial_admin "${initial_admin_groups}" \
    --argjson admin_user "${admin_groups}" \
    --argjson analyst "${analyst_groups}" \
    --argjson viewer "${viewer_groups}" \
    --argjson incident_response_user "${incident_response_groups}" \
    --argjson denied "${denied_groups}" \
    --argjson portal "${portal_client}" \
    --argjson dashboards "${dashboards_client}" \
    --argjson console_admin_roles "${console_admin_roles}" \
    --arg portal_redirect "$(portal_redirect_uri)" \
    --arg dashboards_redirect "${KEYCLOAK_DASHBOARDS_REDIRECT_URI}" \
    --arg portal_logout "$(public_origin)/" \
    --arg dashboards_logout "${KEYCLOAK_DASHBOARDS_REDIRECT_URI%/auth/openid/login}" \
    --arg portal_web_origin "$(public_origin)" \
    --arg dashboards_web_origin "${KEYCLOAK_DASHBOARDS_REDIRECT_URI%/dashboards/auth/openid/login}" \
    --argjson realm "${realm_json}" \
    --argjson totp "${totp_action}" \
    --arg mfa_required "${KEYCLOAK_MFA_REQUIRED:-true}" '
      def names($items): [$items[] | .name];
      def contains_all($actual; $required): all($required[]; . as $expected | ($actual | index($expected)));
      def protected_client($client; $redirect; $logout; $web_origin):
        $client.enabled == true and
        $client.publicClient == false and
        $client.standardFlowEnabled == true and
        $client.directAccessGrantsEnabled == false and
        $client.implicitFlowEnabled == false and
        $client.serviceAccountsEnabled == false and
        (($client.redirectUris // []) | index($redirect)) != null and
        (($client.redirectUris // []) | index($logout)) != null and
        (($client.webOrigins // []) | index($web_origin)) != null;
      {
        group_roles: {
          admins: names($admins), analysts: names($analysts),
          viewers: names($viewers), incident_response: names($incident_response)
        },
        user_groups: {
          initial_admin: names($initial_admin), admin: names($admin_user),
          analyst: names($analyst), viewer: names($viewer),
          incident_response: names($incident_response_user), denied: names($denied)
        },
        clients: {
          portal: {
            standard_flow: $portal.standardFlowEnabled,
            direct_grants: $portal.directAccessGrantsEnabled,
            redirect_uri: $portal.redirectUris[0],
            redirect_uris: $portal.redirectUris,
            web_origins: $portal.webOrigins,
            post_logout_redirect_uri: $portal.attributes."post.logout.redirect.uris"
          },
          dashboards: {
            standard_flow: $dashboards.standardFlowEnabled,
            direct_grants: $dashboards.directAccessGrantsEnabled,
            redirect_uri: $dashboards.redirectUris[0],
            redirect_uris: $dashboards.redirectUris,
            web_origins: $dashboards.webOrigins,
            post_logout_redirect_uri: $dashboards.attributes."post.logout.redirect.uris"
          }
        },
        realm_security: {
          brute_force_protected: $realm.bruteForceProtected,
          refresh_token_rotation: $realm.revokeRefreshToken,
          access_token_lifespan: $realm.accessTokenLifespan,
          sso_session_idle_timeout: $realm.ssoSessionIdleTimeout,
          sso_session_max_lifespan: $realm.ssoSessionMaxLifespan,
          events_enabled: $realm.eventsEnabled,
          admin_events_enabled: $realm.adminEventsEnabled,
          admin_event_details_enabled: $realm.adminEventsDetailsEnabled,
          mfa_required_action_enabled: $totp.enabled,
          mfa_required_action_default: $totp.defaultAction
        },
        keycloak_console_admin: {
          username: env.KEYCLOAK_CONSOLE_ADMIN_USERNAME,
          realm: env.KEYCLOAK_BOOTSTRAP_REALM,
          realm_roles: names($console_admin_roles)
        }
      } as $details |
      $details + {
        result: (
          contains_all($details.group_roles.admins; [$admin]) and
          contains_all($details.group_roles.analysts; [$read_write, $dashboards_write, $hunt]) and
          contains_all($details.group_roles.viewers; [$read, $dashboards_read, $arkime_read]) and
          contains_all($details.group_roles.incident_response; [$read, $dashboards_read, $pcap, $hunt]) and
          contains_all($details.user_groups.initial_admin; ["oculox-users", "oculox-admins"]) and
          contains_all($details.user_groups.admin; ["oculox-users", "oculox-admins"]) and
          contains_all($details.user_groups.analyst; ["oculox-users", "oculox-analysts"]) and
          contains_all($details.user_groups.viewer; ["oculox-users", "oculox-viewers"]) and
          contains_all($details.user_groups.incident_response; ["oculox-users", "oculox-incident-response"]) and
          ($details.user_groups.denied | length) == 0 and
          protected_client($portal; $portal_redirect; $portal_logout; $portal_web_origin) and
          $details.clients.portal.post_logout_redirect_uri == $portal_logout and
          protected_client($dashboards; $dashboards_redirect; $dashboards_logout; $dashboards_web_origin) and
          $details.clients.dashboards.post_logout_redirect_uri == $dashboards_logout and
          $details.realm_security.brute_force_protected == true and
          $details.realm_security.refresh_token_rotation == true and
          $details.realm_security.access_token_lifespan <= 900 and
          $details.realm_security.events_enabled == true and
          $details.realm_security.admin_events_enabled == true and
          $details.realm_security.admin_event_details_enabled == true and
          contains_all($details.keycloak_console_admin.realm_roles; ["admin"]) and
          (if $mfa_required == "true" then
            $details.realm_security.mfa_required_action_enabled == true and
            $details.realm_security.mfa_required_action_default == true
          else true end)
        )
      }' > "${TMP_DIR}/security-report.json"
  jq -s '.[0] as $existence | .[1] as $security | ($existence + $security) | .result = (if $existence.result == "PASS" and $security.result == true then "PASS" else "FAIL" end)' \
    "${TMP_DIR}/existence-report.json" "${TMP_DIR}/security-report.json"
}

retire_bootstrap() {
  local bootstrap_id bootstrap_client_id
  local bootstrap_ids
  bootstrap_ids=$("${ADM_SCRIPT}" get users -r "${BOOTSTRAP_REALM}" --query 'search=oculox-bootstrap-' | \
    jq -r '.[] | select(.username | startswith("oculox-bootstrap-")) | .id')
  while IFS= read -r bootstrap_id; do
    [[ -n "${bootstrap_id}" ]] || continue
    "${ADM_SCRIPT}" delete "users/${bootstrap_id}" -r "${BOOTSTRAP_REALM}" >/dev/null
  done <<< "${bootstrap_ids}"
  bootstrap_client_id=$("${ADM_SCRIPT}" get clients -r "${BOOTSTRAP_REALM}" \
    --query "clientId=${KEYCLOAK_RECOVERY_CLIENT_ID:-}" --fields id | jq -r '.[0].id // empty')
  if [[ -n "${bootstrap_client_id}" ]]; then
    "${ADM_SCRIPT}" delete "clients/${bootstrap_client_id}" -r "${BOOTSTRAP_REALM}" >/dev/null
  fi
  echo 'Temporary bootstrap administrators removed from master.' >&2
}

wait_for_keycloak
authenticate_provisioner
case "${ACTION}" in
  apply)
    apply_realm
    echo "Keycloak realm ${TARGET_REALM} is provisioned." >&2
    ;;
  --check-access) ;;
  --verify) verify_realm ;;
  --retire-bootstrap) retire_bootstrap ;;
esac
