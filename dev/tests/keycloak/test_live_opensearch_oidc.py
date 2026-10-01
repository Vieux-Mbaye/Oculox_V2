#!/usr/bin/env python3
"""Explicit live OIDC/RBAC test using a disposable Keycloak service identity.

Does not change human users, MFA, production clients or OpenSearch mappings.
The temporary client is deleted even when authentication tests fail.
"""

import argparse
import json
import secrets
import re
import subprocess
import ssl
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def env(path):
    return dict(line.split("=", 1) for line in path.read_text().splitlines()
                if "=" in line and not line.startswith("#"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-live", action="store_true", required=True)
    parser.add_argument("--cluster-ssh", help="Optional user@host to check each node directly via SSH")
    parser.add_argument("--sshpass-env", action="store_true", help="Read SSH password from SSHPASS, never from arguments")
    args = parser.parse_args()
    keycloak = env(ROOT / "config/keycloak.env")
    cluster = env(ROOT / "config/opensearch.env")
    web_context = ssl.create_default_context(cafile=str(ROOT / "nginx/ca-trust/oculox-web-ca.crt"))
    cluster_context = ssl.create_default_context(cafile=str(ROOT / "nginx/ca-trust/oculox-opensearch-ca.crt"))
    kc = keycloak["KEYCLOAK_AUTH_URL"].rstrip("/")
    realm = keycloak["KEYCLOAK_AUTH_REALM"]
    if args.cluster_ssh and not re.fullmatch(r"[A-Za-z0-9_.-]+@[A-Za-z0-9_.-]+", args.cluster_ssh):
        raise ValueError("Invalid Cluster SSH identity")

    def request(url, method="GET", body=None, token=None, form=False, context=web_context):
        headers = {}
        if token:
            headers["Authorization"] = "Bearer " + token
        payload = None
        if body is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded" if form else "application/json"
            payload = (urllib.parse.urlencode(body) if form else json.dumps(body)).encode()
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                             urllib.request.HTTPSHandler(context=context))
        with opener.open(urllib.request.Request(url, data=payload, method=method, headers=headers), timeout=30) as response:
            data = response.read()
            return json.loads(data) if data else None

    admin = request(kc + "/realms/master/protocol/openid-connect/token", "POST", {
        "grant_type": "client_credentials", "client_id": keycloak["KEYCLOAK_PROVISIONER_CLIENT_ID"],
        "client_secret": keycloak["KEYCLOAK_PROVISIONER_CLIENT_SECRET"]}, form=True)["access_token"]
    api = kc + "/admin/realms/" + realm
    name, secret = "oculox-oidc-recette-" + secrets.token_hex(8), secrets.token_urlsafe(32)
    uuid = None
    try:
        request(api + "/clients", "POST", {"clientId": name, "secret": secret, "enabled": True,
            "publicClient": False, "serviceAccountsEnabled": True, "standardFlowEnabled": False,
            "directAccessGrantsEnabled": False, "fullScopeAllowed": True,
            "protocolMappers": [
                {"name": "audience", "protocol": "openid-connect", "protocolMapper": "oidc-audience-mapper",
                 "config": {"included.client.audience": "oculox-dashboards", "access.token.claim": "true"}},
                {"name": "roles", "protocol": "openid-connect", "protocolMapper": "oidc-usermodel-realm-role-mapper",
                 "config": {"claim.name": "roles", "jsonType.label": "String", "multivalued": "true",
                            "access.token.claim": "true"}}]}, admin)
        clients = request(api + "/clients?clientId=" + name, token=admin)
        uuid = clients[0]["id"]
        user = request(api + f"/clients/{uuid}/service-account-user", token=admin)["id"]
        role_url = api + f"/users/{user}/role-mappings/realm"
        for role_name, expected in (("read_access", "dashboards_read_access"), ("admin", "all_access")):
            role = request(api + "/roles/" + role_name, token=admin)
            request(role_url, "POST", [role], admin)
            try:
                token = request(kc + f"/realms/{realm}/protocol/openid-connect/token", "POST", {
                    "grant_type": "client_credentials", "client_id": name, "client_secret": secret}, form=True)["access_token"]
                result = request(cluster["OPENSEARCH_URL"].rstrip("/") + "/_plugins/_security/authinfo",
                                 token=token, context=cluster_context)
                if role_name not in result.get("backend_roles", []) or expected not in result.get("roles", []):
                    raise RuntimeError("OIDC token role did not map to expected OpenSearch permissions")
                if role_name == "read_access" and "all_access" in result.get("roles", []):
                    raise RuntimeError("Read-only identity unexpectedly has all_access")
                print(f"PASS signed Keycloak token: {role_name} -> {expected}", flush=True)
                if args.cluster_ssh:
                    for node in ("opensearch-1", "opensearch-2", "opensearch-3"):
                        command = (f"docker exec -i oculox-opensearch-cluster-{node}-1 curl "
                            f"--noproxy '*' --silent --show-error --fail --max-time 20 "
                            f"--cacert /usr/share/opensearch/config/certs/ca.crt "
                            f"--resolve {node}:9200:127.0.0.1 --config /dev/stdin "
                            f"https://{node}:9200/_plugins/_security/authinfo")
                        ssh = (["sshpass", "-e"] if args.sshpass_env else []) + ["ssh", "-F", "/dev/null",
                            "-o", "StrictHostKeyChecking=yes", args.cluster_ssh, command]
                        output = subprocess.run(ssh, input=f'header = "Authorization: Bearer {token}"\n',
                            capture_output=True, text=True, check=True, timeout=40)
                        info = json.loads(output.stdout)
                        if expected not in info.get("roles", []) or role_name not in info.get("backend_roles", []):
                            raise RuntimeError(f"OIDC role check failed on {node}")
                        if role_name == "read_access" and "all_access" in info.get("roles", []):
                            raise RuntimeError(f"Unexpected admin access on {node}")
                        print(f"PASS {node}: signed token and {role_name} mapping", flush=True)
            finally:
                request(role_url, "DELETE", [role], admin)
        mappers = request(api + f"/clients/{uuid}/protocol-mappers/models", token=admin)
        audience = next(mapper for mapper in mappers if mapper["name"] == "audience")
        audience["config"]["included.client.audience"] = "not-oculox-dashboards"
        request(api + f"/clients/{uuid}/protocol-mappers/models/{audience['id']}", "PUT", audience, admin)
        wrong = request(kc + f"/realms/{realm}/protocol/openid-connect/token", "POST", {
            "grant_type": "client_credentials", "client_id": name, "client_secret": secret}, form=True)["access_token"]
        try:
            request(cluster["OPENSEARCH_URL"].rstrip("/") + "/_plugins/_security/authinfo",
                    token=wrong, context=cluster_context)
        except urllib.error.HTTPError as error:
            if error.code != 401:
                raise
            print("PASS signed token with wrong audience rejected (401)", flush=True)
        else:
            raise RuntimeError("Wrong audience unexpectedly accepted")
    finally:
        # Query by unpredictable name also handles a failed response after client creation.
        if uuid is None:
            clients = request(api + "/clients?clientId=" + name, token=admin)
            uuid = clients[0]["id"] if clients else None
        if uuid:
            request(api + "/clients/" + uuid, "DELETE", token=admin)
            print("PASS temporary Keycloak client removed", flush=True)
    print("LIVE_OIDC_RBAC_RESULT=PASS; interactive browser/MFA flow not exercised")


if __name__ == "__main__":
    main()
