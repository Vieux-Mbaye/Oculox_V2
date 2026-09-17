#!/usr/bin/env python3

"""Verify the functional hardening contract for embedded Keycloak."""

import argparse
import json
import stat
import subprocess
import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[3]
AUTH_COMMON_ENV = PROJECT_DIR / "config" / "auth-common.env"
KEYCLOAK_ENV = PROJECT_DIR / "config" / "keycloak.env"
DASHBOARDS_ENV = PROJECT_DIR / "config" / "dashboards.env"
PUBLIC_ENDPOINT_ENV = PROJECT_DIR / "dev" / "generated" / "public-endpoint.env"
REALM_REPORT = PROJECT_DIR / "dev" / "generated" / "keycloak-provisioning" / "realm-report.json"
CREDENTIALS_FILE = PROJECT_DIR / "dev" / "generated" / "keycloak-initial-credentials.env"
KEYCLOAK_LOCATION = PROJECT_DIR / "nginx" / "nginx_keycloak_location.conf"


def read_env(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise FileNotFoundError(f"Runtime configuration is missing: {path}")
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            values[key] = value
    return values


def read_report(path: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError(f"Keycloak realm report is missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def mode_is_private(path: Path) -> bool:
    if not path.exists():
        return True
    return stat.S_IMODE(path.stat().st_mode) & 0o077 == 0


def git_untracked(paths: list[Path]) -> bool:
    existing = [path for path in paths if path.exists() and PROJECT_DIR in path.parents]
    if not existing:
        return True
    result = subprocess.run(
        ["git", "-C", str(PROJECT_DIR), "ls-files", "--", *[str(path.relative_to(PROJECT_DIR)) for path in existing]],
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip() == ""


def temporary_secrets_cleared(keycloak: dict[str, str]) -> bool:
    temporary_keys = (
        "KC_BOOTSTRAP_ADMIN_USERNAME",
        "KC_BOOTSTRAP_ADMIN_PASSWORD",
        "KEYCLOAK_INITIAL_ADMIN_PASSWORD",
        "KEYCLOAK_USER_ADMIN_PASSWORD",
        "KEYCLOAK_USER_ANALYST_PASSWORD",
        "KEYCLOAK_USER_VIEWER_PASSWORD",
        "KEYCLOAK_USER_INCIDENT_RESPONSE_PASSWORD",
        "KEYCLOAK_USER_DENIED_PASSWORD",
        "KEYCLOAK_CONSOLE_ADMIN_PASSWORD",
        "KEYCLOAK_RECOVERY_CLIENT_ID",
        "KEYCLOAK_RECOVERY_CLIENT_SECRET",
    )
    return all(keycloak.get(key, "") == "" for key in temporary_keys)


def admin_console_acl_configured(path: Path) -> bool:
    if not path.is_file():
        return False
    content = path.read_text(encoding="utf-8")
    required_fragments = (
        "location ^~ /keycloak/admin",
        "allow 127.0.0.1;",
        "allow 10.0.0.0/8;",
        "allow 172.16.0.0/12;",
        "allow 192.168.0.0/16;",
        "deny all;",
    )
    return all(fragment in content for fragment in required_fragments)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--auth-common-env", type=Path, default=AUTH_COMMON_ENV)
    parser.add_argument("--keycloak-env", type=Path, default=KEYCLOAK_ENV)
    parser.add_argument("--dashboards-env", type=Path, default=DASHBOARDS_ENV)
    parser.add_argument("--public-endpoint-env", type=Path, default=PUBLIC_ENDPOINT_ENV)
    parser.add_argument("--realm-report", type=Path, default=REALM_REPORT)
    parser.add_argument("--credentials-file", type=Path, default=CREDENTIALS_FILE)
    args = parser.parse_args()

    auth = read_env(args.auth_common_env)
    keycloak = read_env(args.keycloak_env)
    dashboards = read_env(args.dashboards_env)
    public = read_env(args.public_endpoint_env)
    report = read_report(args.realm_report)
    realm_security = report.get("realm_security", {})
    console_admin = report.get("keycloak_console_admin", {})
    clients = report.get("clients", {})

    public_url = public.get("OCULOX_PUBLIC_URL", "").rstrip("/")
    keycloak_url = keycloak.get("KEYCLOAK_AUTH_URL", "").rstrip("/")
    expected_dashboards_redirect = f"{public_url}:5601/dashboards/auth/openid/login"
    sensitive_paths = [
        args.keycloak_env,
        args.auth_common_env,
        args.dashboards_env,
        args.credentials_file,
        PROJECT_DIR / "nginx" / "certs" / "key.pem",
    ]

    checks = {
        "portal_uses_keycloak": auth.get("NGINX_AUTH_MODE") == "keycloak",
        "portal_rbac_enabled": auth.get("ROLE_BASED_ACCESS") == "true",
        "portal_requires_oculox_users_group": auth.get("NGINX_REQUIRE_GROUP") == "/oculox-users",
        "dashboards_uses_openid": dashboards.get("DASHBOARDS_AUTH_TYPE") == "openid",
        "realm_report_passed": report.get("result") == "PASS",
        "realm_is_oculox": keycloak.get("KEYCLOAK_AUTH_REALM") == "oculox",
        "public_endpoint_is_https": public_url.startswith("https://"),
        "keycloak_url_matches_public_endpoint": keycloak_url == f"{public_url}/keycloak",
        "portal_uses_internal_keycloak_connect_url": keycloak.get(
            "KEYCLOAK_NGINX_CONNECT_URL"
        ) == "http://keycloak:8080/keycloak",
        "hostname_strict": keycloak.get("KC_HOSTNAME_STRICT") == "true",
        "hostname_backchannel_dynamic": keycloak.get("KC_HOSTNAME_BACKCHANNEL_DYNAMIC") == "true",
        "tls_verification_enabled": keycloak.get("KEYCLOAK_SSL_VERIFY") == "true",
        "mfa_required": keycloak.get("KEYCLOAK_MFA_REQUIRED") == "true",
        "mfa_required_action_enabled": realm_security.get("mfa_required_action_enabled") is True,
        "mfa_required_action_default": realm_security.get("mfa_required_action_default") is True,
        "brute_force_protection_enabled": realm_security.get("brute_force_protected") is True,
        "refresh_token_rotation_enabled": realm_security.get("refresh_token_rotation") is True,
        "short_access_tokens": int(keycloak.get("KEYCLOAK_ACCESS_TOKEN_LIFESPAN_SECONDS", "999999")) <= 900,
        "events_enabled": realm_security.get("events_enabled") is True,
        "admin_events_enabled": realm_security.get("admin_events_enabled") is True,
        "admin_event_details_enabled": realm_security.get("admin_event_details_enabled") is True,
        "keycloak_console_admin_available": (
            console_admin.get("realm") == "master"
            and "admin" in console_admin.get("realm_roles", [])
        ),
        "keycloak_admin_console_acl_configured": admin_console_acl_configured(KEYCLOAK_LOCATION),
        "portal_redirect_exact": keycloak.get("KEYCLOAK_AUTH_REDIRECT_URI") == "/index.html",
        "dashboards_redirect_exact": keycloak.get("KEYCLOAK_DASHBOARDS_REDIRECT_URI") == expected_dashboards_redirect,
        "dashboards_uses_internal_keycloak_connect_url": keycloak.get(
            "KEYCLOAK_DASHBOARDS_CONNECT_URL"
        ) == "http://keycloak:8080/keycloak",
        "portal_client_direct_grants_disabled": clients.get("portal", {}).get("direct_grants") is False,
        "dashboards_client_direct_grants_disabled": clients.get("dashboards", {}).get("direct_grants") is False,
        "provisioning_disabled_after_apply": keycloak.get("KEYCLOAK_PROVISIONING_ENABLED") == "false",
        "temporary_runtime_secrets_cleared": temporary_secrets_cleared(keycloak),
        "sensitive_files_private": all(mode_is_private(path) for path in sensitive_paths),
        "sensitive_runtime_files_not_tracked": git_untracked(sensitive_paths),
    }
    result = {
        "schema": 1,
        "kind": "keycloak-functional-hardening",
        "checks": checks,
        "result": "PASS" if all(checks.values()) else "FAIL",
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["result"] == "PASS" else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (FileNotFoundError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"Keycloak hardening verification failed: {exc}", file=sys.stderr)
        sys.exit(1)
