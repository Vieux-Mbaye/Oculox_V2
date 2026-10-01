#!/usr/bin/env python3

"""Render the public Oculox identity without embedding deployment addresses in Git."""

import argparse
import ipaddress
import re
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = PROJECT_DIR / "dev/generated/public-endpoint.env"
DNS_LABEL = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")


def normalize_host(value: str) -> tuple[str, str, str, str]:
    candidate = value.strip()
    if not candidate or "://" in candidate or "/" in candidate:
        raise ValueError("provide an IP address or DNS name, not a URL or path")

    try:
        address = ipaddress.ip_address(candidate)
    except ValueError:
        dns_name = candidate.rstrip(".").lower()
        if len(dns_name) > 253 or not dns_name or any(
            not DNS_LABEL.fullmatch(label) for label in dns_name.split(".")
        ):
            raise ValueError("invalid DNS name") from None
        return dns_name, "dns", f"DNS:{dns_name}", dns_name

    url_host = f"[{address.compressed}]" if address.version == 6 else address.compressed
    return address.compressed, f"ipv{address.version}", f"IP:{address.compressed}", url_host


def update_env(path: Path, values: dict[str, str]) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"runtime configuration is missing: {path}")
    lines = path.read_text(encoding="utf-8").splitlines()
    remaining = dict(values)
    rendered: list[str] = []
    for line in lines:
        key = line.split("=", 1)[0] if "=" in line else ""
        if key in remaining:
            rendered.append(f"{key}={remaining.pop(key)}")
        else:
            rendered.append(line)
    rendered.extend(f"{key}={value}" for key, value in remaining.items())
    content = "\n".join(rendered) + "\n"
    if path.read_text(encoding="utf-8") != content:
        path.write_text(content, encoding="utf-8")
    path.chmod(0o600)


def write_if_changed(path: Path, content: str, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.read_text(encoding="utf-8") != content:
        path.write_text(content, encoding="utf-8")
    path.chmod(mode)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--public-host", required=True, help="IPv4, IPv6 or DNS name of the Core")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--keycloak-env", type=Path, default=PROJECT_DIR / "config/keycloak.env")
    parser.add_argument(
        "--dashboards-helper-env",
        type=Path,
        default=PROJECT_DIR / "config/dashboards-helper.env",
    )
    parser.add_argument("--deployment-env", type=Path, default=PROJECT_DIR / "dev/generated/deployment.env")
    args = parser.parse_args()

    try:
        host, identity_type, san, url_host = normalize_host(args.public_host)
    except ValueError as error:
        raise SystemExit(f"Invalid public identity: {error}") from error

    public_url = f"https://{url_host}"
    keycloak_url = f"{public_url}/keycloak"
    dashboards_redirect_uri = f"{public_url}:5601/dashboards/auth/openid/login"
    values = {
        "OCULOX_PUBLIC_HOST": host,
        "OCULOX_PUBLIC_IDENTITY_TYPE": identity_type,
        "OCULOX_PUBLIC_SAN": san,
        "OCULOX_PUBLIC_URL": public_url,
        "OCULOX_KEYCLOAK_URL": keycloak_url,
    }
    write_if_changed(
        args.output,
        "".join(f"{key}={value}\n" for key, value in values.items()),
        0o600,
    )

    update_env(
        args.keycloak_env,
        {
            "KEYCLOAK_AUTH_REALM": "oculox",
            "KEYCLOAK_BOOTSTRAP_REALM": "master",
            "KEYCLOAK_AUTH_REDIRECT_URI": "/index.html",
            "KEYCLOAK_AUTH_URL": keycloak_url,
            "KEYCLOAK_DASHBOARDS_REDIRECT_URI": dashboards_redirect_uri,
            "KEYCLOAK_SSL_VERIFY": "true",
            "KC_HOSTNAME": keycloak_url,
            "KC_HOSTNAME_BACKCHANNEL_DYNAMIC": "true",
            "KC_HOSTNAME_STRICT": "true",
        },
    )
    update_env(
        args.dashboards_helper_env,
        {
            "MALCOLM_URL": public_url,
        },
    )
    update_env(
        args.deployment_env,
        {
            "OCULOX_SERVER_NAME": host,
            "OCULOX_PUBLIC_URL": public_url,
            "OCULOX_KEYCLOAK_URL": keycloak_url,
        },
    )
    print(f"Public Oculox identity configured: {public_url} ({san})")


if __name__ == "__main__":
    main()
