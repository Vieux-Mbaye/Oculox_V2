#!/usr/bin/env python3

"""Prepare or finalize the local runtime configuration for Keycloak IAM."""

import argparse
import re
import secrets
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[3]
KEYCLOAK_ENV = PROJECT_DIR / "config" / "keycloak.env"
AUTH_COMMON_ENV = PROJECT_DIR / "config" / "auth-common.env"
PUBLIC_ENDPOINT_ENV = PROJECT_DIR / "dev" / "generated" / "public-endpoint.env"
DEFAULT_CREDENTIALS = PROJECT_DIR / "dev" / "generated" / "keycloak-initial-credentials.env"
USERNAME = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{2,63}$")


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


def random_secret() -> str:
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789!@#%^&*-_"
    required = [
        secrets.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ"),
        secrets.choice("abcdefghijklmnopqrstuvwxyz"),
        secrets.choice("0123456789"),
        secrets.choice("!@#%^&*-_"),
    ]
    required.extend(secrets.choice(alphabet) for _ in range(44))
    secrets.SystemRandom().shuffle(required)
    return "".join(required)


def retained_secret(current: dict[str, str], credentials: dict[str, str], key: str) -> str:
    candidate = current.get(key) or credentials.get(key) or ""
    if (
        len(candidate) >= 14
        and any(character.isupper() for character in candidate)
        and any(character.islower() for character in candidate)
        and any(character.isdigit() for character in candidate)
        and "$" not in candidate
        and any(character in "!@#%^&*-_" for character in candidate)
    ):
        return candidate
    return random_secret()


def retained_client_secret(current: dict[str, str], key: str) -> str:
    candidate = current.get(key, "")
    return candidate if len(candidate) >= 32 and "$" not in candidate else random_secret()


def write_credentials(path: Path, values: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "".join(f"{key}={value}\n" for key, value in values.items())
    if not path.exists() or path.read_text(encoding="utf-8") != content:
        path.write_text(content, encoding="utf-8")
    path.chmod(0o600)


def prepare(args: argparse.Namespace) -> None:
    current = read_env(args.keycloak_env)
    public = read_env(args.public_endpoint_env)
    credentials = read_env(args.credentials_file) if args.credentials_file.exists() else {}
    public_url = public.get("OCULOX_PUBLIC_URL", "").rstrip("/")
    keycloak_url = public.get("OCULOX_KEYCLOAK_URL", "").rstrip("/")
    if not public_url.startswith("https://") or not keycloak_url.startswith("https://"):
        raise SystemExit("Public HTTPS identity is missing; run ./oculox prepare principal first")
    if not USERNAME.fullmatch(args.admin_username):
        raise SystemExit("Invalid initial administrator username")

    initial_credentials = {
        "KEYCLOAK_INITIAL_ADMIN_USERNAME": args.admin_username,
        "KEYCLOAK_INITIAL_ADMIN_PASSWORD": retained_secret(current, credentials, "KEYCLOAK_INITIAL_ADMIN_PASSWORD"),
        "KEYCLOAK_CONSOLE_ADMIN_USERNAME": current.get("KEYCLOAK_CONSOLE_ADMIN_USERNAME")
        or credentials.get("KEYCLOAK_CONSOLE_ADMIN_USERNAME")
        or "oculox-keycloak-admin",
        "KEYCLOAK_CONSOLE_ADMIN_PASSWORD": retained_secret(current, credentials, "KEYCLOAK_CONSOLE_ADMIN_PASSWORD"),
        "KEYCLOAK_USER_ADMIN_PASSWORD": retained_secret(current, credentials, "KEYCLOAK_USER_ADMIN_PASSWORD"),
        "KEYCLOAK_USER_ANALYST_PASSWORD": retained_secret(current, credentials, "KEYCLOAK_USER_ANALYST_PASSWORD"),
        "KEYCLOAK_USER_VIEWER_PASSWORD": retained_secret(current, credentials, "KEYCLOAK_USER_VIEWER_PASSWORD"),
        "KEYCLOAK_USER_INCIDENT_RESPONSE_PASSWORD": retained_secret(
            current, credentials, "KEYCLOAK_USER_INCIDENT_RESPONSE_PASSWORD"
        ),
        "KEYCLOAK_USER_DENIED_PASSWORD": retained_secret(current, credentials, "KEYCLOAK_USER_DENIED_PASSWORD"),
    }
    portal_secret = retained_client_secret(
        current,
        "KEYCLOAK_PORTAL_CLIENT_SECRET" if current.get("KEYCLOAK_PORTAL_CLIENT_SECRET") else "KEYCLOAK_CLIENT_SECRET",
    )
    dashboards_secret = retained_client_secret(current, "KEYCLOAK_DASHBOARDS_CLIENT_SECRET")
    provisioner_secret = retained_client_secret(current, "KEYCLOAK_PROVISIONER_CLIENT_SECRET")
    recovery_secret = retained_client_secret(current, "KEYCLOAK_RECOVERY_CLIENT_SECRET")
    update_env(
        args.keycloak_env,
        {
            "KEYCLOAK_PROVISIONING_ENABLED": "true",
            "KEYCLOAK_CLIENT_ID": "oculox-portal",
            "KEYCLOAK_CLIENT_SECRET": portal_secret,
            "KEYCLOAK_PORTAL_CLIENT_ID": "oculox-portal",
            "KEYCLOAK_PORTAL_CLIENT_SECRET": portal_secret,
            "KEYCLOAK_DASHBOARDS_CLIENT_ID": "oculox-dashboards",
            "KEYCLOAK_DASHBOARDS_CLIENT_SECRET": dashboards_secret,
            "KEYCLOAK_DASHBOARDS_REDIRECT_URI": f"{public_url}:5601/dashboards/auth/openid/login",
            "KEYCLOAK_NGINX_CONNECT_URL": current.get(
                "KEYCLOAK_NGINX_CONNECT_URL", "http://keycloak:8080/keycloak"
            ),
            "KEYCLOAK_DASHBOARDS_CONNECT_URL": current.get(
                "KEYCLOAK_DASHBOARDS_CONNECT_URL", "http://keycloak:8080/keycloak"
            ),
            "KEYCLOAK_PROVISIONER_CLIENT_ID": "oculox-realm-provisioner",
            "KEYCLOAK_PROVISIONER_CLIENT_SECRET": provisioner_secret,
            "KEYCLOAK_RECOVERY_CLIENT_ID": "oculox-bootstrap-recovery",
            "KEYCLOAK_RECOVERY_CLIENT_SECRET": recovery_secret,
            # The provisioner is bootstrapped by Keycloak's official offline
            # service command. A human bootstrap administrator is not needed.
            "KC_BOOTSTRAP_ADMIN_USERNAME": "",
            "KC_BOOTSTRAP_ADMIN_PASSWORD": "",
            **initial_credentials,
        },
    )
    update_env(
        args.auth_common_env,
        {
            "ROLE_BASED_ACCESS": "true",
            "NGINX_REQUIRE_GROUP": "/oculox-users",
            "NGINX_REQUIRE_ROLE": "",
        },
    )
    write_credentials(args.credentials_file, initial_credentials)
    print(f"Keycloak realm provisioning prepared for {keycloak_url}")
    print(f"Bootstrap and operational credentials are stored in {args.credentials_file}")


def finalize(args: argparse.Namespace) -> None:
    current = read_env(args.keycloak_env)
    update_env(
        args.keycloak_env,
        {
            "KEYCLOAK_PROVISIONING_ENABLED": "false",
            "KC_BOOTSTRAP_ADMIN_USERNAME": "",
            "KC_BOOTSTRAP_ADMIN_PASSWORD": "",
            "KEYCLOAK_INITIAL_ADMIN_PASSWORD": "",
            "KEYCLOAK_USER_ADMIN_PASSWORD": "",
            "KEYCLOAK_USER_ANALYST_PASSWORD": "",
            "KEYCLOAK_USER_VIEWER_PASSWORD": "",
            "KEYCLOAK_USER_INCIDENT_RESPONSE_PASSWORD": "",
            "KEYCLOAK_USER_DENIED_PASSWORD": "",
            "KEYCLOAK_CONSOLE_ADMIN_PASSWORD": "",
            "KEYCLOAK_RECOVERY_CLIENT_ID": "",
            "KEYCLOAK_RECOVERY_CLIENT_SECRET": "",
        },
    )
    if current.get("KEYCLOAK_PROVISIONING_ENABLED") != "true":
        print("Keycloak provisioning was already finalized.")
    else:
        print("Keycloak provisioning credentials were removed from runtime configuration.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "finalize"))
    parser.add_argument("--admin-username", default="oculox-initial-admin")
    parser.add_argument("--keycloak-env", type=Path, default=KEYCLOAK_ENV)
    parser.add_argument("--auth-common-env", type=Path, default=AUTH_COMMON_ENV)
    parser.add_argument("--public-endpoint-env", type=Path, default=PUBLIC_ENDPOINT_ENV)
    parser.add_argument("--credentials-file", type=Path, default=DEFAULT_CREDENTIALS)
    args = parser.parse_args()
    if args.action == "prepare":
        prepare(args)
    else:
        finalize(args)


if __name__ == "__main__":
    main()
