#!/usr/bin/env python3

"""Validate the three-VM installation contract without contacting a server."""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[3]
LAUNCHER = PROJECT_DIR / "oculox"
MANAGER = PROJECT_DIR / "dev/scripts/opensearch-cluster/manage-cluster.sh"
COMPOSE = PROJECT_DIR / "dev/compose/opensearch-cluster/compose.yml"
OPERATIONAL_ROOTS = (
    PROJECT_DIR / "dev/compose/opensearch-cluster",
    PROJECT_DIR / "dev/config/opensearch-cluster",
    PROJECT_DIR / "dev/scripts/opensearch-cluster",
    PROJECT_DIR / "dev/tests/opensearch-cluster",
)


def main() -> None:
    launcher = LAUNCHER.read_text(encoding="utf-8")
    manager = MANAGER.read_text(encoding="utf-8")

    assert "./oculox install cluster --endpoint-ip" in launcher
    assert '"${1:-}" == cluster' in launcher
    assert "--opensearch-bundle" in launcher
    assert "create-client-bundle.py" in manager
    assert "client-bundles/$role" in manager
    assert "wait_for_cluster_green" in manager
    assert "down -v" not in manager
    assert "10.5.6.3" not in manager and "10.5.6.4" not in manager

    forbidden_name = re.compile(r"phase[-_ ]?\d", re.IGNORECASE)
    for root in OPERATIONAL_ROOTS:
        for path in root.rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts:
                assert not forbidden_name.search(path.name), path
                assert not forbidden_name.search(path.read_text(encoding="utf-8")), path

    with tempfile.TemporaryDirectory() as temporary:
        env_file = Path(temporary) / "cluster.env"
        env_file.write_text(
            "OPENSEARCH_IMAGE=ghcr.io/idaholab/malcolm/opensearch:26.07.1\n"
            "OCULOX_CLUSTER_PROFILE=production\n"
            "OPENSEARCH_CLUSTER_NAME=oculox-opensearch\n"
            "OPENSEARCH_DISCOVERY_SEED_HOSTS=opensearch-1:9300,opensearch-2:9300,opensearch-3:9300\n"
            "OPENSEARCH_INITIAL_CLUSTER_MANAGER_NODES=opensearch-1,opensearch-2,opensearch-3\n"
            "OPENSEARCH_HEAP_SIZE=3g\n"
            "OPENSEARCH_RESTART_POLICY=unless-stopped\n"
            "OPENSEARCH_CLUSTER_ENDPOINT=https://192.0.2.10:9200\n"
            "OPENSEARCH_ENDPOINT_BIND_IP=192.0.2.10\n"
            "OPENSEARCH_ENDPOINT_PORT=9443\n"
            "OPENSEARCH_MONITORING_PORT=8405\n"
            "OPENSEARCH_PROXY_IMAGE=haproxy:3.2.21-alpine\n"
            "OPENSEARCH_PROXY_UID=1234\n"
            "OPENSEARCH_PROXY_GID=1234\n",
            encoding="ascii",
        )
        result = subprocess.run(
            [
                "docker", "compose", "--env-file", str(env_file),
                "-f", str(COMPOSE), "config", "--format", "json",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    config = json.loads(result.stdout)
    proxy = config["services"]["opensearch-endpoint"]
    ports = {int(port["target"]): port for port in proxy["ports"]}
    assert ports[9200]["host_ip"] == "192.0.2.10"
    assert int(ports[9200]["published"]) == 9443
    assert ports[8404]["host_ip"] == "192.0.2.10"
    assert int(ports[8404]["published"]) == 8405
    assert proxy["user"] == "1234:1234"
    for node in ("opensearch-1", "opensearch-2", "opensearch-3"):
        opts = config["services"][node]["environment"]["OPENSEARCH_JAVA_OPTS"]
        assert "-Xms3g" in opts and "-Xmx3g" in opts

    print("fresh_vm_roles=cluster,core,hedgehog PASS")
    print("runtime_endpoint_and_heap=PARAMETERIZED PASS")
    print("destructive_volume_removal=ABSENT PASS")
    print("FRESH_INSTALLATION_CONTRACT_RESULT=PASS")


if __name__ == "__main__":
    main()
