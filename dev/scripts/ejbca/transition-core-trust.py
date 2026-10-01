#!/usr/bin/env python3
"""Coordinate Core trust while a remote OpenSearch endpoint changes issuer."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TRUST = ROOT / "nginx/ca-trust/oculox-opensearch-ca.crt"
BACKUPS = ROOT / "dev/ejbca/generated/backups/core-opensearch-trust"
ENV = ROOT / "config/opensearch.env"
RUNTIME_COMPOSE = ROOT / "dev/generated/docker-compose.runtime.yml"


def reload_dashboards() -> None:
    base = ["docker", "compose", "-f", str(RUNTIME_COMPOSE), "--profile", "malcolm"]
    running = subprocess.run([*base, "ps", "--services", "--status", "running"],
                              capture_output=True, text=True, check=False)
    if running.returncode:
        raise RuntimeError("Cannot determine active OpenSearch clients")
    clients = sorted(set(running.stdout.splitlines()) & {
        "dashboards", "logstash", "logstash-2", "api", "arkime", "arkime-live", "pcap-monitor", "dashboards-helper"})
    if not clients:
        return
    command = [*base, "restart", *clients]
    restarted = subprocess.run(command, capture_output=True, text=True, check=False)
    if restarted.returncode:
        raise RuntimeError(restarted.stderr.strip() or "OpenSearch clients restart failed")
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        status = subprocess.run([*base, "ps", "--format", "json"], capture_output=True, text=True, check=False)
        records = [json.loads(line) for line in status.stdout.splitlines() if line.strip()] if status.returncode == 0 else []
        if records and all(any(record.get("Service") == client and record.get("Health") == "healthy"
                              for record in records) for client in clients):
            return
        time.sleep(5)
    raise RuntimeError("OpenSearch clients did not become healthy after trust reload")


def endpoint() -> str:
    for line in ENV.read_text(encoding="utf-8").splitlines():
        if line.startswith("OPENSEARCH_URL="):
            return line.split("=", 1)[1].strip().strip('"').rstrip("/")
    raise RuntimeError("OPENSEARCH_URL missing")


def check_tls() -> None:
    result = subprocess.run(["curl", "--noproxy", "*", "--silent", "--show-error",
        "--max-time", "15", "--cacert", str(TRUST), "-o", "/dev/null", "-w", "%{http_code}",
        endpoint() + "/_cluster/health"], capture_output=True, text=True, check=False)
    if result.returncode or result.stdout not in {"200", "401", "403"}:
        raise RuntimeError(result.stderr.strip() or f"endpoint TLS/HTTP failed: {result.stdout}")


def atomic(value: bytes) -> None:
    temp = TRUST.with_name("." + TRUST.name + f".tmp-{os.getpid()}")
    temp.write_bytes(value)
    temp.chmod(0o644)
    os.replace(temp, TRUST)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("add", "retire", "restore", "status"))
    parser.add_argument("--new-ca", type=Path)
    parser.add_argument("--backup", type=Path)
    args = parser.parse_args()
    if args.phase == "status":
        check_tls()
        print("Core OpenSearch TLS trust: PASS")
        return
    if args.phase == "restore":
        if not args.backup or not args.backup.resolve().is_relative_to(BACKUPS.resolve()):
            raise RuntimeError("--backup must be under core-opensearch-trust")
        atomic(args.backup.read_bytes())
        check_tls()
        reload_dashboards()
        print("Core trust restored")
        return
    if not args.new_ca or not args.new_ca.is_file():
        raise RuntimeError("--new-ca is required")
    old = TRUST.read_bytes()
    new = args.new_ca.read_bytes()
    for data in (old, new):
        if b"-----BEGIN CERTIFICATE-----" not in data:
            raise RuntimeError("invalid PEM trust bundle")
    if args.phase == "retire":
        # Do not remove the old trust unless the currently presented endpoint
        # already validates against the new EJBCA chain alone.
        probe = subprocess.run(["curl", "--noproxy", "*", "--silent", "--show-error",
            "--max-time", "15", "--cacert", str(args.new_ca), "-o", "/dev/null",
            endpoint() + "/_cluster/health"], capture_output=True, text=True, check=False)
        if probe.returncode:
            raise RuntimeError("new EJBCA trust does not validate active endpoint")
    BACKUPS.mkdir(parents=True, exist_ok=True, mode=0o700)
    BACKUPS.chmod(0o700)
    backup = BACKUPS / (dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + args.phase + ".crt")
    shutil.copy2(TRUST, backup)
    backup.chmod(0o600)
    try:
        atomic(old.rstrip() + b"\n" + new if args.phase == "add" else new)
        check_tls()
        reload_dashboards()
    except Exception:
        atomic(old)
        reload_dashboards()
        raise
    print(f"Core trust {args.phase}: PASS; backup={backup}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
