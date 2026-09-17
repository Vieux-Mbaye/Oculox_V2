#!/usr/bin/env python3

"""Activate, deactivate or verify Keycloak as the Oculox portal authenticator."""

import argparse
import json
import re
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[3]
AUTH_COMMON_ENV = PROJECT_DIR / "config" / "auth-common.env"
KEYCLOAK_ENV = PROJECT_DIR / "config" / "keycloak.env"
PUBLIC_ENDPOINT_ENV = PROJECT_DIR / "dev" / "generated" / "public-endpoint.env"
REALM_REPORT = PROJECT_DIR / "dev" / "generated" / "keycloak-provisioning" / "realm-report.json"


def read_env(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise FileNotFoundError(f"Runtime configuration is missing: {path}")
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            values[key] = value
    return values


def update_env(path: Path, values: dict[str, str]) -> None:
    original = path.read_text(encoding="utf-8")
    remaining = dict(values)
    rendered: list[str] = []
    for line in original.splitlines():
        key = line.split("=", 1)[0] if "=" in line else ""
        if key in remaining:
            rendered.append(f"{key}={remaining.pop(key)}")
        else:
            rendered.append(line)
    rendered.extend(f"{key}={value}" for key, value in remaining.items())
    content = "\n".join(rendered) + "\n"
    if content != original:
        path.write_text(content, encoding="utf-8")
    path.chmod(0o600)


def public_origin(auth_url: str) -> str:
    return re.sub(r"/keycloak/?$", "", auth_url.rstrip("/"))


def require_provisioned(report_path: Path) -> None:
    if not report_path.is_file():
        raise SystemExit("Keycloak realm report is missing; run ./oculox keycloak provision first")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("result") != "PASS":
        raise SystemExit("Keycloak realm report is not PASS; rerun ./oculox keycloak provision")


def validate_runtime(keycloak: dict[str, str], public: dict[str, str], report_path: Path) -> None:
    require_provisioned(report_path)
    auth_url = keycloak.get("KEYCLOAK_AUTH_URL", "").rstrip("/")
    public_url = public.get("OCULOX_PUBLIC_URL", "").rstrip("/")
    if not auth_url.startswith("https://") or not public_url.startswith("https://"):
        raise SystemExit("Keycloak portal activation requires an HTTPS public endpoint")
    if public_origin(auth_url) != public_url:
        raise SystemExit("KEYCLOAK_AUTH_URL does not match the configured Oculox public URL")
    if keycloak.get("KEYCLOAK_AUTH_REALM") != "oculox":
        raise SystemExit("KEYCLOAK_AUTH_REALM must be oculox")
    if keycloak.get("KEYCLOAK_PORTAL_CLIENT_ID") != "oculox-portal":
        raise SystemExit("KEYCLOAK_PORTAL_CLIENT_ID must be oculox-portal")
    if len(keycloak.get("KEYCLOAK_PORTAL_CLIENT_SECRET", "")) < 32:
        raise SystemExit("KEYCLOAK_PORTAL_CLIENT_SECRET is missing; run ./oculox keycloak provision first")
    redirect = keycloak.get("KEYCLOAK_AUTH_REDIRECT_URI", "")
    if redirect != "/index.html":
        raise SystemExit("KEYCLOAK_AUTH_REDIRECT_URI must stay the exact portal callback /index.html")


def activate(args: argparse.Namespace) -> None:
    keycloak = read_env(args.keycloak_env)
    public = read_env(args.public_endpoint_env)
    validate_runtime(keycloak, public, args.realm_report)
    portal_secret = keycloak["KEYCLOAK_PORTAL_CLIENT_SECRET"]
    update_env(
        args.keycloak_env,
        {
            "KEYCLOAK_CLIENT_ID": "oculox-portal",
            "KEYCLOAK_CLIENT_SECRET": portal_secret,
            "KEYCLOAK_PROVISIONING_ENABLED": "false",
            "KEYCLOAK_SSL_VERIFY": "true",
        },
    )
    update_env(
        args.auth_common_env,
        {
            "NGINX_AUTH_MODE": "keycloak",
            "NGINX_KEYCLOAK_BASIC_AUTH": "false",
            "ROLE_BASED_ACCESS": "true",
            "NGINX_REQUIRE_GROUP": "/oculox-users",
            "NGINX_REQUIRE_ROLE": "",
        },
    )
    print("Oculox portal authentication is set to embedded Keycloak.")


def deactivate(args: argparse.Namespace) -> None:
    update_env(
        args.auth_common_env,
        {
            "NGINX_AUTH_MODE": "basic",
            "NGINX_KEYCLOAK_BASIC_AUTH": "false",
            "ROLE_BASED_ACCESS": "false",
            "NGINX_REQUIRE_GROUP": "",
            "NGINX_REQUIRE_ROLE": "",
        },
    )
    update_env(args.keycloak_env, {"KEYCLOAK_PROVISIONING_ENABLED": "false"})
    print("Oculox portal authentication is set back to Basic.")


def verify(args: argparse.Namespace) -> None:
    auth = read_env(args.auth_common_env)
    keycloak = read_env(args.keycloak_env)
    public = read_env(args.public_endpoint_env)
    validate_runtime(keycloak, public, args.realm_report)
    checks = {
        "auth_mode_keycloak": auth.get("NGINX_AUTH_MODE") == "keycloak",
        "rbac_enabled": auth.get("ROLE_BASED_ACCESS") == "true",
        "required_group": auth.get("NGINX_REQUIRE_GROUP") == "/oculox-users",
        "service_account_basic_fallback_disabled": auth.get("NGINX_KEYCLOAK_BASIC_AUTH", "false") == "false",
        "portal_client_selected": keycloak.get("KEYCLOAK_CLIENT_ID") == "oculox-portal",
        "ssl_verify_enabled": keycloak.get("KEYCLOAK_SSL_VERIFY") == "true",
    }
    result = {"checks": checks, "result": "PASS" if all(checks.values()) else "FAIL"}
    print(json.dumps(result, indent=2, sort_keys=True))
    if result["result"] != "PASS":
        raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("activate", "deactivate", "verify"))
    parser.add_argument("--auth-common-env", type=Path, default=AUTH_COMMON_ENV)
    parser.add_argument("--keycloak-env", type=Path, default=KEYCLOAK_ENV)
    parser.add_argument("--public-endpoint-env", type=Path, default=PUBLIC_ENDPOINT_ENV)
    parser.add_argument("--realm-report", type=Path, default=REALM_REPORT)
    args = parser.parse_args()
    if args.action == "activate":
        activate(args)
    elif args.action == "deactivate":
        deactivate(args)
    else:
        verify(args)


if __name__ == "__main__":
    main()
