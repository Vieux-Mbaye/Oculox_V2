#!/usr/bin/env bash

set -euo pipefail

IMAGE="ghcr.io/idaholab/malcolm/opensearch:26.07.1"
NETWORK="oculox-opensearch-transport"
TARGET="opensearch-1"
ACCOUNTS_ENV=""
ADMIN_DIR=""
CA_FILE=""

usage() {
  cat <<'EOF'
Usage: test_security_runtime.sh --accounts-env FILE --admin-dir DIR --ca FILE

Verifie le cluster, les comptes de service et les refus imposes par le plugin
OpenSearch Security. Les mots de passe ne sont jamais affiches.
EOF
}

while (($#)); do
  case "$1" in
    --accounts-env) ACCOUNTS_ENV="$2"; shift 2 ;;
    --admin-dir) ADMIN_DIR="$2"; shift 2 ;;
    --ca) CA_FILE="$2"; shift 2 ;;
    --network) NETWORK="$2"; shift 2 ;;
    --target) TARGET="$2"; shift 2 ;;
    --image) IMAGE="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Option inconnue: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ -r "${ACCOUNTS_ENV}" ]] || { echo "Fichier de comptes absent" >&2; exit 1; }
[[ -r "${CA_FILE}" ]] || { echo "CA absente" >&2; exit 1; }
for file in admin.crt admin.key ca.crt; do
  [[ -r "${ADMIN_DIR}/${file}" ]] || { echo "Fichier admin absent: ${file}" >&2; exit 1; }
done

set -a
# shellcheck disable=SC1090
source "${ACCOUNTS_ENV}"
set +a

WORK_DIR="$(mktemp -d)"
trap 'rm -rf -- "${WORK_DIR}"' EXIT
chmod 700 "${WORK_DIR}"
cp "${CA_FILE}" "${WORK_DIR}/ca.crt"
cp "${ADMIN_DIR}/admin.crt" "${WORK_DIR}/admin.crt"
cp "${ADMIN_DIR}/admin.key" "${WORK_DIR}/admin.key"
chmod 600 "${WORK_DIR}"/*

write_basic_config() {
  local name="$1" username="$2" password="$3"
  cat >"${WORK_DIR}/${name}.curlrc" <<EOF
cacert = "/auth/ca.crt"
user = "${username}:${password}"
silent
show-error
EOF
  chmod 600 "${WORK_DIR}/${name}.curlrc"
}

write_basic_config platform_admin oculox_platform_admin "${OCULOX_PLATFORM_ADMIN_PASSWORD}"
write_basic_config logstash oculox_logstash "${OCULOX_LOGSTASH_PASSWORD}"
write_basic_config arkime oculox_arkime "${OCULOX_ARKIME_PASSWORD}"
write_basic_config dashboards oculox_dashboards "${OCULOX_DASHBOARDS_PASSWORD}"
write_basic_config helper oculox_dashboards_helper "${OCULOX_DASHBOARDS_HELPER_PASSWORD}"
write_basic_config api oculox_api "${OCULOX_API_PASSWORD}"
write_basic_config snapshot oculox_snapshot "${OCULOX_SNAPSHOT_PASSWORD}"
cat >"${WORK_DIR}/admin.curlrc" <<'EOF'
cacert = "/auth/ca.crt"
cert = "/auth/admin.crt"
key = "/auth/admin.key"
silent
show-error
EOF
chmod 600 "${WORK_DIR}/admin.curlrc"

request() {
  local identity="$1" method="$2" path="$3" data="${4:-}"
  local -a args=(--config "/auth/${identity}.curlrc" --request "${method}" --write-out $'\n%{http_code}')
  [[ -z "${data}" ]] || args+=(--header 'Content-Type: application/json' --data "${data}")
  docker run --rm --network "${NETWORK}" --entrypoint curl \
    --mount "type=bind,src=${WORK_DIR},dst=/auth,readonly" \
    "${IMAGE}" "${args[@]}" "https://${TARGET}:9200${path}"
}

expect_code() {
  local label="$1" expected="$2" identity="$3" method="$4" path="$5" data="${6:-}"
  local response code
  response="$(request "${identity}" "${method}" "${path}" "${data}")"
  code="${response##*$'\n'}"
  if [[ "${code}" != "${expected}" ]]; then
    echo "${label}=FAIL expected=${expected} actual=${code}" >&2
    exit 1
  fi
  echo "${label}=PASS http=${code}"
  RESPONSE_BODY="${response%$'\n'*}"
}

expect_code cluster_admin_health 200 platform_admin GET '/_cluster/health'
python3 -c 'import json,sys; d=json.loads(sys.stdin.read()); assert d["number_of_nodes"] == 3; assert d["status"] == "green"; assert d["unassigned_shards"] == 0' <<<"${RESPONSE_BODY}"
echo "cluster_three_nodes_green=PASS"

expect_code admin_certificate_security_api 200 admin GET '/_plugins/_security/api/internalusers'
python3 -c 'import json,sys; d=json.loads(sys.stdin.read()); expected={"oculox_platform_admin","oculox_logstash","oculox_arkime","oculox_dashboards","oculox_dashboards_helper","oculox_api","oculox_snapshot"}; assert set(d) == expected; assert "malcolm_internal" not in d' <<<"${RESPONSE_BODY}"
echo "security_accounts_exact_set=PASS"

cleanup_resource() {
  local path="$1" response code
  response="$(request platform_admin DELETE "${path}")"
  code="${response##*$'\n'}"
  [[ "${code}" == "200" || "${code}" == "404" ]] || {
    echo "pretest_cleanup=FAIL path=${path} http=${code}" >&2
    exit 1
  }
}

for index in \
  malcolm_beats_security_test \
  arkime_security_test \
  outside_security_test \
  malcolm_beats_arkime_forbidden \
  malcolm_beats_dashboards_forbidden \
  malcolm_beats_snapshot_forbidden; do
  cleanup_resource "/${index}"
done
cleanup_resource '/_index_template/oculox-security-test-template'
echo "pretest_cleanup=PASS"

expect_code logstash_create_allowed 200 logstash PUT '/malcolm_beats_security_test'
expect_code logstash_write_allowed 201 logstash POST '/malcolm_beats_security_test/_doc' '{"test":"security","source":"logstash"}'
expect_code logstash_out_of_role_denied 403 logstash PUT '/outside_security_test'

expect_code arkime_create_allowed 200 arkime PUT '/arkime_security_test'
expect_code arkime_out_of_role_denied 403 arkime PUT '/malcolm_beats_arkime_forbidden'

expect_code api_read_allowed 200 api GET '/malcolm_beats_security_test/_search'
expect_code api_write_denied 403 api POST '/malcolm_beats_security_test/_doc' '{"forbidden":true}'

expect_code dashboards_account_allowed 200 dashboards GET '/_plugins/_security/api/account'
expect_code dashboards_application_write_denied 403 dashboards PUT '/malcolm_beats_dashboards_forbidden'

expect_code helper_template_allowed 200 helper PUT '/_index_template/oculox-security-test-template' '{"index_patterns":["oculox-security-test-*"]}'
expect_code snapshot_listing_allowed 200 snapshot GET '/_snapshot/_all'
expect_code snapshot_index_read_denied 403 snapshot GET '/malcolm_beats_security_test/_search'

response="$(docker run --rm --network "${NETWORK}" --entrypoint curl \
  --mount "type=bind,src=${WORK_DIR},dst=/auth,readonly" "${IMAGE}" \
  --cacert /auth/ca.crt --silent --output /dev/null --write-out '%{http_code}' \
  "https://${TARGET}:9200/")"
[[ "${response}" == "401" ]] || { echo "anonymous_denied=FAIL http=${response}" >&2; exit 1; }
echo "anonymous_denied=PASS http=401"

set +e
docker run --rm --network "${NETWORK}" --entrypoint curl "${IMAGE}" \
  --silent --show-error --output /dev/null "https://${TARGET}:9200/" >/dev/null 2>&1
untrusted_rc=$?
set -e
[[ "${untrusted_rc}" -ne 0 ]] || { echo "untrusted_ca_denied=FAIL" >&2; exit 1; }
echo "untrusted_ca_denied=PASS curl_exit=${untrusted_rc}"

expect_code cleanup_logstash_index 200 platform_admin DELETE '/malcolm_beats_security_test'
expect_code cleanup_arkime_index 200 platform_admin DELETE '/arkime_security_test'
expect_code cleanup_template 200 platform_admin DELETE '/_index_template/oculox-security-test-template'

echo "SECURITY_RUNTIME_RESULT=PASS"
