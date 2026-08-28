#!/usr/bin/env python3

"""Import a remote OpenSearch client bundle into an Oculox deployment."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlparse


PROJECT_DIR = Path(__file__).resolve().parents[2]
CLIENT_DIR = PROJECT_DIR / "dev/generated/opensearch-clients"
CA_DESTINATION = PROJECT_DIR / "nginx/ca-trust/oculox-opensearch-ca.crt"
PRIMARY_CURLRC = PROJECT_DIR / ".opensearch.primary.curlrc"

ROLE_CLIENTS = {
    "principal": ("logstash", "arkime", "dashboards", "dashboards-helper", "api"),
    "hedgehog": ("arkime", "api"),
}
BUNDLE_ROLE = {"principal": "core", "hedgehog": "hedgehog"}


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


def update_env(path: Path, values: dict[str, str]) -> None:
    if not path.is_file():
        raise SystemExit(f"Configuration officielle absente : {path}")
    remaining = dict(values)
    result: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        key = line.split("=", 1)[0] if "=" in line else ""
        if key in remaining:
            result.append(f"{key}={remaining.pop(key)}")
        else:
            result.append(line)
    result.extend(f"{key}={value}" for key, value in remaining.items())
    path.write_text("\n".join(result) + "\n", encoding="utf-8")
    path.chmod(0o600)


def verify_checksums(bundle: Path) -> None:
    checksum_file = bundle / "SHA256SUMS"
    if not checksum_file.is_file():
        raise SystemExit("Bundle incomplet : SHA256SUMS absent")
    for line in checksum_file.read_text(encoding="ascii").splitlines():
        digest, filename = line.split(None, 1)
        filename = filename.strip().lstrip("*")
        if Path(filename).name != filename:
            raise SystemExit("Nom de fichier invalide dans SHA256SUMS")
        path = bundle / filename
        if not path.is_file():
            raise SystemExit(f"Bundle incomplet : {filename} absent")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != digest:
            raise SystemExit(f"Somme SHA-256 invalide : {filename}")


def validate_curlrc(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if not re.search(r'^\s*user\s*[:=]\s*"[^":]+:.+"\s*$', text, re.MULTILINE):
        raise SystemExit(f"Identifiants cURL invalides : {path.name}")
    if re.search(r'^\s*-?-?insecure\s*$', text, re.MULTILINE):
        raise SystemExit(f"Verification TLS desactivee dans {path.name}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--role", choices=tuple(ROLE_CLIENTS))
    args = parser.parse_args()

    bundle = args.bundle.resolve()
    if not bundle.is_dir():
        raise SystemExit(f"Bundle absent : {bundle}")
    verify_checksums(bundle)

    bundle_env = read_env(bundle / "bundle.env")
    endpoint = bundle_env.get("OPENSEARCH_CLUSTER_ENDPOINT", "")
    parsed = urlparse(endpoint)
    if parsed.scheme != "https" or not parsed.hostname:
        raise SystemExit("Endpoint HTTPS invalide dans bundle.env")

    deployment = read_env(PROJECT_DIR / "dev/generated/deployment.env")
    role = args.role or deployment.get("OCULOX_ROLE", "")
    if role not in ROLE_CLIENTS:
        raise SystemExit("Role Oculox absent ou invalide; utilisez --role")
    if bundle_env.get("OCULOX_OPENSEARCH_CLIENT_ROLE") != BUNDLE_ROLE[role]:
        raise SystemExit(f"Le bundle ne correspond pas au role {role}")

    ca_source = bundle / "oculox-opensearch-ca.crt"
    if not shutil.which("openssl"):
        raise SystemExit("openssl est requis pour valider la CA")
    ca_check = subprocess.run(
        ["openssl", "x509", "-in", str(ca_source), "-noout", "-checkend", "0"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if ca_check.returncode != 0:
        raise SystemExit(f"Certificat CA invalide ou expire : {ca_check.stderr.strip()}")

    for client in ROLE_CLIENTS[role]:
        path = bundle / f"{client}.curlrc"
        if not path.is_file():
            raise SystemExit(f"Bundle incomplet : {path.name} absent")
        validate_curlrc(path)

    CLIENT_DIR.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=".opensearch-clients.", dir=CLIENT_DIR.parent))
    os.chmod(work, 0o700)
    try:
        for client in ROLE_CLIENTS[role]:
            shutil.copyfile(bundle / f"{client}.curlrc", work / f"{client}.curlrc")
            os.chmod(work / f"{client}.curlrc", 0o600)
        if CLIENT_DIR.exists():
            shutil.rmtree(CLIENT_DIR)
        work.rename(CLIENT_DIR)
    except Exception:
        shutil.rmtree(work, ignore_errors=True)
        raise

    CA_DESTINATION.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ca_source, CA_DESTINATION)
    os.chmod(CA_DESTINATION, 0o644)

    shutil.copyfile(CLIENT_DIR / "api.curlrc", PRIMARY_CURLRC)
    os.chmod(PRIMARY_CURLRC, 0o600)

    update_env(
        PROJECT_DIR / "config/opensearch.env",
        {
            "OPENSEARCH_PRIMARY": "opensearch-remote",
            "OPENSEARCH_URL": endpoint.rstrip("/"),
            "OPENSEARCH_SSL_CERTIFICATE_VERIFICATION": "true",
        },
    )

    marker = CLIENT_DIR / "deployment.env"
    marker.write_text(
        f"OCULOX_ROLE={role}\nOPENSEARCH_CLUSTER_ENDPOINT={endpoint.rstrip('/')}\n",
        encoding="utf-8",
    )
    os.chmod(marker, 0o600)

    print("Configuration OpenSearch distante importée.")
    print(f"Role : {role}; endpoint : {endpoint.rstrip('/')}")
    print("Verification TLS : activee; CA : nginx/ca-trust/oculox-opensearch-ca.crt")
    print(f"Identites de service installees : {len(ROLE_CLIENTS[role])}")


if __name__ == "__main__":
    main()
