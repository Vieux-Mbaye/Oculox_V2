#!/usr/bin/env python3

import json
import os
import re
import subprocess
import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[3]
COMPOSE_FILE = PROJECT_DIR / "dev/compose/opensearch-cluster/compose.yml"
ENV_FILE = Path(os.environ.get(
    "OPENSEARCH_CLUSTER_ENV_FILE",
    PROJECT_DIR / "dev/config/opensearch-cluster/cluster.env.example",
))
TEMPLATE = PROJECT_DIR / "dev/config/opensearch-cluster/haproxy.cfg.template"
RENDERED = PROJECT_DIR / "dev/generated/opensearch-cluster/endpoint-proxy"
EXPECTED_NODES = {"opensearch-1", "opensearch-2", "opensearch-3"}


def fail(message: str) -> None:
    print(f"ENDPOINT_PROXY_STATIC_RESULT=FAIL: {message}", file=sys.stderr)
    raise SystemExit(1)


def compose_config() -> dict:
    result = subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            str(ENV_FILE),
            "-f",
            str(COMPOSE_FILE),
            "config",
            "--format",
            "json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        fail(result.stderr.strip() or "docker compose config failed")
    return json.loads(result.stdout)


def main() -> None:
    config = compose_config()
    services = config.get("services", {})
    proxy = services.get("opensearch-endpoint")
    if not proxy:
        fail("opensearch-endpoint service is missing")
    if proxy.get("image") != "haproxy:3.2.21-alpine":
        fail("HAProxy image must be pinned")
    if proxy.get("read_only") is not True:
        fail("proxy root filesystem must be read-only")
    expected_uid = "1000"
    expected_gid = "1000"
    expected_ip = "192.0.2.10"
    expected_port = 9200
    expected_monitoring_port = 8404
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        key, _, value = line.partition("=")
        if key == "OPENSEARCH_PROXY_UID":
            expected_uid = value
        elif key == "OPENSEARCH_PROXY_GID":
            expected_gid = value
        elif key == "OPENSEARCH_ENDPOINT_BIND_IP":
            expected_ip = value
        elif key == "OPENSEARCH_ENDPOINT_PORT":
            expected_port = int(value)
        elif key == "OPENSEARCH_MONITORING_PORT":
            expected_monitoring_port = int(value)
    if str(proxy.get("user")) != f"{expected_uid}:{expected_gid}":
        fail("proxy must use the owner of its mode-0600 generated secrets")
    if set(proxy.get("depends_on", {})) != EXPECTED_NODES:
        fail("proxy must know all three OpenSearch nodes")
    if set(proxy.get("networks", {})) != {"cluster-transport", "endpoint-ingress"}:
        fail("proxy must separate private transport from host ingress")
    for node in EXPECTED_NODES:
        if "endpoint-ingress" in services[node].get("networks", {}):
            fail(f"{node} must not join the ingress network")

    published = proxy.get("ports", [])
    if len(published) != 2:
        fail("proxy must publish the API and monitoring ports")
    publications = {
        int(port.get("target", 0)): (str(port.get("host_ip")), int(port.get("published", 0)))
        for port in published
    }
    if publications.get(9200) != (expected_ip, expected_port):
        fail(f"unexpected stable endpoint publication: {published}")
    if publications.get(8404) != (expected_ip, expected_monitoring_port):
        fail(f"unexpected monitoring endpoint publication: {published}")

    mounts = {mount.get("target"): mount for mount in proxy.get("volumes", [])}
    for target in (
        "/usr/local/etc/haproxy/haproxy.cfg",
        "/usr/local/etc/haproxy/certs/endpoint.pem",
        "/usr/local/etc/haproxy/certs/backend-ca.crt",
    ):
        if target not in mounts or mounts[target].get("read_only") is not True:
            fail(f"missing read-only proxy mount: {target}")

    template = TEMPLATE.read_text(encoding="utf-8")
    if template.count("server opensearch-") != 3:
        fail("HAProxy backend must contain exactly three node servers")
    for node in sorted(EXPECTED_NODES):
        pattern = rf"server {node} {node}:9200 .*check-sni {node}.*ssl verify required.*sni str\({node}\)"
        if not re.search(pattern, template):
            fail(f"active TLS verification is incomplete for {node}")
    for required in (
        "monitor-uri /healthz",
        "nbsrv(opensearch_nodes) lt 1",
        "balance roundrobin",
        "http-check expect status 200",
        "fall 3 rise 2",
        "ssl-min-ver TLSv1.2",
    ):
        if required not in template:
            fail(f"missing HAProxy requirement: {required}")
    if "%r" in template or "capture request header Authorization" in template:
        fail("proxy logs must not contain request paths or authorization headers")
    if "monitor /healthz" in template or "monitor fail -uriif" in template:
        fail("legacy invalid HAProxy monitor syntax is present")
    if "OCULOX_API_PASSWORD" in template or "oculox_api:" in template:
        fail("the versioned template must not contain credentials")

    rendered_config = RENDERED / "haproxy.cfg"
    if rendered_config.exists():
        rendered_text = rendered_config.read_text(encoding="utf-8")
        if "__HEALTH_AUTHORIZATION__" in rendered_text:
            fail("rendered HAProxy configuration still contains its placeholder")
        for path in (rendered_config, RENDERED / "endpoint.pem", RENDERED / "backend-ca.crt"):
            if path.stat().st_mode & 0o077:
                fail(f"generated file permissions are too broad: {path}")

    git_root = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=PROJECT_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if git_root.returncode == 0:
        tracked = subprocess.run(
            ["git", "ls-files", "dev/generated/opensearch-cluster/endpoint-proxy"],
            cwd=PROJECT_DIR,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        if tracked.strip():
            fail("generated endpoint secrets must not be tracked by Git")

    print(f"stable_endpoint={expected_ip}:{expected_port} PASS")
    print(f"monitoring_endpoint={expected_ip}:{expected_monitoring_port} PASS")
    print("backend_nodes=3/3 PASS")
    print("active_health_checks=PASS")
    print("backend_tls_verification=PASS")
    print("limited_logs=PASS")
    print(
        "generated_proxy_secrets_git_tracking=NONE PASS"
        if git_root.returncode == 0
        else "generated_proxy_secrets_git_tracking=NOT_APPLICABLE_DEPLOYED_TREE PASS"
    )
    print("ENDPOINT_PROXY_STATIC_RESULT=PASS")


if __name__ == "__main__":
    main()
