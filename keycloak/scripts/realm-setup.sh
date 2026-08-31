#!/usr/bin/env bash

set -euo pipefail

ADM_SCRIPT=/opt/keycloak/bin/kcadm.sh
TARGET_REALM="${KEYCLOAK_AUTH_REALM:-}"
BOOTSTRAP_REALM="${KEYCLOAK_BOOTSTRAP_REALM:-master}"
KEYCLOAK_SERVER="http://localhost:8080${KC_HTTP_RELATIVE_PATH:-/keycloak}"

if [[ "${NGINX_AUTH_MODE:-basic}" != "keycloak" ]] || [[ ! -x "${ADM_SCRIPT}" ]]; then
  exit 0
fi

if [[ -z "${KC_BOOTSTRAP_ADMIN_USERNAME:-}" || -z "${KC_BOOTSTRAP_ADMIN_PASSWORD:-}" ]]; then
  echo "Keycloak realm provisioning skipped: bootstrap credentials are absent." >&2
  exit 0
fi

TMP_DIR=$(mktemp -d)
trap 'rm -rf "${TMP_DIR}"' EXIT

echo "Waiting for the Keycloak master realm..." >&2
until curl -sSf --output /dev/null "${KEYCLOAK_SERVER}/realms/${BOOTSTRAP_REALM}"; do
  sleep 5
done

echo "Authenticating the temporary administrator in realm ${BOOTSTRAP_REALM}..." >&2
"${ADM_SCRIPT}" config credentials \
  --server "${KEYCLOAK_SERVER}" \
  --realm "${BOOTSTRAP_REALM}" \
  --user "${KC_BOOTSTRAP_ADMIN_USERNAME}" \
  --password "${KC_BOOTSTRAP_ADMIN_PASSWORD}" >/dev/null

if ! "${ADM_SCRIPT}" get "realms/${TARGET_REALM}" >/dev/null 2>&1; then
  echo "Creating realm ${TARGET_REALM}..." >&2
  "${ADM_SCRIPT}" create realms -s "realm=${TARGET_REALM}" -s enabled=true >/dev/null
fi

PASSWORD_POLICY="length(${KEYCLOAK_PASSWORD_MIN_LENGTH:-14}) and upperCase(1) and lowerCase(1) and digits(1) and specialChars(1) and passwordHistory(5)"

echo "Applying the hardened realm policy..." >&2
"${ADM_SCRIPT}" update "realms/${TARGET_REALM}" \
  -s enabled=true \
  -s "passwordPolicy=${PASSWORD_POLICY}" \
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

for ROLE_VAR in $(compgen -e | sort); do
  [[ "${ROLE_VAR}" == ROLE_* && "${ROLE_VAR}" != "ROLE_BASED_ACCESS" ]] || continue
  ROLE_NAME="${!ROLE_VAR}"
  [[ -n "${ROLE_NAME}" ]] || continue
  if ! "${ADM_SCRIPT}" get roles -r "${TARGET_REALM}" --query "search=${ROLE_NAME}" | \
      jq -e --arg name "${ROLE_NAME}" '.[] | select(.name == $name)' >/dev/null; then
    echo "Creating realm role ${ROLE_NAME}..." >&2
    "${ADM_SCRIPT}" create roles -r "${TARGET_REALM}" -s "name=${ROLE_NAME}" >/dev/null
  fi
done

AUTH_URL="${KEYCLOAK_AUTH_URL%/}"
RELATIVE_PATH="${KC_HTTP_RELATIVE_PATH:-/keycloak}"
PUBLIC_ORIGIN="${AUTH_URL%${RELATIVE_PATH}}"
PUBLIC_ORIGIN="${PUBLIC_ORIGIN%/}"
if [[ "${KEYCLOAK_AUTH_REDIRECT_URI}" == /* ]]; then
  REDIRECT_URI="${PUBLIC_ORIGIN}${KEYCLOAK_AUTH_REDIRECT_URI}"
else
  REDIRECT_URI="${KEYCLOAK_AUTH_REDIRECT_URI}"
fi

CLIENT_FILE="${TMP_DIR}/client.json"
jq -n \
  --arg client_id "${KEYCLOAK_CLIENT_ID}" \
  --arg client_secret "${KEYCLOAK_CLIENT_SECRET}" \
  --arg origin "${PUBLIC_ORIGIN}" \
  --arg redirect_uri "${REDIRECT_URI}" \
  '{
    clientId: $client_id,
    secret: $client_secret,
    name: "Oculox portal",
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
    redirectUris: [$redirect_uri],
    webOrigins: [$origin],
    attributes: {"post.logout.redirect.uris": ($origin + "/")}
  }' > "${CLIENT_FILE}"

CLIENT_UUID=$("${ADM_SCRIPT}" get clients -r "${TARGET_REALM}" \
  --query "clientId=${KEYCLOAK_CLIENT_ID}" --fields id | jq -r '.[0].id // empty')
if [[ -n "${CLIENT_UUID}" ]]; then
  echo "Updating OIDC client ${KEYCLOAK_CLIENT_ID}..." >&2
  "${ADM_SCRIPT}" update "clients/${CLIENT_UUID}" -r "${TARGET_REALM}" -f "${CLIENT_FILE}" >/dev/null
else
  echo "Creating OIDC client ${KEYCLOAK_CLIENT_ID}..." >&2
  "${ADM_SCRIPT}" create clients -r "${TARGET_REALM}" -f "${CLIENT_FILE}" >/dev/null
  CLIENT_UUID=$("${ADM_SCRIPT}" get clients -r "${TARGET_REALM}" \
    --query "clientId=${KEYCLOAK_CLIENT_ID}" --fields id | jq -r '.[0].id // empty')
fi
[[ -n "${CLIENT_UUID}" ]] || { echo "OIDC client lookup failed." >&2; exit 1; }

ensure_mapper() {
  local mapper_name="$1"
  local mapper_file="$2"
  local mapper_id
  mapper_id=$("${ADM_SCRIPT}" get "clients/${CLIENT_UUID}/protocol-mappers/models" -r "${TARGET_REALM}" | \
    jq -r --arg name "${mapper_name}" '.[] | select(.name == $name) | .id' | head -n 1)
  if [[ -n "${mapper_id}" ]]; then
    "${ADM_SCRIPT}" update "clients/${CLIENT_UUID}/protocol-mappers/models/${mapper_id}" \
      -r "${TARGET_REALM}" -f "${mapper_file}" >/dev/null
  else
    "${ADM_SCRIPT}" create "clients/${CLIENT_UUID}/protocol-mappers/models" \
      -r "${TARGET_REALM}" -f "${mapper_file}" >/dev/null
  fi
}

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
}' > "${TMP_DIR}/roles-mapper.json"

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
}' > "${TMP_DIR}/groups-mapper.json"

jq -n --arg audience "${KEYCLOAK_CLIENT_ID}" '{
  name: "oculox_portal_audience",
  protocol: "openid-connect",
  protocolMapper: "oidc-audience-mapper",
  consentRequired: false,
  config: {
    "included.client.audience": $audience,
    "id.token.claim": "false",
    "access.token.claim": "true"
  }
}' > "${TMP_DIR}/audience-mapper.json"

ensure_mapper user_realm_role "${TMP_DIR}/roles-mapper.json"
ensure_mapper group_membership "${TMP_DIR}/groups-mapper.json"
ensure_mapper oculox_portal_audience "${TMP_DIR}/audience-mapper.json"

echo "Keycloak realm ${TARGET_REALM} and client ${KEYCLOAK_CLIENT_ID} are provisioned." >&2
