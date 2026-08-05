#!/usr/bin/env python3

"""Collect a lightweight, reproducible snapshot of the reduced Oculox stack."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import yaml


PROJECT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_THRESHOLDS = PROJECT_DIR / "dev" / "monitoring" / "thresholds.yml"
COMMAND_TIMEOUT_SECONDS = 30


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--label", default="runtime")
    parser.add_argument("--thresholds", type=Path, default=DEFAULT_THRESHOLDS)
    parser.add_argument(
        "--lightweight",
        action="store_true",
        help="Ignore les statistiques OpenSearch détaillées pour limiter l'impact de la mesure.",
    )
    return parser.parse_args()


def run(*command: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=False,
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as error:
        stdout = error.stdout if isinstance(error.stdout, str) else ""
        stderr = error.stderr if isinstance(error.stderr, str) else ""
        timeout_message = (
            f"commande interrompue après {COMMAND_TIMEOUT_SECONDS} secondes"
        )
        return subprocess.CompletedProcess(
            command,
            124,
            stdout,
            f"{stderr}\n{timeout_message}".strip(),
        )


def json_command(*command: str) -> dict[str, Any] | None:
    result = run(*command)
    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def parse_percent(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return float(value.rstrip("%"))
    except ValueError:
        return None


def host_metrics() -> dict[str, Any]:
    memory: dict[str, int] = {}
    with Path("/proc/meminfo").open(encoding="utf-8") as meminfo:
        for line in meminfo:
            key, value = line.split(":", 1)
            memory[key] = int(value.strip().split()[0]) * 1024

    total = memory["MemTotal"]
    available = memory["MemAvailable"]
    disk = shutil.disk_usage(PROJECT_DIR)
    return {
        "cpu_count": os.cpu_count(),
        "memory_total_bytes": total,
        "memory_available_bytes": available,
        "memory_used_percent": round((total - available) * 100 / total, 3),
        "disk_total_bytes": disk.total,
        "disk_free_bytes": disk.free,
        "disk_used_percent": round(disk.used * 100 / disk.total, 3),
        "load_average": list(os.getloadavg()),
    }


def container_metrics() -> dict[str, Any]:
    containers: dict[str, Any] = {}
    ps = run(
        "docker",
        "ps",
        "--filter",
        "name=oculox-",
        "--format",
        "{{json .}}",
    )
    if ps.returncode != 0:
        return {"error": ps.stderr.strip() or "docker ps failed"}

    for line in ps.stdout.splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        name = item["Names"]
        health = json_command("docker", "inspect", "--format", "{{json .State}}", name)
        containers[name] = {
            "status": item.get("Status"),
            "state": health,
        }

    if not containers:
        return containers

    stats = run(
        "docker",
        "stats",
        "--no-stream",
        "--format",
        "{{json .}}",
        *containers.keys(),
    )
    if stats.returncode == 0:
        for line in stats.stdout.splitlines():
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            name = item.get("Name") or item.get("Container")
            if name in containers:
                containers[name]["resources"] = {
                    "cpu_percent": parse_percent(item.get("CPUPerc")),
                    "memory_percent": parse_percent(item.get("MemPerc")),
                    "memory_usage": item.get("MemUsage"),
                    "network_io": item.get("NetIO"),
                    "block_io": item.get("BlockIO"),
                    "pids": item.get("PIDs"),
                }
    return containers


def logstash_metrics() -> dict[str, Any]:
    result: dict[str, Any] = {}
    for container in ("oculox-logstash-1", "oculox-logstash-2-1"):
        inspect = run("docker", "inspect", "--format", "{{json .State}}", container)
        if inspect.returncode != 0:
            # Une instance volontairement absente (mode simple) n'est pas une panne.
            continue
        try:
            state = json.loads(inspect.stdout)
        except json.JSONDecodeError:
            result[container] = {"available": False}
            continue
        if not state.get("Running"):
            result[container] = {"available": False}
            continue

        pipelines = json_command(
            "docker",
            "exec",
            container,
            "curl",
            "-fsS",
            "http://127.0.0.1:9600/_node/stats/pipelines",
        )
        jvm = json_command(
            "docker",
            "exec",
            container,
            "curl",
            "-fsS",
            "http://127.0.0.1:9600/_node/stats/jvm",
        )
        result[container] = {
            "available": pipelines is not None,
            "pipelines": (pipelines or {}).get("pipelines", {}),
            "jvm": (jvm or {}).get("jvm", {}),
        }
    return result


def opensearch_metrics(lightweight: bool = False) -> dict[str, Any]:
    state = json_command(
        "docker", "inspect", "--format", "{{json .State}}", "oculox-opensearch-1"
    )
    if not state or not state.get("Running"):
        return {"available": False}

    curl_base = (
        "docker",
        "exec",
        "oculox-opensearch-1",
        "curl",
        "-K",
        "/var/local/curlrc/.opensearch.primary.curlrc",
        "-sk",
    )
    health = json_command(*curl_base, "https://localhost:9200/_cluster/health")
    nodes = None
    if not lightweight:
        nodes = json_command(
            *curl_base,
            "https://localhost:9200/_nodes/stats/jvm,fs,indices,thread_pool",
        )
    return {"available": health is not None, "health": health, "nodes": nodes}


def filebeat_metrics() -> dict[str, Any]:
    state = json_command(
        "docker", "inspect", "--format", "{{json .State}}", "oculox-filebeat-1"
    )
    if not state or not state.get("Running"):
        return {"available": False}
    stats = json_command(
        "docker",
        "exec",
        "oculox-filebeat-1",
        "curl",
        "-fsS",
        "http://127.0.0.1:5066/stats",
    )
    return {"available": stats is not None, "stats": stats}


def nested(data: dict[str, Any], *keys: str, default: Any = None) -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def evaluate_alerts(snapshot: dict[str, Any], thresholds: dict[str, Any]) -> list[dict[str, str]]:
    alerts: list[dict[str, str]] = []

    def add(level: str, component: str, message: str) -> None:
        alerts.append({"level": level, "component": component, "message": message})

    for metric in ("memory", "disk"):
        value = snapshot["host"][f"{metric}_used_percent"]
        critical = thresholds["host"][f"{metric}_critical_percent"]
        warning = thresholds["host"][f"{metric}_warning_percent"]
        if value >= critical:
            add("critical", "host", f"{metric} used at {value}%")
        elif value >= warning:
            add("warning", "host", f"{metric} used at {value}%")

    for name, container in snapshot["containers"].items():
        if name == "error":
            continue
        health = nested(container, "state", "Health", "Status")
        if health and health != "healthy":
            add("critical", name, f"container health is {health}")

    for name, instance in snapshot["logstash"].items():
        if not instance.get("available"):
            add("critical", name, "Logstash API unavailable")
            continue
        for pipeline_id, pipeline in instance["pipelines"].items():
            queue = pipeline.get("queue", {})
            maximum = queue.get("max_queue_size_in_bytes") or 0
            current = queue.get("queue_size_in_bytes") or 0
            fill = (current * 100 / maximum) if maximum else 0
            if fill >= thresholds["logstash"]["queue_critical_percent"]:
                add("critical", name, f"{pipeline_id} queue at {fill:.1f}%")
            elif fill >= thresholds["logstash"]["queue_warning_percent"]:
                add("warning", name, f"{pipeline_id} queue at {fill:.1f}%")

            worker = nested(pipeline, "flow", "worker_utilization", "current")
            if worker is not None and worker >= thresholds["logstash"]["worker_warning_percent"]:
                add("warning", name, f"{pipeline_id} worker utilization at {worker:.1f}%")

    health = nested(snapshot, "opensearch", "health")
    if snapshot["opensearch"].get("available") and health:
        if health.get("status") != "green":
            add("warning", "opensearch", f"cluster status is {health.get('status')}")
        if health.get("unassigned_shards", 0) > 0:
            add("critical", "opensearch", "unassigned shards detected")
    elif not snapshot["opensearch"].get("available"):
        add("critical", "opensearch", "OpenSearch API unavailable")

    if not snapshot["filebeat"].get("available"):
        add("warning", "filebeat", "Filebeat HTTP metrics API unavailable")
    return alerts


def main() -> None:
    args = parse_args()
    with args.thresholds.open(encoding="utf-8") as threshold_file:
        thresholds = yaml.safe_load(threshold_file)

    snapshot: dict[str, Any] = {
        "schema_version": 1,
        "label": args.label,
        "timestamp_epoch": time.time(),
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "host": host_metrics(),
        "containers": container_metrics(),
        "filebeat": filebeat_metrics(),
        "logstash": logstash_metrics(),
        "opensearch": opensearch_metrics(args.lightweight),
    }
    snapshot["alerts"] = evaluate_alerts(snapshot, thresholds)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as output_file:
        json.dump(snapshot, output_file, indent=2, sort_keys=True)
        output_file.write("\n")
    temporary.replace(args.output)
    print(args.output)


if __name__ == "__main__":
    main()
