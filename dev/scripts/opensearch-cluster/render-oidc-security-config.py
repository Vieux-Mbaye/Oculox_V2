#!/usr/bin/env python3

"""Render OpenSearch Security files with an OIDC domain for human users."""

from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path
from urllib.parse import urlparse

import yaml


PROJECT_DIR = Path(__file__).resolve().parents[3]
DEFAULT_SOURCE = PROJECT_DIR / "dev/generated/opensearch-cluster/security/config"
DEFAULT_OUTPUT = PROJECT_DIR / "dev/generated/opensearch-cluster/security/oidc-config"


ROLE_MAPPINGS = {
    "all_access": ["admin"],
    "dashboards_read_access": ["read_access", "dashboards_read_access"],
    "dashboards_all_apps_read_access": ["dashboards_read_all_apps_access"],
    "dashboards_read_write_access": ["read_write_access", "dashboards_read_write_access"],
    "alerting_read_access": ["read_access", "dashboards_read_access"],
    "anomaly_read_access": ["read_access", "dashboards_read_access"],
    "index_management_full_access": ["admin", "dashboards_read_write_access"],
    "notifications_read_access": ["read_access", "dashboards_read_access"],
    "reports_read_access": ["read_access", "dashboards_read_access"],
}


def load_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as stream:
        value = yaml.safe_load(stream)
    if not isinstance(value, dict):
        raise SystemExit(f"YAML invalide ou vide: {path}")
    return value


def write_yaml(path: Path, data: dict) -> None:
    with path.open("w", encoding="utf-8") as stream:
        yaml.safe_dump(data, stream, sort_keys=False, explicit_start=True)
    path.chmod(0o600)


def validate_url(value: str, label: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise SystemExit(f"{label} doit etre une URL HTTPS sans identifiants")
    if parsed.query or parsed.fragment:
        raise SystemExit(f"{label} ne doit pas contenir query string ou fragment")
    return value.rstrip("/")


def realm_discovery_url(auth_url: str, realm: str) -> str:
    auth_url = validate_url(auth_url, "KEYCLOAK_AUTH_URL")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", realm):
        raise SystemExit("Nom de realm Keycloak invalide")
    return f"{auth_url}/realms/{realm}/.well-known/openid-configuration"


def render_config(
    config: dict,
    discovery_url: str,
    client_id: str,
    roles_key: str,
    subject_key: str,
    idp_ca_path: str,
) -> dict:
    dynamic = config["config"]["dynamic"]
    authc = dynamic.setdefault("authc", {})
    basic = authc.setdefault("basic_internal_auth_domain", {})
    basic["order"] = 1
    basic.setdefault("http_authenticator", {})["challenge"] = False
    authc["openid_auth_domain"] = {
        "description": "Oculox human authentication through Keycloak OIDC",
        "http_enabled": True,
        "transport_enabled": False,
        "order": 0,
        "http_authenticator": {
            "type": "openid",
            "challenge": False,
            "config": {
                "subject_key": subject_key,
                "roles_key": roles_key,
                "openid_connect_url": discovery_url,
                "required_audience": client_id,
                "jwt_clock_skew_tolerance_seconds": 30,
                "openid_connect_idp": {
                    "enable_ssl": True,
                    "verify_hostnames": True,
                    "pemtrustedcas_filepath": idp_ca_path,
                },
            },
        },
        "authentication_backend": {"type": "noop"},
    }
    return config


def render_mappings(mappings: dict) -> dict:
    for role_name, backend_roles in ROLE_MAPPINGS.items():
        mapping = mappings.setdefault(
            role_name,
            {
                "reserved": True,
                "backend_roles": [],
                "hosts": [],
                "users": [],
                "and_backend_roles": [],
            },
        )
        existing = list(mapping.get("backend_roles") or [])
        for backend_role in backend_roles:
            if backend_role not in existing:
                existing.append(backend_role)
        mapping["backend_roles"] = existing
    return mappings


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--keycloak-auth-url", required=True)
    parser.add_argument("--realm", default="oculox")
    parser.add_argument("--client-id", default="oculox-dashboards")
    parser.add_argument("--roles-key", default="roles")
    parser.add_argument("--subject-key", default="preferred_username")
    parser.add_argument(
        "--idp-ca-path",
        default="/usr/share/opensearch/config/idp-trust/keycloak-ca.crt",
        help="Absolute path, inside each OpenSearch container, to the CA that signs the Keycloak HTTPS certificate.",
    )
    args = parser.parse_args()

    for name in ("config.yml", "internal_users.yml", "roles.yml", "roles_mapping.yml"):
        if not (args.source / name).is_file():
            raise SystemExit(f"Configuration Security absente: {args.source / name}")

    discovery_url = realm_discovery_url(args.keycloak_auth_url, args.realm)
    if args.output.exists():
        shutil.rmtree(args.output)
    args.output.mkdir(parents=True, mode=0o700)

    for path in args.source.glob("*.yml"):
        shutil.copy2(path, args.output / path.name)
        (args.output / path.name).chmod(0o600)

    config = render_config(
        load_yaml(args.output / "config.yml"),
        discovery_url,
        args.client_id,
        args.roles_key,
        args.subject_key,
        args.idp_ca_path,
    )
    mappings = render_mappings(load_yaml(args.output / "roles_mapping.yml"))
    write_yaml(args.output / "config.yml", config)
    write_yaml(args.output / "roles_mapping.yml", mappings)
    manifest = {
        "kind": "opensearch-security-oidc-config",
        "issuer_discovery_url": discovery_url,
        "client_id": args.client_id,
        "roles_key": args.roles_key,
        "subject_key": args.subject_key,
        "idp_ca_path": args.idp_ca_path,
        "basic_internal_auth_preserved": True,
    }
    (args.output / "oidc-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (args.output / "oidc-manifest.json").chmod(0o600)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
