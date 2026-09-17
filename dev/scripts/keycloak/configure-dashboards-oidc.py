#!/usr/bin/env python3

"""Activate, deactivate or verify OIDC for OpenSearch Dashboards."""

import argparse
import json
import re
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[3]
DASHBOARDS_ENV = PROJECT_DIR / "config" / "dashboards.env"
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


def require_realm_report(path: Path) -> None:
    if not path.is_file():
        raise SystemExit("Keycloak realm report is missing; run ./oculox keycloak provision first")
    report = json.loads(path.read_text(encoding="utf-8"))
    if report.get("result") != "PASS":
        raise SystemExit("Keycloak realm report is not PASS; rerun ./oculox keycloak provision")


def validate_runtime(keycloak: dict[str, str], public: dict[str, str], report_path: Path) -> None:
    require_realm_report(report_path)
    public_url = public.get("OCULOX_PUBLIC_URL", "").rstrip("/")
    auth_url = keycloak.get("KEYCLOAK_AUTH_URL", "").rstrip("/")
    if not public_url.startswith("https://") or not auth_url.startswith("https://"):
        raise SystemExit("Dashboards OIDC requires HTTPS public and Keycloak URLs")
    if public_origin(auth_url) != public_url:
        raise SystemExit("KEYCLOAK_AUTH_URL does not match the configured public endpoint")
    if keycloak.get("KEYCLOAK_AUTH_REALM") != "oculox":
        raise SystemExit("KEYCLOAK_AUTH_REALM must be oculox")
    if keycloak.get("KEYCLOAK_DASHBOARDS_CLIENT_ID") != "oculox-dashboards":
        raise SystemExit("KEYCLOAK_DASHBOARDS_CLIENT_ID must be oculox-dashboards")
    if len(keycloak.get("KEYCLOAK_DASHBOARDS_CLIENT_SECRET", "")) < 32:
        raise SystemExit("KEYCLOAK_DASHBOARDS_CLIENT_SECRET is missing")
    expected_redirect = f"{public_url}:5601/dashboards/auth/openid/login"
    if keycloak.get("KEYCLOAK_DASHBOARDS_REDIRECT_URI") != expected_redirect:
        raise SystemExit(f"KEYCLOAK_DASHBOARDS_REDIRECT_URI must be {expected_redirect}")


def activate(args: argparse.Namespace) -> None:
    keycloak = read_env(args.keycloak_env)
    public = read_env(args.public_endpoint_env)
    validate_runtime(keycloak, public, args.realm_report)
    update_env(args.dashboards_env, {"DASHBOARDS_AUTH_TYPE": "openid"})
    print("OpenSearch Dashboards authentication is set to OIDC.")


def deactivate(args: argparse.Namespace) -> None:
    update_env(args.dashboards_env, {"DASHBOARDS_AUTH_TYPE": "basicauth"})
    print("OpenSearch Dashboards authentication is set back to Basic.")


def verify(args: argparse.Namespace) -> None:
    dashboards = read_env(args.dashboards_env)
    keycloak = read_env(args.keycloak_env)
    public = read_env(args.public_endpoint_env)
    validate_runtime(keycloak, public, args.realm_report)
    checks = {
        "dashboards_auth_openid": dashboards.get("DASHBOARDS_AUTH_TYPE") == "openid",
        "dashboards_client_selected": keycloak.get("KEYCLOAK_DASHBOARDS_CLIENT_ID") == "oculox-dashboards",
        "dashboards_redirect_exact": keycloak.get("KEYCLOAK_DASHBOARDS_REDIRECT_URI")
        == f"{public.get('OCULOX_PUBLIC_URL', '').rstrip('/')}:5601/dashboards/auth/openid/login",
        "keycloak_ssl_verify_enabled": keycloak.get("KEYCLOAK_SSL_VERIFY") == "true",
    }
    result = {"checks": checks, "result": "PASS" if all(checks.values()) else "FAIL"}
    print(json.dumps(result, indent=2, sort_keys=True))
    if result["result"] != "PASS":
        raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("activate", "deactivate", "verify"))
    parser.add_argument("--dashboards-env", type=Path, default=DASHBOARDS_ENV)
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
