#!/usr/bin/env python3

"""Validate an operator configuration and render the cluster runtime state."""

from __future__ import annotations

import argparse
import copy
import ipaddress
import os
import re
from pathlib import Path
from typing import Any

import yaml


DEFAULT_CONFIG: dict[str, Any] = {
    "version": 1,
    "cluster": {
        "name": "oculox-opensearch",
        "image": "ghcr.io/idaholab/malcolm/opensearch:26.07.1",
        "heap_per_node": "2g",
        "restart_policy": "unless-stopped",
    },
    "endpoint": {"ip": None, "port": 9200, "monitoring_port": 8404},
    "storage": {
        "primary_shards": 1,
        "replicas": 1,
        "max_docvalue_fields_search": 200,
        "watermarks": {"low": 75, "high": 85, "flood_stage": 90},
    },
    "policies": {
        "arkime_sessions": {
            "enabled": True,
            "optimize_after_days": 30,
            "delete_enabled": False,
            "delete_after_days": 90,
        },
        "arkime_history": {
            "enabled": True,
            "delete_enabled": False,
            "delete_after_days": 91,
        },
        "beats": {
            "enabled": True,
            "optimize_after_days": 30,
            "delete_enabled": False,
            "delete_after_days": 90,
        },
    },
    "snapshots": {"enabled": False},
}

ALLOWED_KEYS = {
    (): set(DEFAULT_CONFIG),
    ("cluster",): set(DEFAULT_CONFIG["cluster"]),
    ("endpoint",): set(DEFAULT_CONFIG["endpoint"]),
    ("storage",): set(DEFAULT_CONFIG["storage"]),
    ("storage", "watermarks"): set(DEFAULT_CONFIG["storage"]["watermarks"]),
    ("policies",): set(DEFAULT_CONFIG["policies"]),
    ("policies", "arkime_sessions"): set(DEFAULT_CONFIG["policies"]["arkime_sessions"]),
    ("policies", "arkime_history"): set(DEFAULT_CONFIG["policies"]["arkime_history"]),
    ("policies", "beats"): set(DEFAULT_CONFIG["policies"]["beats"]),
    ("snapshots",): set(DEFAULT_CONFIG["snapshots"]),
}


def merge(base: dict[str, Any], override: dict[str, Any], path: tuple[str, ...] = ()) -> None:
    allowed = ALLOWED_KEYS[path]
    unknown = sorted(set(override) - allowed)
    if unknown:
        location = ".".join(path) or "root"
        raise ValueError(f"Unknown setting(s) under {location}: {', '.join(unknown)}")
    for key, value in override.items():
        target = base.get(key)
        child_path = (*path, key)
        if isinstance(target, dict):
            if not isinstance(value, dict):
                raise ValueError(f"{'.'.join(child_path)} must be a mapping")
            merge(target, value, child_path)
        else:
            base[key] = value


def integer(value: Any, name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def boolean(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be true or false")
    return value


def validate(config: dict[str, Any]) -> None:
    if config["version"] != 1:
        raise ValueError("Only configuration version 1 is supported")

    cluster = config["cluster"]
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", str(cluster["name"])):
        raise ValueError("cluster.name contains unsupported characters")
    if not str(cluster["image"]).strip():
        raise ValueError("cluster.image is required")
    if not re.fullmatch(r"[1-9][0-9]*[gGmM]", str(cluster["heap_per_node"])):
        raise ValueError("cluster.heap_per_node must use a value such as 2g or 2048m")
    if cluster["restart_policy"] not in {"no", "always", "on-failure", "unless-stopped"}:
        raise ValueError("cluster.restart_policy is invalid")

    endpoint = config["endpoint"]
    try:
        address = ipaddress.ip_address(str(endpoint["ip"]))
    except ValueError as error:
        raise ValueError("endpoint.ip must be a valid IP address") from error
    if address.version != 4 or address.is_unspecified or address.is_multicast:
        raise ValueError("endpoint.ip must be a usable IPv4 address")
    integer(endpoint["port"], "endpoint.port", 1, 65535)
    integer(endpoint["monitoring_port"], "endpoint.monitoring_port", 1, 65535)
    if endpoint["port"] == endpoint["monitoring_port"]:
        raise ValueError("endpoint.port and endpoint.monitoring_port must differ")

    storage = config["storage"]
    integer(storage["primary_shards"], "storage.primary_shards", 1, 64)
    integer(storage["replicas"], "storage.replicas", 1, 2)
    integer(
        storage["max_docvalue_fields_search"],
        "storage.max_docvalue_fields_search",
        100,
        1000,
    )
    watermarks = storage["watermarks"]
    low = integer(watermarks["low"], "storage.watermarks.low", 1, 97)
    high = integer(watermarks["high"], "storage.watermarks.high", 2, 98)
    flood = integer(watermarks["flood_stage"], "storage.watermarks.flood_stage", 3, 99)
    if not low < high < flood:
        raise ValueError("disk watermarks must satisfy low < high < flood_stage")

    for policy_name, policy in config["policies"].items():
        boolean(policy["enabled"], f"policies.{policy_name}.enabled")
        boolean(policy["delete_enabled"], f"policies.{policy_name}.delete_enabled")
        integer(
            policy["delete_after_days"],
            f"policies.{policy_name}.delete_after_days",
            1,
            3650,
        )
        if "optimize_after_days" in policy:
            optimize = integer(
                policy["optimize_after_days"],
                f"policies.{policy_name}.optimize_after_days",
                1,
                3650,
            )
            if policy["delete_enabled"] and optimize >= policy["delete_after_days"]:
                raise ValueError(
                    f"policies.{policy_name}.optimize_after_days must be lower than delete_after_days"
                )

    if boolean(config["snapshots"]["enabled"], "snapshots.enabled"):
        raise ValueError("snapshots are not available yet; keep snapshots.enabled=false")


def env_bool(value: bool) -> str:
    return "true" if value else "false"


def render_env(
    config: dict[str, Any], output: Path, proxy_uid: int, proxy_gid: int
) -> None:
    cluster = config["cluster"]
    endpoint = config["endpoint"]
    storage = config["storage"]
    policies = config["policies"]
    values = {
        "OPENSEARCH_IMAGE": cluster["image"],
        "OPENSEARCH_CLUSTER_NAME": cluster["name"],
        "OPENSEARCH_DISCOVERY_SEED_HOSTS": "opensearch-1:9300,opensearch-2:9300,opensearch-3:9300",
        "OPENSEARCH_INITIAL_CLUSTER_MANAGER_NODES": "opensearch-1,opensearch-2,opensearch-3",
        "OPENSEARCH_HEAP_SIZE": cluster["heap_per_node"],
        "OPENSEARCH_RESTART_POLICY": cluster["restart_policy"],
        "OPENSEARCH_CLUSTER_ENDPOINT": f"https://{endpoint['ip']}:{endpoint['port']}",
        "OPENSEARCH_ENDPOINT_BIND_IP": endpoint["ip"],
        "OPENSEARCH_ENDPOINT_PORT": endpoint["port"],
        "OPENSEARCH_MONITORING_PORT": endpoint["monitoring_port"],
        "OPENSEARCH_PROXY_IMAGE": "haproxy:3.2.21-alpine",
        "OPENSEARCH_PROXY_UID": proxy_uid,
        "OPENSEARCH_PROXY_GID": proxy_gid,
        "OPENSEARCH_PRIMARY_SHARDS": storage["primary_shards"],
        "OPENSEARCH_REPLICAS": storage["replicas"],
        "OPENSEARCH_MAX_DOCVALUE_FIELDS_SEARCH": storage["max_docvalue_fields_search"],
        "OPENSEARCH_WATERMARK_LOW": storage["watermarks"]["low"],
        "OPENSEARCH_WATERMARK_HIGH": storage["watermarks"]["high"],
        "OPENSEARCH_WATERMARK_FLOOD_STAGE": storage["watermarks"]["flood_stage"],
        "OPENSEARCH_POLICY_ARKIME_SESSIONS_ENABLED": env_bool(policies["arkime_sessions"]["enabled"]),
        "OPENSEARCH_POLICY_ARKIME_SESSIONS_OPTIMIZE_DAYS": policies["arkime_sessions"]["optimize_after_days"],
        "OPENSEARCH_POLICY_ARKIME_SESSIONS_DELETE_ENABLED": env_bool(policies["arkime_sessions"]["delete_enabled"]),
        "OPENSEARCH_POLICY_ARKIME_SESSIONS_DELETE_DAYS": policies["arkime_sessions"]["delete_after_days"],
        "OPENSEARCH_POLICY_ARKIME_HISTORY_ENABLED": env_bool(policies["arkime_history"]["enabled"]),
        "OPENSEARCH_POLICY_ARKIME_HISTORY_DELETE_ENABLED": env_bool(policies["arkime_history"]["delete_enabled"]),
        "OPENSEARCH_POLICY_ARKIME_HISTORY_DELETE_DAYS": policies["arkime_history"]["delete_after_days"],
        "OPENSEARCH_POLICY_BEATS_ENABLED": env_bool(policies["beats"]["enabled"]),
        "OPENSEARCH_POLICY_BEATS_OPTIMIZE_DAYS": policies["beats"]["optimize_after_days"],
        "OPENSEARCH_POLICY_BEATS_DELETE_ENABLED": env_bool(policies["beats"]["delete_enabled"]),
        "OPENSEARCH_POLICY_BEATS_DELETE_DAYS": policies["beats"]["delete_after_days"],
        "OPENSEARCH_SNAPSHOTS_ENABLED": env_bool(config["snapshots"]["enabled"]),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("".join(f"{key}={value}\n" for key, value in values.items()), encoding="ascii")
    output.chmod(0o600)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--endpoint-ip")
    parser.add_argument("--heap")
    parser.add_argument("--output-env", type=Path)
    parser.add_argument("--output-config", type=Path)
    parser.add_argument("--proxy-uid", type=int, default=os.getuid())
    parser.add_argument("--proxy-gid", type=int, default=os.getgid())
    parser.add_argument("--print", action="store_true", dest="print_config")
    args = parser.parse_args()

    config = copy.deepcopy(DEFAULT_CONFIG)
    if args.config:
        loaded = yaml.safe_load(args.config.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError("the cluster configuration must be a YAML mapping")
        merge(config, loaded)
    if args.endpoint_ip:
        config["endpoint"]["ip"] = args.endpoint_ip
    if args.heap:
        config["cluster"]["heap_per_node"] = args.heap
    validate(config)

    if args.output_env:
        render_env(config, args.output_env, args.proxy_uid, args.proxy_gid)
    if args.output_config:
        args.output_config.parent.mkdir(parents=True, exist_ok=True)
        args.output_config.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
        args.output_config.chmod(0o600)
    if args.print_config:
        print(yaml.safe_dump(config, sort_keys=False), end="")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, yaml.YAMLError) as error:
        raise SystemExit(f"Invalid cluster configuration: {error}") from error
