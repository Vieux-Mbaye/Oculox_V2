#!/usr/bin/env python3

import json
import os
import subprocess
import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[3]
COMPOSE_DIR = PROJECT_DIR / "dev/compose/opensearch-cluster"
ENV_FILE = Path(os.environ.get(
    "OPENSEARCH_CLUSTER_ENV_FILE",
    PROJECT_DIR / "dev/config/opensearch-cluster/cluster.env.example",
))
NODE_NAMES = ("opensearch-1", "opensearch-2", "opensearch-3")
EXPECTED_SEEDS = tuple(f"{name}:9300" for name in NODE_NAMES)


def fail(message: str) -> None:
    print(f"DISCOVERY_CONFIG_RESULT=FAIL: {message}", file=sys.stderr)
    raise SystemExit(1)


def render(*compose_files: str) -> dict:
    command = ["docker", "compose", "--env-file", str(ENV_FILE)]
    for compose_file in compose_files:
        command.extend(("-f", str(COMPOSE_DIR / compose_file)))
    command.extend(("config", "--format", "json"))

    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        fail(result.stderr.strip() or "docker compose config failed")
    return json.loads(result.stdout)


def csv_values(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def main() -> None:
    base = render("compose.yml")
    bootstrap = render("compose.yml", "compose.bootstrap.yml")

    base_services = base.get("services", {})
    bootstrap_services = bootstrap.get("services", {})
    if not set(NODE_NAMES).issubset(base_services):
        fail("the base Compose does not contain the expected nodes")
    if not set(NODE_NAMES).issubset(bootstrap_services):
        fail("the bootstrap Compose does not contain the expected nodes")

    seed_lists = set()
    bootstrap_lists = set()
    discovered_node_names = set()

    for name in NODE_NAMES:
        base_environment = base_services[name].get("environment", {})
        bootstrap_environment = bootstrap_services[name].get("environment", {})

        if base_environment.get("cluster.name") != "oculox-opensearch":
            fail(f"{name}: unexpected cluster.name")
        if "discovery.type" in base_environment:
            fail(f"{name}: discovery.type must be absent for multi-node discovery")
        entrypoint = base_services[name].get("entrypoint", [])
        if "/usr/local/bin/oculox-opensearch-entrypoint.sh" not in entrypoint:
            fail(f"{name}: multi-node entrypoint is not installed")
        command = base_services[name].get("command", [])
        if command != ["/usr/share/opensearch/opensearch-docker-entrypoint.sh"]:
            fail(f"{name}: original OpenSearch command is not preserved")
        if base_environment.get("transport.port") != "9300":
            fail(f"{name}: transport.port must be 9300")

        node_name = base_environment.get("node.name")
        discovered_node_names.add(node_name)
        seed_lists.add(csv_values(base_environment.get("discovery.seed_hosts", "")))

        if "cluster.initial_cluster_manager_nodes" in base_environment:
            fail(f"{name}: bootstrap setting leaked into routine restarts")
        bootstrap_lists.add(
            csv_values(bootstrap_environment.get("cluster.initial_cluster_manager_nodes", ""))
        )

    if discovered_node_names != set(NODE_NAMES):
        fail(f"node.name mismatch: {sorted(discovered_node_names)}")
    if seed_lists != {EXPECTED_SEEDS}:
        fail(f"seed lists are not identical: {sorted(seed_lists)}")
    if bootstrap_lists != {NODE_NAMES}:
        fail(f"bootstrap lists are not identical: {sorted(bootstrap_lists)}")

    seed_names = tuple(seed.rsplit(":", maxsplit=1)[0] for seed in EXPECTED_SEEDS)
    if seed_names != NODE_NAMES:
        fail("seed hostnames do not match node.name values")

    print("cluster_name=oculox-opensearch")
    print(f"seed_hosts={','.join(EXPECTED_SEEDS)}")
    print(f"initial_cluster_manager_nodes={','.join(NODE_NAMES)}")
    print("identical_configuration=3/3")
    print("DISCOVERY_CONFIG_RESULT=PASS")
    pki_marker = PROJECT_DIR / "dev/generated/opensearch-cluster/pki/.oculox-opensearch-pki"
    runtime_state = "PENDING_FIRST_START" if pki_marker.is_file() else "PENDING_PKI"
    print(f"DISCOVERY_RUNTIME_RESULT={runtime_state}")


if __name__ == "__main__":
    main()
