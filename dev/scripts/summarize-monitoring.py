#!/usr/bin/env python3

"""Aggregate monitoring snapshots into a compact benchmark summary."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def maximum(target: dict[str, Any], key: str, value: Any) -> None:
    if isinstance(value, (int, float)):
        target[key] = max(target.get(key, value), value)


def main() -> None:
    args = arguments()
    files = sorted(args.input.glob("snapshot_*.json"))
    if not files:
        raise SystemExit(f"Aucun instantané trouvé dans {args.input}")

    summary: dict[str, Any] = {
        "schema_version": 1,
        "snapshot_count": len(files),
        "containers": {},
        "logstash": {},
        "opensearch_statuses": [],
        "alerts": [],
    }
    first: dict[str, Any] | None = None
    last: dict[str, Any] | None = None

    for path in files:
        with path.open(encoding="utf-8") as stream:
            snapshot = json.load(stream)
        first = first or snapshot
        last = snapshot

        for name, container in snapshot.get("containers", {}).items():
            resources = container.get("resources", {})
            aggregate = summary["containers"].setdefault(name, {})
            maximum(aggregate, "max_cpu_percent", resources.get("cpu_percent"))
            maximum(aggregate, "max_memory_percent", resources.get("memory_percent"))

        for name, instance in snapshot.get("logstash", {}).items():
            aggregate_instance = summary["logstash"].setdefault(name, {"pipelines": {}})
            jvm = instance.get("jvm", {})
            maximum(
                aggregate_instance,
                "max_heap_used_percent",
                jvm.get("mem", {}).get("heap_used_percent"),
            )
            for pipeline_id, pipeline in instance.get("pipelines", {}).items():
                aggregate = aggregate_instance["pipelines"].setdefault(pipeline_id, {})
                flow = pipeline.get("flow", {})
                maximum(
                    aggregate,
                    "max_worker_utilization",
                    flow.get("worker_utilization", {}).get("current"),
                )
                maximum(
                    aggregate,
                    "max_queue_backpressure",
                    flow.get("queue_backpressure", {}).get("current"),
                )
                queue = pipeline.get("queue", {})
                maximum(aggregate, "max_queue_bytes", queue.get("queue_size_in_bytes"))
                maximum(
                    aggregate,
                    "max_queue_events",
                    queue.get("events_count"),
                )

        status = snapshot.get("opensearch", {}).get("health", {}).get("status")
        if status and status not in summary["opensearch_statuses"]:
            summary["opensearch_statuses"].append(status)
        summary["alerts"].extend(snapshot.get("alerts", []))

    assert first is not None and last is not None
    summary["start_utc"] = first["timestamp_utc"]
    summary["end_utc"] = last["timestamp_utc"]
    summary["duration_seconds"] = round(
        last["timestamp_epoch"] - first["timestamp_epoch"], 3
    )
    summary["host"] = {
        "start_memory_used_percent": first["host"]["memory_used_percent"],
        "end_memory_used_percent": last["host"]["memory_used_percent"],
        "start_disk_used_percent": first["host"]["disk_used_percent"],
        "end_disk_used_percent": last["host"]["disk_used_percent"],
    }
    unique_alerts = {
        (alert["level"], alert["component"], alert["message"]): alert
        for alert in summary["alerts"]
    }
    summary["alerts"] = list(unique_alerts.values())

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as stream:
        json.dump(summary, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(args.output)


if __name__ == "__main__":
    main()
