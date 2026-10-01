#!/usr/bin/env python3
"""Validate and rotate EJBCA Web trust without changing OpenSearch identities."""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

import yaml

ROOT = Path(__file__).resolve().parents[3]
GENERATED = ROOT / "dev/generated/opensearch-cluster"
AGENT = ROOT / "dev/generated/pki/remote-agent"
TRUST = GENERATED / "idp-trust/keycloak-ca.crt"
CONTAINER_TRUST = "/usr/share/opensearch/config/idp-trust/keycloak-ca.crt"
NODES = ("opensearch-1", "opensearch-2", "opensearch-3")


def module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def run(*args: str, data: str | None = None, timeout: int = 60) -> str:
    result = subprocess.run(args, input=data, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "Command failed: " + args[0])
    return result.stdout


def container(node: str) -> str:
    return f"oculox-opensearch-cluster-{node}-1"


def security(category: str) -> dict:
    info = json.loads(run("docker", "inspect", container(NODES[0])))[0]
    ip = info["NetworkSettings"]["Networks"]["oculox-opensearch-transport"]["IPAddress"]
    admin = GENERATED / "pki/admin"
    return json.loads(run("curl", "--noproxy", "*", "--silent", "--show-error", "--fail",
        "--max-time", "20", "--resolve", f"opensearch-1:9200:{ip}",
        "--cacert", str(admin / "ca.crt"), "--cert", str(admin / "admin.crt"),
        "--key", str(admin / "admin.key"),
        "https://opensearch-1:9200/_plugins/_security/api/" + category))


def oidc_settings(config: dict) -> dict:
    domains = config["config"]["dynamic"]["authc"]
    found = [domain["http_authenticator"]["config"] for domain in domains.values()
             if domain.get("http_enabled") and domain.get("http_authenticator", {}).get("type") == "openid"]
    if len(found) != 1:
        raise RuntimeError("Exactly one active OpenID domain required; run configure-oidc after Core startup")
    settings = found[0]
    tls = settings.get("openid_connect_idp", {})
    if tls.get("enable_ssl") is not True or tls.get("verify_hostnames") is not True:
        raise RuntimeError("OIDC must verify TLS and hostnames")
    if tls.get("pemtrustedcas_filepath") != CONTAINER_TRUST:
        raise RuntimeError("Unexpected OIDC trust path; explicit configuration required")
    if not settings.get("roles_key") or not settings.get("required_audience"):
        raise RuntimeError("OIDC roles claim and required audience must be configured")
    return settings


def https_url(value: str) -> str:
    parsed = urlparse(value)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.fragment or parsed.query):
        raise RuntimeError("OIDC endpoints must be HTTPS URLs without credentials, query or fragment")
    return value


def check_metadata(discovery: dict, url: str) -> str:
    issuer = https_url(discovery.get("issuer", ""))
    expected = url.removesuffix("/.well-known/openid-configuration")
    if issuer != expected:
        raise RuntimeError("Discovery issuer does not match configured realm URL")
    jwks = https_url(discovery.get("jwks_uri", ""))
    if urlparse(jwks).netloc != urlparse(issuer).netloc:
        raise RuntimeError("Cross-host JWKS URL requires explicit review")
    return jwks


def probe(url: str, ca: Path | None = None) -> None:
    https_url(url)
    for node in NODES:
        prefix = ["docker", "exec"] + (["-i"] if ca else []) + [container(node), "curl",
            "--noproxy", "*", "--silent", "--show-error", "--fail", "--max-time", "20",
            "--cacert", "/dev/stdin" if ca else CONTAINER_TRUST]
        pem = ca.read_text(encoding="ascii") if ca else None
        discovery = json.loads(run(*prefix, url, data=pem))
        jwks = check_metadata(discovery, url)
        keys = json.loads(run(*prefix, jwks, data=pem))
        if not any(key.get("kid") and key.get("kty") in ("RSA", "EC") for key in keys.get("keys", [])):
            raise RuntimeError("No usable signing key in Keycloak JWKS")
        print(f"PASS {node}: HTTPS discovery, issuer and JWKS", flush=True)


def validate_ca(ca: Path) -> None:
    # Reuse the same root pin validation as remote enrollment, without private keys.
    spec = importlib.util.spec_from_file_location("remote_enrollment", ROOT / "dev/scripts/ejbca/remote-enrollment.py")
    remote = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(remote)
    remote.verify_pinned_bundle(AGENT, remote.fingerprint(AGENT / "root.crt"))
    pem = ca.read_text(encoding="ascii")
    if "PRIVATE KEY" in pem or pem != (AGENT / "api-ca.crt").read_text(encoding="ascii"):
        raise RuntimeError("Use the Web CA bundle from the root-pinned enrollment agent; refresh the agent for CA rotation")


def snapshot(label: str, config: dict, mappings: dict) -> Path:
    parent = GENERATED / "oidc-backups"
    parent.mkdir(mode=0o700, exist_ok=True)
    parent.chmod(0o700)
    folder = parent / (dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-" + label)
    folder.mkdir(mode=0o700)
    for name, value in (("securityconfig.json", config), ("rolesmapping.json", mappings)):
        path = folder / name
        path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
        path.chmod(0o600)
    if TRUST.exists():
        module("migration", "migrate-ejbca.py").atomic_copy(TRUST, folder / "keycloak-ca.crt", 0o600)
    print(f"Backup: {folder}", flush=True)
    return folder


def reload_nodes(migration) -> None:
    for node in NODES:
        # Restart keeps container IPs stable and reloads the directory-mounted CA.
        migration.compose("restart", node)
        migration.health()
        print(f"PASS {node}: restarted; cluster green with three nodes", flush=True)


def apply_trust(ca: Path, url: str) -> None:
    validate_ca(ca)
    probe(url, ca)
    before, mappings = security("securityconfig"), security("rolesmapping")
    migration = module("migration", "migrate-ejbca.py")
    migration.health()
    if TRUST.exists() and TRUST.read_bytes() == ca.read_bytes():
        probe(url)
        print("OIDC trust already current; no restart")
        return
    backup = snapshot("trust", before, mappings)
    migration.atomic_copy(ca, TRUST, 0o644)
    try:
        reload_nodes(migration)
        probe(url)
        if security("securityconfig") != before or security("rolesmapping") != mappings:
            raise RuntimeError("Security configuration changed concurrently; inspect the backup")
    except Exception:
        if (backup / "keycloak-ca.crt").exists():
            migration.atomic_copy(backup / "keycloak-ca.crt", TRUST, 0o644)
        else:
            TRUST.unlink(missing_ok=True)
        reload_nodes(migration)
        raise
    print("OIDC_TRUST_RESULT=PASS; active roles and authentication configuration unchanged")


def write_security(folder: Path, config: dict, mappings: dict) -> None:
    meta = {"type": "config", "config_version": 2}
    for name, value in (("config.yml", {"_meta": meta, **config}),
                        ("roles_mapping.yml", {"_meta": {**meta, "type": "rolesmapping"}, **mappings})):
        path = folder / name
        path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
        path.chmod(0o600)


def configure(args) -> None:
    renderer = module("oidc_renderer", "render-oidc-security-config.py")
    url = renderer.realm_discovery_url(args.keycloak_auth_url, args.realm)
    apply_trust(args.keycloak_ca, url)
    config, mappings = security("securityconfig"), security("rolesmapping")
    backup = snapshot("configure", config, mappings)
    write_security(backup, config, mappings)
    # Start from actual live settings, never an obsolete installation baseline.
    updated = renderer.render_config(json.loads(json.dumps(config)), url, args.client_id,
        "roles", "preferred_username", CONTAINER_TRUST)
    mapped = renderer.render_mappings(json.loads(json.dumps(mappings)))
    candidate = backup / "candidate"
    candidate.mkdir(mode=0o700)
    write_security(candidate, updated, mapped)
    migration = module("migration", "migrate-ejbca.py")
    def update(folder):
        run("bash", str(Path(__file__).with_name("update-security-config.sh")),
            "--admin-dir", str(GENERATED / "pki/admin"), "--security-dir", str(folder),
            "--image", migration.env_value("OPENSEARCH_IMAGE", migration.ENV), timeout=240)
    try:
        update(candidate)
        migration.health()
        verify()
        active_mappings = security("rolesmapping")
        for role, mapping in mappings.items():
            for key in ("users", "hosts", "backend_roles", "and_backend_roles"):
                if not set(mapping.get(key, [])).issubset(set(active_mappings.get(role, {}).get(key, []))):
                    raise RuntimeError("Existing role mapping was not preserved")
    except Exception:
        update(backup)
        raise
    print("OIDC_CONFIGURE_RESULT=PASS; existing role mappings preserved")


def verify(if_configured: bool = False) -> None:
    config = security("securityconfig")
    if if_configured and not any(domain.get("http_enabled") and
            domain.get("http_authenticator", {}).get("type") == "openid"
            for domain in config["config"]["dynamic"]["authc"].values()):
        print("OIDC not configured yet; configure-oidc required after Core startup")
        return
    settings = oidc_settings(config)
    validate_ca(TRUST)
    probe(settings["openid_connect_url"])
    module("migration", "migrate-ejbca.py").health()
    print("OIDC_VERIFY_RESULT=PASS; TLS/JWKS checked, interactive login still requires browser verification")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("verify", "trust", "configure"))
    parser.add_argument("--keycloak-ca", type=Path, default=AGENT / "api-ca.crt")
    parser.add_argument("--keycloak-auth-url")
    parser.add_argument("--realm", default="oculox")
    parser.add_argument("--client-id", default="oculox-dashboards")
    parser.add_argument("--if-configured", action="store_true")
    args = parser.parse_args()
    GENERATED.mkdir(parents=True, exist_ok=True)
    with (GENERATED / ".pki-operation.lock").open("a") as lock:
        os.chmod(lock.name, 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.action == "verify":
            verify(args.if_configured)
        elif args.action == "trust":
            apply_trust(args.keycloak_ca, oidc_settings(security("securityconfig"))["openid_connect_url"])
        else:
            if not args.keycloak_auth_url:
                raise RuntimeError("--keycloak-auth-url required (public Core URL ending in /keycloak)")
            configure(args)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as error:
        print(f"FAIL OIDC: {error}", file=sys.stderr)
        sys.exit(1)
