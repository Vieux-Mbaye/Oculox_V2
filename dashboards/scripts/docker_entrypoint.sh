#!/bin/bash

# tweak some things in the opensearch_dashboards.yml file for opensearch output
ORIG_YML=/tmp/oculox/opensearch_dashboards.orig.yml
FINAL_YML=/usr/share/opensearch-dashboards/config/opensearch_dashboards.yml

OPENSEARCH_SSL_CERTIFICATE_VERIFICATION=${OPENSEARCH_SSL_CERTIFICATE_VERIFICATION:-"false"}
OPENSEARCH_PRIMARY=${OPENSEARCH_PRIMARY:-"opensearch-local"}
OPENSEARCH_CREDS_CONFIG_FILE=${OPENSEARCH_CREDS_CONFIG_FILE:-"/var/local/curlrc/.opensearch.primary.curlrc"}
DASHBOARDS_AUTH_TYPE=${DASHBOARDS_AUTH_TYPE:-"basicauth"}
KEYCLOAK_AUTH_URL=${KEYCLOAK_AUTH_URL:-""}
KEYCLOAK_DASHBOARDS_CONNECT_URL=${KEYCLOAK_DASHBOARDS_CONNECT_URL:-"$KEYCLOAK_AUTH_URL"}
KEYCLOAK_AUTH_REALM=${KEYCLOAK_AUTH_REALM:-"oculox"}
KEYCLOAK_DASHBOARDS_CLIENT_ID=${KEYCLOAK_DASHBOARDS_CLIENT_ID:-""}
KEYCLOAK_DASHBOARDS_CLIENT_SECRET=${KEYCLOAK_DASHBOARDS_CLIENT_SECRET:-""}
KEYCLOAK_DASHBOARDS_REDIRECT_URI=${KEYCLOAK_DASHBOARDS_REDIRECT_URI:-""}

if [[ -f "$ORIG_YML" ]]; then
    cp "$ORIG_YML" "$FINAL_YML"

    # get the new username/password from the curl file (I already wrote python code to do this, so sue me)
    OPENSSL_USER=
    OPENSSL_PASSWORD=
    if [[ -r "$OPENSEARCH_CREDS_CONFIG_FILE" ]]; then
        pushd "$(dirname $(realpath -e "${BASH_SOURCE[0]}"))" >/dev/null 2>&1
        NEW_USER_PASSWORD="$(python3 -c "import malcolm_utils; result=malcolm_utils.ParseCurlFile('$OPENSEARCH_CREDS_CONFIG_FILE'); print(result['user']+'|'+result['password']);")"
        OPENSSL_USER="$(echo "$NEW_USER_PASSWORD" | cut -d'|' -f1)"
        OPENSSL_PASSWORD="$(echo "$NEW_USER_PASSWORD" | cut -d'|' -f2-)"
        popd >/dev/null 2>&1
    fi

    # replace things in the YML file for dashboards to use
    [[ -n "$OPENSSL_USER" ]] && \
        sed -i "s/_MALCOLM_DASHBOARDS_OPENSEARCH_USER_/$OPENSSL_USER/g" "$FINAL_YML" || \
        sed -i '/_MALCOLM_DASHBOARDS_OPENSEARCH_USER_/d' "$FINAL_YML"

    [[ -n "$OPENSSL_PASSWORD" ]] && \
        sed -i "s/_MALCOLM_DASHBOARDS_OPENSEARCH_PASSWORD_/$OPENSSL_PASSWORD/g" "$FINAL_YML" || \
        sed -i '/_MALCOLM_DASHBOARDS_OPENSEARCH_PASSWORD_/d' "$FINAL_YML"

    # Reuse the generated Dashboards service secret as the session encryption
    # key. A dedicated cookie name invalidates sessions from older auth modes.
    [[ -n "$OPENSSL_PASSWORD" ]] && \
        sed -i "s/_MALCOLM_DASHBOARDS_COOKIE_PASSWORD_/$OPENSSL_PASSWORD/g" "$FINAL_YML" || \
        sed -i '/_MALCOLM_DASHBOARDS_COOKIE_PASSWORD_/d' "$FINAL_YML"

    ( [[ "$OPENSEARCH_SSL_CERTIFICATE_VERIFICATION" == "true" ]] && [[ "$OPENSEARCH_PRIMARY" != "opensearch-local" ]] ) && \
        SSL_VERIFICATION_MODE=certificate || \
        SSL_VERIFICATION_MODE=none

    sed -i "s/_MALCOLM_DASHBOARDS_OPENSEARCH_SSL_VERIFICATION_MODE_/$SSL_VERIFICATION_MODE/g" "$FINAL_YML"
    sed -i "s/_MALCOLM_DASHBOARDS_AUTH_TYPE_/$DASHBOARDS_AUTH_TYPE/g" "$FINAL_YML"

    if [[ "$DASHBOARDS_AUTH_TYPE" == "openid" ]]; then
        [[ -n "$KEYCLOAK_DASHBOARDS_CONNECT_URL" && -n "$KEYCLOAK_DASHBOARDS_CLIENT_ID" && -n "$KEYCLOAK_DASHBOARDS_CLIENT_SECRET" ]] || {
            echo "Dashboards OpenID auth requires Keycloak URL, client ID and client secret" >&2
            exit 1
        }
        DASHBOARDS_OPENID_CONNECT_URL="${KEYCLOAK_DASHBOARDS_CONNECT_URL%/}/realms/${KEYCLOAK_AUTH_REALM}/.well-known/openid-configuration"
        DASHBOARDS_BASE_REDIRECT_URL="${KEYCLOAK_DASHBOARDS_REDIRECT_URI%/auth/openid/login}"
        cat >> "$FINAL_YML" <<EOF

opensearch_security.openid.connect_url: "$DASHBOARDS_OPENID_CONNECT_URL"
opensearch_security.openid.client_id: "$KEYCLOAK_DASHBOARDS_CLIENT_ID"
opensearch_security.openid.client_secret: "$KEYCLOAK_DASHBOARDS_CLIENT_SECRET"
opensearch_security.openid.base_redirect_url: "$DASHBOARDS_BASE_REDIRECT_URL"
opensearch_security.openid.verify_hostnames: true
EOF
    fi

    chmod 600 "$FINAL_YML"
fi

rm -f /tmp/shared-objects-created

# start the default dashboards entrypoint
exec "$@"
