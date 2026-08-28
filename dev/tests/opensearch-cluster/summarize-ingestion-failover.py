#!/usr/bin/env python3

"""Consolidate Oculox ingestion evidence collected during node outages."""

from __future__ import annotations

import argparse
import base64
import json
import ssl
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_DIR = Path(__file__).resolve().parents[3]
CLIENT_DIR = PROJECT_DIR / "dev/generated/opensearch-clients"
CA_FILE = PROJECT_DIR / "nginx/ca-trust/oculox-opensearch-ca.crt"
EXPECTED_NODES = ("opensearch-1", "opensearch-2", "opensearch-3")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reports-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        if raw.strip() and not raw.lstrip().startswith("#") and "=" in raw:
            key, value = raw.split("=", 1)
            values[key] = value.strip().strip('"').strip("'")
    return values


def credentials() -> tuple[str, str, str]:
    endpoint = env_file(CLIENT_DIR / "deployment.env")["OPENSEARCH_CLUSTER_ENDPOINT"]
    for raw in (CLIENT_DIR / "api.curlrc").read_text(encoding="utf-8").splitlines():
        if raw.strip().startswith("user") and "=" in raw:
            user, password = raw.split("=", 1)[1].strip().strip('"').split(":", 1)
            return endpoint, user, password
    raise RuntimeError("compte API OpenSearch absent")


def cluster_health() -> dict[str, Any]:
    endpoint, user, password = credentials()
    authorization = base64.b64encode(f"{user}:{password}".encode()).decode()
    request = urllib.request.Request(
        endpoint + "/_cluster/health",
        headers={"Authorization": f"Basic {authorization}"},
    )
    context = ssl.create_default_context(cafile=str(CA_FILE))
    with urllib.request.urlopen(request, context=context, timeout=30) as response:
        return json.loads(response.read().decode())


def report_checks(report: dict[str, Any]) -> dict[str, bool]:
    collector = report.get("collector", {})
    filebeat = collector.get("filebeat", {})
    logstash = report.get("logstash_delta", {})
    opensearch = report.get("opensearch_delta", {})
    published = int(filebeat.get("published", -1))
    acked = int(filebeat.get("acked", -1))
    return {
        "report_passed": report.get("result") == "PASS",
        "pcap_accepted": bool(collector.get("accepted_by_monitor")),
        "packets_measured": int(collector.get("packets") or 0) > 0,
        "filebeat_all_published_events_acked": published > 0 and published == acked,
        "filebeat_no_failed_event": int(filebeat.get("failed", -1)) == 0,
        "logstash_1_received": int(logstash.get("logstash", {}).get("in") or 0) > 0,
        "logstash_2_received": int(logstash.get("logstash-2", {}).get("in") or 0) > 0,
        "pipeline_documents_increased": int(opensearch.get("pipeline_documents") or 0) > 0,
        "arkime_sessions_increased": int(opensearch.get("arkime_sessions") or 0) > 0,
        "no_new_indexing_rejection": int(opensearch.get("indexing_rejections") or 0) <= 0,
        "no_new_indexing_failure": int(opensearch.get("indexing_failures") or 0) <= 0,
    }


def main() -> int:
    args = parse_args()
    scenarios: dict[str, Any] = {}
    for node in EXPECTED_NODES:
        path = args.reports_dir / node / "final.json"
        if not path.is_file():
            raise SystemExit(f"rapport manquant: {path}")
        source = json.loads(path.read_text(encoding="utf-8"))
        checks = report_checks(source)
        scenarios[node] = {
            "run_id": source.get("run_id"),
            "packets": source.get("collector", {}).get("packets"),
            "filebeat": source.get("collector", {}).get("filebeat"),
            "logstash_delta": source.get("logstash_delta"),
            "opensearch_delta": source.get("opensearch_delta"),
            "checks": checks,
            "result": "PASS" if all(checks.values()) else "FAIL",
        }

    health = cluster_health()
    recovery_checks = {
        "cluster_green": health.get("status") == "green",
        "three_nodes_present": int(health.get("number_of_nodes", 0)) == 3,
        "three_data_nodes_present": int(health.get("number_of_data_nodes", 0)) == 3,
        "manager_elected": bool(
            health.get("discovered_cluster_manager", health.get("discovered_master"))
        ),
        "zero_unassigned_shards": int(health.get("unassigned_shards", -1)) == 0,
    }
    passed = all(item["result"] == "PASS" for item in scenarios.values()) and all(
        recovery_checks.values()
    )
    report = {
        "schema": 1,
        "kind": "ingestion-failover-summary",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "scenarios": scenarios,
        "final_cluster": {
            "status": health.get("status"),
            "number_of_nodes": health.get("number_of_nodes"),
            "number_of_data_nodes": health.get("number_of_data_nodes"),
            "unassigned_shards": health.get("unassigned_shards"),
            "checks": recovery_checks,
        },
        "result": "PASS" if passed else "FAIL",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    args.output.chmod(0o600)
    print(json.dumps(report, indent=2))
    print(f"REPORT {args.output}")
    print(f"INGESTION_FAILOVER_RESULT={report['result']}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
