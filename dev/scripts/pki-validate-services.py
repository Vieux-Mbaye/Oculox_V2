#!/usr/bin/env python3
"""Functional PKI-adjacent validation commands for Oculox services."""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[2]


@dataclass
class Check:
    scope: str
    status: str
    detail: str


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=PROJECT_DIR, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)


def curl_check(scope: str, url: str, expected: tuple[str, ...] = ("200", "301", "302", "401", "403"), *, ca: Path | None = None, credentials: Path | None = None) -> Check:
    command = ["curl", "--silent", "--show-error", "--max-time", "15"]
    command.extend(["--cacert", str(ca or PROJECT_DIR / "nginx/ca-trust/oculox-web-ca.crt")])
    if credentials is not None:
        command.extend(["--config", str(credentials)])
    result = run([*command, "-o", "/dev/null", "-w", "%{http_code}", url])
    if result.returncode != 0:
        return Check(scope, "FAIL", f"{url} inaccessible ou TLS invalide: {result.stderr.strip() or result.stdout.strip()}")
    code = result.stdout.strip()
    if code in expected:
        return Check(scope, "OK", f"{url} répond HTTP {code}")
    return Check(scope, "FAIL", f"{url} répond HTTP {code}, attendu {','.join(expected)}")


def docker_running(name: str) -> bool | None:
    result = run(["docker", "ps", "--format", "{{.Names}}"])
    if result.returncode != 0:
        return None
    candidates = {line.strip() for line in result.stdout.splitlines()}
    return any(candidate == name or candidate.endswith(f"-{name}-1") or candidate.endswith(f"_{name}_1") for candidate in candidates)


def pki_audit_required() -> Check:
    result = run(["./oculox", "pki", "status"])
    if result.returncode == 0:
        return Check("pki", "OK", "manifest PKI actif valide ou avec avertissements non bloquants")
    return Check("pki", "FAIL", result.stderr.strip() or result.stdout.strip() or "audit PKI en échec")


def ejbca_required() -> list[Check]:
    if not (PROJECT_DIR / "dev/ejbca/generated/ejbca.env").is_file():
        return []
    result = run(["./oculox", "pki-ca", "validate"])
    if result.returncode == 0:
        return [Check("ejbca", "OK", "autorité centrale et base disponibles")]
    return [Check("ejbca", "FAIL", result.stderr.strip() or result.stdout.strip() or "autorité centrale indisponible")]


def public_url(path: str = "/") -> str:
    config = PROJECT_DIR / "dev/generated/public-endpoint.env"
    if config.is_file():
        for line in config.read_text().splitlines():
            if line.startswith("OCULOX_PUBLIC_URL="):
                return line.split("=", 1)[1].strip().strip('\"').strip("'").rstrip("/") + path
    return "https://localhost" + path


def validate_web() -> list[Check]:
    return [
        pki_audit_required(),
        curl_check("web", public_url()),
    ]


def validate_keycloak() -> list[Check]:
    checks = [curl_check("keycloak", public_url("/keycloak/realms/oculox/.well-known/openid-configuration"))]
    running = docker_running("keycloak")
    if running is None:
        checks.append(Check("keycloak", "WARN", "Docker inaccessible pour vérifier le conteneur Keycloak"))
    elif not running:
        checks.append(Check("keycloak", "WARN", "conteneur Keycloak non détecté par nom standard"))
    return checks


def validate_dashboards() -> list[Check]:
    return [curl_check("dashboards", public_url("/dashboards/"))]


def validate_opensearch() -> list[Check]:
    checks = [pki_audit_required()]
    config = PROJECT_DIR / "config/opensearch.env"
    endpoint = ""
    if config.is_file():
        for line in config.read_text().splitlines():
            if line.startswith("OPENSEARCH_URL="):
                endpoint = line.split("=", 1)[1].strip().strip('\"').strip("'")
    if endpoint:
        credentials = PROJECT_DIR / "dev/generated/opensearch-clients/api.curlrc"
        checks.append(curl_check("opensearch", endpoint + "/_cluster/health", ("200",) if credentials.is_file() else ("200", "401"), ca=PROJECT_DIR / "nginx/ca-trust/oculox-opensearch-ca.crt", credentials=credentials if credentials.is_file() else None))
        return checks
    running = docker_running("opensearch")
    if running:
        checks.append(curl_check("opensearch", "https://127.0.0.1:9200/", ("200", "401", "403")))
    elif running is None:
        checks.append(Check("opensearch", "WARN", "Docker inaccessible; endpoint OpenSearch non vérifié"))
    else:
        checks.append(Check("opensearch", "WARN", "endpoint local 9200 non détecté; vérifiez le cluster distant avec les commandes cluster dédiées"))
    return checks


def validate_ingestion() -> list[Check]:
    checks = [pki_audit_required()]
    for name in ("filebeat", "logstash", "logstash-2"):
        running = docker_running(name)
        if running is None:
            checks.append(Check("ingestion", "WARN", f"conteneur {name}: Docker inaccessible"))
        else:
            checks.append(Check("ingestion", "OK" if running else "FAIL", f"conteneur {name}: {'actif' if running else 'non détecté'}"))
    result = run(["docker", "ps", "--format", "{{.Names}} {{.Status}}"])
    for line in result.stdout.splitlines():
        if any(f"-{name}-1 " in line for name in ("filebeat", "logstash", "logstash-2")) and "(unhealthy)" in line:
            checks.append(Check("ingestion", "FAIL", f"controle de sante en echec: {line.split()[0]}"))
    return checks


def print_checks(checks: list[Check]) -> int:
    failed = False
    for check in checks:
        print(f"{check.status:<5} {check.scope:<12} {check.detail}")
        failed = failed or check.status == "FAIL"
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Validation fonctionnelle Oculox par service")
    parser.add_argument("scope", choices=("web", "keycloak", "dashboards", "opensearch", "ingestion", "all"))
    args = parser.parse_args()

    mapping = {
        "web": validate_web,
        "keycloak": validate_keycloak,
        "dashboards": validate_dashboards,
        "opensearch": validate_opensearch,
        "ingestion": validate_ingestion,
    }
    checks: list[Check] = []
    scopes = mapping.keys() if args.scope == "all" else (args.scope,)
    for scope in scopes:
        checks.extend(mapping[scope]())
    if args.scope == "all":
        checks.extend(ejbca_required())
    return print_checks(checks)


if __name__ == "__main__":
    sys.exit(main())
