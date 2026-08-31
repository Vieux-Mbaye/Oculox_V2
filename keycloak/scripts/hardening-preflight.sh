#!/usr/bin/env bash

set -euo pipefail

if [[ "${NGINX_AUTH_MODE:-basic}" != "keycloak" ]]; then
  exit 0
fi

fail() {
  printf 'Keycloak hardening preflight failed: %s\n' "$1" >&2
  exit 1
}

is_positive_integer() {
  [[ "$1" =~ ^[1-9][0-9]*$ ]]
}

[[ -n "${KEYCLOAK_AUTH_REALM:-}" ]] || fail "KEYCLOAK_AUTH_REALM is required"
[[ "${KEYCLOAK_AUTH_REALM}" != "master" ]] || fail "the Oculox realm must be separate from master"
[[ "${KEYCLOAK_BOOTSTRAP_REALM:-master}" == "master" ]] || fail "bootstrap administration must use the master realm"

[[ "${KEYCLOAK_AUTH_URL:-}" == https://* ]] || fail "KEYCLOAK_AUTH_URL must use HTTPS"
[[ -n "${KC_HOSTNAME:-}" ]] || fail "KC_HOSTNAME is required"
[[ "${KC_HOSTNAME%/}" == "${KEYCLOAK_AUTH_URL%/}" ]] || fail "KC_HOSTNAME must match KEYCLOAK_AUTH_URL"
[[ "${KC_HOSTNAME_STRICT:-false}" == "true" ]] || fail "KC_HOSTNAME_STRICT must be true"
[[ "${KC_PROXY_HEADERS:-}" == "xforwarded" ]] || fail "KC_PROXY_HEADERS must be xforwarded behind the Oculox proxy"
[[ "${KEYCLOAK_SSL_VERIFY:-false}" == "true" ]] || fail "KEYCLOAK_SSL_VERIFY must be true"

[[ -n "${KEYCLOAK_CLIENT_ID:-}" ]] || fail "KEYCLOAK_CLIENT_ID is required"
CLIENT_SECRET="${KEYCLOAK_CLIENT_SECRET:-}"
[[ ${#CLIENT_SECRET} -ge 32 ]] || fail "KEYCLOAK_CLIENT_SECRET must contain at least 32 characters"
[[ -n "${KEYCLOAK_AUTH_REDIRECT_URI:-}" ]] || fail "KEYCLOAK_AUTH_REDIRECT_URI is required"
[[ "${KEYCLOAK_AUTH_REDIRECT_URI}" != *'*'* ]] || fail "wildcards are forbidden in redirect URIs"
if [[ "${KEYCLOAK_AUTH_REDIRECT_URI}" != /* && "${KEYCLOAK_AUTH_REDIRECT_URI}" != https://* ]]; then
  fail "the redirect URI must be an absolute HTTPS URI or an absolute path"
fi
if [[ "${KEYCLOAK_AUTH_REDIRECT_URI}" == https://* ]]; then
  PUBLIC_ORIGIN="${KEYCLOAK_AUTH_URL%${KC_HTTP_RELATIVE_PATH:-/keycloak}}"
  [[ "${KEYCLOAK_AUTH_REDIRECT_URI}" == "${PUBLIC_ORIGIN%/}"/* ]] || \
    fail "the redirect URI must use the Oculox public origin"
fi

[[ "${ROLE_BASED_ACCESS:-false}" == "true" ]] || fail "ROLE_BASED_ACCESS must be true"
[[ -n "${NGINX_REQUIRE_GROUP:-}" ]] || fail "NGINX_REQUIRE_GROUP must restrict portal access"

if [[ -n "${KC_BOOTSTRAP_ADMIN_USERNAME:-}" || -n "${KC_BOOTSTRAP_ADMIN_PASSWORD:-}" ]]; then
  [[ -n "${KC_BOOTSTRAP_ADMIN_USERNAME:-}" && -n "${KC_BOOTSTRAP_ADMIN_PASSWORD:-}" ]] || \
    fail "bootstrap username and password must be set together"
  [[ ${#KC_BOOTSTRAP_ADMIN_PASSWORD} -ge 16 ]] || fail "the bootstrap password must contain at least 16 characters"
fi

is_positive_integer "${KEYCLOAK_PASSWORD_MIN_LENGTH:-14}" || fail "KEYCLOAK_PASSWORD_MIN_LENGTH must be a positive integer"
(( KEYCLOAK_PASSWORD_MIN_LENGTH >= 14 )) || fail "KEYCLOAK_PASSWORD_MIN_LENGTH must be at least 14"

for setting in \
  KEYCLOAK_ACCESS_TOKEN_LIFESPAN_SECONDS \
  KEYCLOAK_SSO_SESSION_IDLE_SECONDS \
  KEYCLOAK_SSO_SESSION_MAX_SECONDS \
  KEYCLOAK_EVENTS_EXPIRATION_SECONDS; do
  value="${!setting:-}"
  is_positive_integer "${value}" || fail "${setting} must be a positive integer"
done

(( KEYCLOAK_ACCESS_TOKEN_LIFESPAN_SECONDS <= 900 )) || fail "access tokens must not exceed 900 seconds"
(( KEYCLOAK_SSO_SESSION_IDLE_SECONDS <= KEYCLOAK_SSO_SESSION_MAX_SECONDS )) || \
  fail "session idle timeout must not exceed session maximum"

printf 'Keycloak hardening preflight passed for realm %s and client %s.\n' \
  "${KEYCLOAK_AUTH_REALM}" "${KEYCLOAK_CLIENT_ID}" >&2
