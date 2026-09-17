#!/usr/bin/env python3

"""Validate every Oculox client contract with a remote OpenSearch cluster."""

from __future__ import annotations

import argparse
import base64
import json
import os
import ssl
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


PROJECT_DIR = Path(__file__).resolve().parents[3]
STATE_FILE = PROJECT_DIR / "dev/generated/deployment.env"
CLIENT_DIR = PROJECT_DIR / "dev/generated/opensearch-clients"
CA_FILE = PROJECT_DIR / "nginx/ca-trust/oculox-opensearch-ca.crt"
FILEBEAT_DIR = PROJECT_DIR / "dev/generated/filebeat"
RESULT_ROOT = PROJECT_DIR / "dev/generated/validation/client-connectivity"
EXPECTED = {
    "principal": {
        "logstash": "logstash",
        "logstash-2": "logstash",
        "arkime": "arkime",
        "arkime-live": "arkime",
        "dashboards": "dashboards",
        "dashboards-helper": "dashboards-helper",
        "pcap-monitor": "api",
        "api": "api",
    },
    "hedgehog": {
        "arkime": "arkime",
        "arkime-live": "arkime",
        "pcap-monitor": "api",
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key] = value.strip().strip('"').strip("'")
    return values


def curlrc_user(path: Path) -> tuple[str, str]:
    for raw in path.read_text(encoding="utf-8").splitlines():
        if raw.strip().startswith("user") and "=" in raw:
            value = raw.split("=", 1)[1].strip().strip('"')
            return tuple(value.split(":", 1))  # type: ignore[return-value]
    raise RuntimeError(f"identifiants absents de {path}")


def run(*command: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, check=False)


def container_for(service: str) -> str | None:
    result = run(
        "docker",
        "ps",
        "-a",
        "--filter",
        "label=com.docker.compose.project=oculox",
        "--filter",
        f"label=com.docker.compose.service={service}",
        "--format",
        "{{.Names}}",
    )
    names = [line for line in result.stdout.splitlines() if line]
    return names[0] if len(names) == 1 else None


def request(
    endpoint: str,
    credential: Path,
    path: str,
    method: str = "GET",
    body: dict[str, Any] | None = None,
) -> tuple[int, Any]:
    username, password = curlrc_user(credential)
    headers = {
        "Authorization": "Basic " + base64.b64encode(
            f"{username}:{password}".encode()
        ).decode(),
        "Content-Type": "application/json",
    }
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(endpoint + path, data=data, headers=headers, method=method)
    context = ssl.create_default_context(cafile=str(CA_FILE))
    try:
        with urllib.request.urlopen(req, context=context, timeout=15) as response:
            payload = response.read().decode()
            return response.status, json.loads(payload) if payload else {}
    except urllib.error.HTTPError as error:
        payload = error.read().decode()
        try:
            parsed: Any = json.loads(payload)
        except json.JSONDecodeError:
            parsed = payload
        return error.code, parsed


def main() -> int:
    args = parse_args()
    checks: list[dict[str, Any]] = []

    def check(name: str, passed: bool, detail: str) -> None:
        checks.append({"name": name, "status": "PASS" if passed else "FAIL", "detail": detail})
        print(f"{'PASS' if passed else 'FAIL'} {name}: {detail}")

    if not STATE_FILE.is_file():
        raise SystemExit("déploiement absent: exécutez d'abord ./oculox install")
    state = env_file(STATE_FILE)
    role = state.get("OCULOX_ROLE", "")
    deployment = env_file(CLIENT_DIR / "deployment.env")
    endpoint = deployment.get("OPENSEARCH_CLUSTER_ENDPOINT", "")
    check("deployment_role", role in EXPECTED, role or "absent")
    check("remote_endpoint", endpoint.startswith("https://"), endpoint or "absent")
    check("trusted_ca", CA_FILE.is_file(), str(CA_FILE))

    expected = EXPECTED.get(role, {})
    for service, identity in expected.items():
        credential = CLIENT_DIR / f"{identity}.curlrc"
        container = container_for(service)
        check(f"{service}_container", container is not None, container or "absent ou ambigu")
        if not container:
            continue
        inspect = run("docker", "inspect", container)
        try:
            info = json.loads(inspect.stdout)[0]
        except (json.JSONDecodeError, IndexError):
            check(f"{service}_inspect", False, inspect.stderr.strip() or "inspect illisible")
            continue
        state_info = info.get("State", {})
        health = state_info.get("Health", {}).get("Status", "not-defined")
        check(
            f"{service}_runtime",
            bool(state_info.get("Running")) and health in ("healthy", "not-defined"),
            f"running={state_info.get('Running')} health={health}",
        )
        sources = {mount.get("Source") for mount in info.get("Mounts", [])}
        check(f"{service}_credential_mount", str(credential.resolve()) in sources, identity)
        if credential.is_file() and endpoint:
            code, auth = request(endpoint, credential, "/_plugins/_security/authinfo")
            actual_user = auth.get("user_name") if isinstance(auth, dict) else None
            expected_user = curlrc_user(credential)[0]
            check(f"{service}_authentication", code == 200 and actual_user == expected_user,
                  f"HTTP {code}, user={actual_user}")

    for service in ("logstash", "logstash-2") if role == "principal" else ():
        container = container_for(service)
        if container:
            api = run("docker", "exec", container, "curl", "-fsS",
                      "http://127.0.0.1:9600/_node/stats/pipelines")
            try:
                pipelines = json.loads(api.stdout).get("pipelines", {})
            except json.JSONDecodeError:
                pipelines = {}
            check(f"{service}_pipelines", api.returncode == 0 and bool(pipelines),
                  f"{len(pipelines)} pipeline(s)")

    filebeat_files = sorted(FILEBEAT_DIR.glob("*.yml"))
    check("filebeat_configs", bool(filebeat_files), f"{len(filebeat_files)} fichier(s)")
    expected_hosts = (["logstash:5044", "logstash-2:5044"] if role == "principal" else [
        f"{state.get('OCULOX_PRINCIPAL_HOST')}:5044",
        f"{state.get('OCULOX_PRINCIPAL_HOST')}:5045",
    ])
    for path in filebeat_files:
        config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        output = config.get("output.logstash", {})
        hosts = output.get("hosts", [])
        no_direct = "output.elasticsearch" not in config and "output.opensearch" not in config
        mtls = (output.get("ssl.enabled") is True
                and output.get("ssl.verification_mode") == "full"
                and bool(output.get("ssl.certificate_authorities"))
                and bool(output.get("ssl.certificate")) and bool(output.get("ssl.key")))
        check(f"filebeat_{path.stem}", output.get("loadbalance") is True
              and hosts == expected_hosts and mtls and no_direct,
              f"hosts={hosts}, loadbalance={output.get('loadbalance')}, direct_opensearch={not no_direct}")

    nginx = container_for("nginx-proxy") if role == "principal" else None
    if nginx:
        route = run("curl", "-ksS", "-o", "/dev/null", "-w", "%{http_code}",
                    "https://127.0.0.1/")
        check("nginx_proxy_route", route.stdout.strip() in {"200", "301", "302", "401", "403"},
              f"HTTP {route.stdout.strip() or 'aucun'}")

    if role == "principal" and endpoint:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        arkime_index = f"arkime_client_validation_{stamp}"
        credential = CLIENT_DIR / "arkime.curlrc"
        create, _ = request(endpoint, credential, f"/{arkime_index}", "PUT",
                            {"settings": {"number_of_shards": 1, "number_of_replicas": 1}})
        write, _ = request(endpoint, credential, f"/{arkime_index}/_doc/1?refresh=wait_for", "PUT",
                           {"validation": "arkime-direct-opensearch"})
        read, payload = request(endpoint, credential, f"/{arkime_index}/_count")
        delete, _ = request(endpoint, credential, f"/{arkime_index}", "DELETE")
        check("arkime_direct_write", create == 200 and write in {200, 201} and read == 200
              and payload.get("count") == 1 and delete == 200,
              f"create={create} write={write} read={read} delete={delete}")

    failed = [item for item in checks if item["status"] == "FAIL"]
    output = args.output or RESULT_ROOT / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") / "report.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {"schema": 1, "created_at": datetime.now(timezone.utc).isoformat(),
              "role": role, "endpoint": endpoint, "result": "FAIL" if failed else "PASS",
              "checks": checks}
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    os.chmod(output, 0o600)
    print(f"REPORT {output}")
    print(f"CLIENT_CONNECTIVITY_RESULT={report['result']}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
