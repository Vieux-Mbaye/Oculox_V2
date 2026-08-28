#!/usr/bin/env python3

"""Measure a PCAP ingestion path across separate Core and Hedgehog hosts."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shutil
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_DIR = Path(__file__).resolve().parents[3]
STATE_FILE = PROJECT_DIR / "dev/generated/deployment.env"
CLIENT_DIR = PROJECT_DIR / "dev/generated/opensearch-clients"
CA_FILE = PROJECT_DIR / "nginx/ca-trust/oculox-opensearch-ca.crt"
RESULT_ROOT = PROJECT_DIR / "dev/generated/validation/ingestion"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="action", required=True)
    baseline = sub.add_parser("baseline")
    baseline.add_argument("--output", required=True, type=Path)
    inject = sub.add_parser("inject")
    inject.add_argument("--pcap", required=True, type=Path)
    inject.add_argument("--run-id", required=True)
    inject.add_argument("--output", required=True, type=Path)
    inject.add_argument("--wait", type=int, default=180)
    inject.add_argument(
        "--allow-core",
        action="store_true",
        help="autorise une injection de laboratoire depuis le Core local",
    )
    finalize = sub.add_parser("finalize")
    finalize.add_argument("--baseline", required=True, type=Path)
    finalize.add_argument("--collector-report", required=True, type=Path)
    finalize.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        if raw.strip() and not raw.lstrip().startswith("#") and "=" in raw:
            key, value = raw.split("=", 1)
            values[key] = value.strip().strip('"').strip("'")
    return values


def role() -> str:
    return env_file(STATE_FILE).get("OCULOX_ROLE", "") if STATE_FILE.is_file() else ""


def credentials() -> tuple[str, str, str]:
    endpoint = env_file(CLIENT_DIR / "deployment.env")["OPENSEARCH_CLUSTER_ENDPOINT"]
    for raw in (CLIENT_DIR / "api.curlrc").read_text(encoding="utf-8").splitlines():
        if raw.strip().startswith("user") and "=" in raw:
            user, password = raw.split("=", 1)[1].strip().strip('"').split(":", 1)
            return endpoint, user, password
    raise RuntimeError("compte API OpenSearch absent")


def os_request(path: str) -> tuple[int, dict[str, Any]]:
    endpoint, user, password = credentials()
    auth = base64.b64encode(f"{user}:{password}".encode()).decode()
    request = urllib.request.Request(endpoint + path, headers={"Authorization": f"Basic {auth}"})
    context = ssl.create_default_context(cafile=str(CA_FILE))
    try:
        with urllib.request.urlopen(request, context=context, timeout=20) as response:
            return response.status, json.loads(response.read().decode())
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return 404, {}
        raise


def run(*command: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, check=False)


def container_for(service: str) -> str | None:
    result = run("docker", "ps", "--filter", f"label=com.docker.compose.service={service}",
                 "--format", "{{.Names}}")
    names = [line for line in result.stdout.splitlines() if line]
    return names[0] if len(names) == 1 else None


def logstash_events() -> dict[str, dict[str, int]]:
    metrics: dict[str, dict[str, int]] = {}
    for service in ("logstash", "logstash-2"):
        container = container_for(service)
        if not container:
            metrics[service] = {"in": -1, "out": -1, "filtered": -1}
            continue
        response = run("docker", "exec", container, "curl", "-fsS",
                       "http://127.0.0.1:9600/_node/stats/events")
        try:
            events = json.loads(response.stdout)["events"]
            metrics[service] = {key: int(events.get(key, 0)) for key in ("in", "out", "filtered")}
        except (json.JSONDecodeError, KeyError):
            metrics[service] = {"in": -1, "out": -1, "filtered": -1}
    return metrics


def count(pattern: str) -> int:
    code, payload = os_request(f"/{pattern}/_count")
    return int(payload.get("count", 0)) if code == 200 else 0


def cluster_metrics() -> dict[str, Any]:
    _, health = os_request("/_cluster/health")
    _, nodes = os_request("/_nodes/stats/thread_pool,indices")
    rejected = 0
    failed = 0
    for node in nodes.get("nodes", {}).values():
        pools = node.get("thread_pool", {})
        rejected += sum(int(pools.get(name, {}).get("rejected", 0)) for name in ("write", "index"))
        failed += int(node.get("indices", {}).get("indexing", {}).get("index_failed", 0))
    return {
        "health": health.get("status"),
        "documents": count("malcolm_beats_*") + count("arkime_sessions3-*"),
        "pipeline_documents": count("malcolm_beats_*"),
        "arkime_sessions": count("arkime_sessions3-*"),
        "indexing_rejections": rejected,
        "indexing_failures": failed,
    }


def filebeat_events() -> dict[str, int]:
    container = container_for("filebeat")
    if not container:
        return {"published": -1, "acked": -1, "failed": -1}
    response = run("docker", "exec", container, "curl", "-fsS", "http://127.0.0.1:5066/stats")
    try:
        output = json.loads(response.stdout).get("libbeat", {}).get("output", {}).get("events", {})
        return {"published": int(output.get("total", 0)), "acked": int(output.get("acked", 0)),
                "failed": int(output.get("failed", 0))}
    except json.JSONDecodeError:
        return {"published": -1, "acked": -1, "failed": -1}


def packet_count(path: Path) -> int | None:
    capinfos = run("capinfos", "-c", "-M", str(path)) if shutil.which("capinfos") else None
    if capinfos and capinfos.returncode == 0:
        for line in capinfos.stdout.splitlines():
            if "Number of packets" in line and ":" in line:
                return int(line.split(":", 1)[1].strip().replace(",", ""))
    if shutil.which("tcpdump"):
        tcpdump = run("tcpdump", "-nn", "-r", str(path))
        if tcpdump.returncode == 0:
            return len(tcpdump.stdout.splitlines())
    return None


def tree_state(path: Path) -> dict[str, int]:
    files = [item for item in path.rglob("*") if item.is_file()] if path.exists() else []
    return {"files": len(files), "bytes": sum(item.stat().st_size for item in files)}


def snapshot_core() -> dict[str, Any]:
    return {"captured_at": datetime.now(timezone.utc).isoformat(), "logstash": logstash_events(),
            "opensearch": cluster_metrics()}


def delta(after: int, before: int) -> int | None:
    return after - before if before >= 0 and after >= 0 else None


def main() -> int:
    args = parse_args()
    if args.action in {"baseline", "finalize"} and role() != "principal":
        raise SystemExit("baseline et finalize doivent être exécutés sur Oculox Core")
    if args.action == "inject" and role() != "hedgehog" and not args.allow_core:
        raise SystemExit(
            "inject doit être exécuté sur Hedgehog; utiliser --allow-core uniquement pour un banc local"
        )

    if args.action == "baseline":
        report = {"schema": 1, "kind": "ingestion-baseline", **snapshot_core()}
        output = args.output
    elif args.action == "inject":
        pcap = args.pcap.resolve()
        if not pcap.is_file():
            raise SystemExit(f"PCAP introuvable: {pcap}")
        upload = PROJECT_DIR / "pcap/upload"
        upload.mkdir(parents=True, exist_ok=True)
        before_zeek = tree_state(PROJECT_DIR / "zeek-logs")
        before_suricata = tree_state(PROJECT_DIR / "suricata-logs")
        before_filebeat = filebeat_events()
        target = upload / f"{args.run_id}-{pcap.name}"
        shutil.copy2(pcap, target)
        started = time.monotonic()
        after_zeek = before_zeek
        after_suricata = before_suricata
        after_filebeat = before_filebeat
        while time.monotonic() - started < args.wait:
            after_zeek = tree_state(PROJECT_DIR / "zeek-logs")
            after_suricata = tree_state(PROJECT_DIR / "suricata-logs")
            after_filebeat = filebeat_events()
            acked = delta(after_filebeat["acked"], before_filebeat["acked"])
            if (not target.exists() and after_zeek["bytes"] > before_zeek["bytes"]
                    and after_suricata["bytes"] > before_suricata["bytes"]
                    and (acked or 0) > 0):
                break
            time.sleep(5)
        report = {
            "schema": 1, "kind": "ingestion-collector", "run_id": args.run_id,
            "source_role": role(), "core_lab_override": bool(args.allow_core),
            "captured_at": datetime.now(timezone.utc).isoformat(), "pcap": pcap.name,
            "pcap_sha256": hashlib.sha256(pcap.read_bytes()).hexdigest(),
            "packets": packet_count(pcap), "accepted_by_monitor": not target.exists(),
            "observation_seconds": round(time.monotonic() - started, 3),
            "zeek": {"files_delta": after_zeek["files"] - before_zeek["files"],
                     "bytes_delta": after_zeek["bytes"] - before_zeek["bytes"]},
            "suricata": {"files_delta": after_suricata["files"] - before_suricata["files"],
                          "bytes_delta": after_suricata["bytes"] - before_suricata["bytes"]},
            "filebeat": {key: delta(after_filebeat[key], before_filebeat[key]) for key in before_filebeat},
        }
        output = args.output
    else:
        baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
        collector = json.loads(args.collector_report.read_text(encoding="utf-8"))
        current = snapshot_core()
        logstash_delta = {
            service: {key: delta(current["logstash"][service][key], baseline["logstash"][service][key])
                      for key in ("in", "out", "filtered")}
            for service in ("logstash", "logstash-2")
        }
        os_delta = {key: current["opensearch"][key] - baseline["opensearch"][key]
                    for key in ("documents", "pipeline_documents", "arkime_sessions",
                                "indexing_rejections", "indexing_failures")}
        dashboards = container_for("dashboards")
        dashboard_ok = False
        if dashboards:
            inspect = run("docker", "inspect", "--format", "{{.State.Health.Status}}", dashboards)
            dashboard_ok = inspect.stdout.strip() == "healthy"
        checks = {
            "pcap_processed": bool(collector.get("accepted_by_monitor")),
            "packets_measured": isinstance(collector.get("packets"), int) and collector["packets"] > 0,
            "zeek_events_produced": collector.get("zeek", {}).get("bytes_delta", 0) > 0,
            "suricata_events_produced": collector.get("suricata", {}).get("bytes_delta", 0) > 0,
            "filebeat_published": (collector.get("filebeat", {}).get("acked") or 0) > 0,
            "logstash_1_received": (logstash_delta["logstash"]["in"] or 0) > 0,
            "logstash_2_received": (logstash_delta["logstash-2"]["in"] or 0) > 0,
            "pipeline_documents_indexed": os_delta["pipeline_documents"] > 0,
            "arkime_sessions_created": os_delta["arkime_sessions"] > 0,
            "dashboards_can_present_data": dashboard_ok and os_delta["documents"] > 0,
            "no_new_opensearch_rejection": os_delta["indexing_rejections"] <= 0,
            "no_new_opensearch_failure": os_delta["indexing_failures"] <= 0,
            "cluster_available": current["opensearch"]["health"] in {"green", "yellow"},
        }
        report = {"schema": 1, "kind": "ingestion-final", "run_id": collector.get("run_id"),
                  "captured_at": current["captured_at"], "collector": collector,
                  "logstash_delta": logstash_delta, "opensearch_delta": os_delta,
                  "checks": checks, "result": "PASS" if all(checks.values()) else "FAIL"}
        output = args.output

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    os.chmod(output, 0o600)
    print(json.dumps(report, indent=2))
    print(f"REPORT {output}")
    if args.action == "finalize":
        print(f"INGESTION_RESULT={report['result']}")
        return 0 if report["result"] == "PASS" else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
