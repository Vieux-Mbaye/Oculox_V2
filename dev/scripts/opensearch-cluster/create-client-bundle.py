#!/usr/bin/env python3

"""Build a transportable OpenSearch client bundle without printing secrets."""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import tempfile
from pathlib import Path
from urllib.parse import urlparse


PROJECT_DIR = Path(__file__).resolve().parents[3]
DEFAULT_CA = PROJECT_DIR / "dev/generated/opensearch-cluster/pki/client-trust/oculox-opensearch-ca.crt"
DEFAULT_ACCOUNTS = PROJECT_DIR / "dev/generated/opensearch-cluster/security/accounts.env"

ACCOUNT_MAP = {
    "core": {
        "logstash": ("oculox_logstash", "OCULOX_LOGSTASH_PASSWORD"),
        "arkime": ("oculox_arkime", "OCULOX_ARKIME_PASSWORD"),
        "dashboards": ("oculox_dashboards", "OCULOX_DASHBOARDS_PASSWORD"),
        "dashboards-helper": ("oculox_dashboards_helper", "OCULOX_DASHBOARDS_HELPER_PASSWORD"),
        "api": ("oculox_api", "OCULOX_API_PASSWORD"),
    },
    "hedgehog": {
        "arkime": ("oculox_arkime", "OCULOX_ARKIME_PASSWORD"),
        "api": ("oculox_api", "OCULOX_API_PASSWORD"),
    },
}


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


def escape_curl(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def validate_endpoint(endpoint: str) -> str:
    parsed = urlparse(endpoint)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise SystemExit("L'endpoint doit etre une URL HTTPS sans identifiants")
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise SystemExit("L'endpoint ne doit contenir ni chemin, ni requete, ni fragment")
    return endpoint.rstrip("/")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", choices=tuple(ACCOUNT_MAP), required=True)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--ca", type=Path, default=DEFAULT_CA)
    parser.add_argument("--accounts", type=Path, default=DEFAULT_ACCOUNTS)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    endpoint = validate_endpoint(args.endpoint)
    for path, label in ((args.ca, "CA"), (args.accounts, "comptes Security")):
        if not path.is_file():
            raise SystemExit(f"Fichier {label} absent : {path}")

    accounts = read_env(args.accounts)
    missing = [key for _, key in ACCOUNT_MAP[args.role].values() if not accounts.get(key)]
    if missing:
        raise SystemExit(f"Mots de passe absents dans accounts.env : {', '.join(missing)}")

    output = args.output.resolve()
    if output.exists():
        raise SystemExit(f"La sortie existe deja : {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=".opensearch-client-bundle.", dir=output.parent))
    os.chmod(work, 0o700)

    try:
        shutil.copyfile(args.ca, work / "oculox-opensearch-ca.crt")
        os.chmod(work / "oculox-opensearch-ca.crt", 0o644)
        (work / "bundle.env").write_text(
            f"OCULOX_OPENSEARCH_CLIENT_ROLE={args.role}\n"
            f"OPENSEARCH_CLUSTER_ENDPOINT={endpoint}\n",
            encoding="utf-8",
        )
        os.chmod(work / "bundle.env", 0o600)

        for client, (username, password_key) in ACCOUNT_MAP[args.role].items():
            content = f'user = "{escape_curl(username)}:{escape_curl(accounts[password_key])}"\n'
            path = work / f"{client}.curlrc"
            path.write_text(content, encoding="utf-8")
            os.chmod(path, 0o600)

        files = sorted(path for path in work.iterdir() if path.name != "SHA256SUMS")
        checksums = "".join(f"{sha256(path)}  {path.name}\n" for path in files)
        (work / "SHA256SUMS").write_text(checksums, encoding="ascii")
        os.chmod(work / "SHA256SUMS", 0o600)
        work.rename(output)
    except Exception:
        shutil.rmtree(work, ignore_errors=True)
        raise

    print(f"Bundle client OpenSearch genere : {output}")
    print(f"Role : {args.role}; endpoint : {endpoint}; comptes : {len(ACCOUNT_MAP[args.role])}")
    print("Le bundle contient des secrets et doit rester en mode 0700.")


if __name__ == "__main__":
    main()
