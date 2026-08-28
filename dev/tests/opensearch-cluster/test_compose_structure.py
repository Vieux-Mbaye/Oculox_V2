#!/usr/bin/env python3

import json
import os
import subprocess
import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[3]
COMPOSE_FILE = PROJECT_DIR / "dev/compose/opensearch-cluster/compose.yml"
ENV_FILE = Path(os.environ.get(
    "OPENSEARCH_CLUSTER_ENV_FILE",
    PROJECT_DIR / "dev/config/opensearch-cluster/cluster.env.example",
))
EXPECTED_SERVICES = {"opensearch-1", "opensearch-2", "opensearch-3"}
EXPECTED_IMAGE = "ghcr.io/idaholab/malcolm/opensearch:26.07.1"


def fail(message: str) -> None:
    print(f"CLUSTER_COMPOSE_RESULT=FAIL: {message}", file=sys.stderr)
    raise SystemExit(1)


def main() -> None:
    command = [
        "docker",
        "compose",
        "--env-file",
        str(ENV_FILE),
        "-f",
        str(COMPOSE_FILE),
        "config",
        "--format",
        "json",
    ]
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        fail(result.stderr.strip() or "docker compose config failed")

    config = json.loads(result.stdout)
    services = config.get("services", {})
    if not EXPECTED_SERVICES.issubset(services):
        fail(f"missing OpenSearch node services: {sorted(EXPECTED_SERVICES - set(services))}")

    data_sources = set()
    for name in sorted(EXPECTED_SERVICES):
        service = services[name]
        environment = service.get("environment", {})

        if service.get("image") != EXPECTED_IMAGE:
            fail(f"{name}: unexpected image {service.get('image')}")
        if service.get("hostname") != name:
            fail(f"{name}: hostname must match service name")
        if environment.get("node.name") != name:
            fail(f"{name}: node.name must be unique")
        if environment.get("network.publish_host") != name:
            fail(f"{name}: network.publish_host must use the certificate DNS name")
        if environment.get("discovery.type") == "single-node":
            fail(f"{name}: inherited single-node mode")
        if environment.get("OPENSEARCH_SKIP_SELF_SIGNED_KEY_GEN") != "true":
            fail(f"{name}: automatic mono-node PKI is not disabled")

        java_opts = environment.get("OPENSEARCH_JAVA_OPTS", "")
        if not any(option.startswith("-Xms") for option in java_opts.split()) or not any(
            option.startswith("-Xmx") for option in java_opts.split()
        ):
            fail(f"{name}: expected an explicit heap")

        if service.get("restart") != "unless-stopped":
            fail(f"{name}: unexpected restart policy")
        if not service.get("healthcheck", {}).get("test"):
            fail(f"{name}: healthcheck missing")
        healthcheck = " ".join(service["healthcheck"]["test"])
        if '"503"' not in healthcheck:
            fail(f"{name}: healthcheck must tolerate the pre-Security startup response")
        if service.get("ports"):
            fail(f"{name}: a node port must not be published on the host")

        exposed = {str(port).split("/", maxsplit=1)[0] for port in service.get("expose", [])}
        if not {"9200", "9300"}.issubset(exposed):
            fail(f"{name}: ports 9200 and 9300 must be exposed internally")

        networks = service.get("networks", {})
        if "cluster-transport" not in networks:
            fail(f"{name}: private transport network missing")

        data_mounts = [
            mount
            for mount in service.get("volumes", [])
            if mount.get("target") == "/usr/share/opensearch/data"
        ]
        if len(data_mounts) != 1:
            fail(f"{name}: expected exactly one data volume")
        data_sources.add(data_mounts[0].get("source"))

    expected_volumes = {"opensearch-data-1", "opensearch-data-2", "opensearch-data-3"}
    if data_sources != expected_volumes:
        fail(f"data volumes are not isolated: {sorted(data_sources)}")

    network = config.get("networks", {}).get("cluster-transport", {})
    if network.get("internal") is not True:
        fail("cluster-transport network must be internal")

    print("services=opensearch-1,opensearch-2,opensearch-3")
    print("data_volumes=opensearch-data-1,opensearch-data-2,opensearch-data-3")
    print("node_host_ports=none")
    print("CLUSTER_COMPOSE_RESULT=PASS")


if __name__ == "__main__":
    main()
