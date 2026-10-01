#!/usr/bin/env python3
"""Rotate a running OpenSearch cluster to EJBCA in three reversible phases."""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
GENERATED = ROOT / "dev/generated/opensearch-cluster"
PKI = GENERATED / "pki"
PROXY = GENERATED / "endpoint-proxy"
ENV = GENERATED / "cluster.env"
COMPOSE = ROOT / "dev/compose/opensearch-cluster/compose.yml"
AGENT = ROOT / "dev/generated/pki/remote-agent"
STAGES = ROOT / "dev/ejbca/generated/enrollments"
BACKUPS = GENERATED / "pki-migration-backups"
STATE = GENERATED / "pki-ejbca-migration.json"
OPENSEARCH_CONFIG = ROOT / "dev/config/opensearch-cluster/opensearch.yml"
SERVICES = ("opensearch_node_1", "opensearch_node_2", "opensearch_node_3",
            "opensearch_admin_client", "opensearch_endpoint")
NODES = ("opensearch-1", "opensearch-2", "opensearch-3")
STAGED: dict[str, Path] = {}


def run(*command: str, timeout: int = 60) -> str:
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f"failed: {command[0]}")
    return result.stdout


def compose(*args: str) -> str:
    return run("docker", "compose", "--env-file", str(ENV), "-f", str(COMPOSE), *args, timeout=240)


def env_value(key: str, path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError(f"missing {key}: {path}")


def health(wait_seconds: int = 1800) -> None:
    endpoint = env_value("OPENSEARCH_CLUSTER_ENDPOINT", ENV)
    username = "oculox_platform_admin"
    password = env_value("OCULOX_PLATFORM_ADMIN_PASSWORD", GENERATED / "security/accounts.env")
    ca = PKI / "client-trust/oculox-opensearch-ca.crt"
    until = time.monotonic() + wait_seconds
    last_status = "unavailable"
    next_report = time.monotonic() + 30
    while time.monotonic() < until:
        result = subprocess.run(["curl", "--noproxy", "*", "--silent", "--show-error", "--fail",
            "--max-time", "8", "--cacert", str(ca), "--user", f"{username}:{password}",
            endpoint + "/_cluster/health"], capture_output=True, text=True, check=False)
        if result.returncode == 0:
            try:
                data = json.loads(result.stdout)
                last_status = (f"status={data.get('status')} nodes={data.get('number_of_nodes')} "
                               f"unassigned={data.get('unassigned_shards')}")
                if data.get("status") == "green" and data.get("number_of_nodes") == 3 and data.get("unassigned_shards") == 0:
                    return
            except ValueError:
                last_status = "invalid health response"
        else:
            last_status = result.stderr.strip()[-200:] or "health request failed"
        if time.monotonic() >= next_report:
            print(f"Waiting for cluster: {last_status}", flush=True)
            next_report = time.monotonic() + 30
        time.sleep(5)
    raise RuntimeError(f"cluster did not return to green with three nodes: {last_status}")


def stage(service: str) -> Path:
    if service in STAGED:
        return STAGED[service]
    matches = sorted((folder / service for folder in STAGES.iterdir() if (folder / service / "cert.crt").is_file()),
                     key=lambda path: path.stat().st_mtime)
    if not matches:
        raise RuntimeError(f"missing staged EJBCA certificate: {service}")
    candidate = matches[-1]
    for name in ("cert.crt", "key.key", "ca.crt"):
        if not (candidate / name).is_file():
            raise RuntimeError(f"incomplete stage: {candidate}")
    return candidate


def verify_stages() -> None:
    ca = AGENT / "service-ca.crt"
    if not ca.is_file():
        raise RuntimeError("cluster agent trust is missing")
    settings = yaml.safe_load(OPENSEARCH_CONFIG.read_text(encoding="utf-8"))
    security = settings["plugins"]["security"]
    node_dns = set(security["nodes_dn"])
    admin_dns = set(security["authcz"]["admin_dn"])
    for service in SERVICES:
        folder = stage(service)
        STAGED[service] = folder
        run("openssl", "verify", "-CAfile", str(ca), str(folder / "cert.crt"))
        cert_pub = run("openssl", "x509", "-in", str(folder / "cert.crt"), "-pubkey", "-noout")
        key_pub = run("openssl", "pkey", "-in", str(folder / "key.key"), "-pubout")
        if cert_pub != key_pub:
            raise RuntimeError(f"certificate/key mismatch: {service}")
        issuer = run("openssl", "x509", "-in", str(folder / "cert.crt"), "-noout", "-issuer")
        if "Oculox OpenSearch CA" not in issuer:
            raise RuntimeError(f"not EJBCA OpenSearch issuer: {service}")
        eku = run("openssl", "x509", "-in", str(folder / "cert.crt"), "-noout", "-ext", "extendedKeyUsage")
        usages = ("TLS Web Server Authentication", "TLS Web Client Authentication") if service.startswith("opensearch_node_") else (
            ("TLS Web Client Authentication",) if service == "opensearch_admin_client" else ("TLS Web Server Authentication",))
        if any(usage not in eku for usage in usages):
            raise RuntimeError(f"missing TLS usage: {service}")
        if service == "opensearch_endpoint":
            for field in ("OPENSEARCH_ENDPOINT_BIND_IP", "OPENSEARCH_ENDPOINT_DNS"):
                try:
                    value = env_value(field, ENV)
                except RuntimeError:
                    continue
                if value:
                    option = "-checkip" if field.endswith("IP") else "-checkhost"
                    result = run("openssl", "x509", "-in", str(folder / "cert.crt"), "-noout", option, value)
                    if "does match certificate" not in result:
                        raise RuntimeError(f"endpoint SAN missing: {value}")
        if service.startswith("opensearch_node_") or service == "opensearch_admin_client":
            subject = run("openssl", "x509", "-in", str(folder / "cert.crt"),
                          "-noout", "-subject", "-nameopt", "RFC2253").strip().removeprefix("subject=")
            permitted = admin_dns if service == "opensearch_admin_client" else node_dns
            if subject not in permitted:
                raise RuntimeError(f"certificate DN missing from OpenSearch Security configuration: {service}: {subject}")


def atomic_copy(source: Path, destination: Path, mode: int) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name("." + destination.name + f".tmp-{os.getpid()}")
    shutil.copy2(source, temporary)
    temporary.chmod(mode)
    os.replace(temporary, destination)


def atomic_text(value: str, destination: Path, mode: int = 0o644) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name("." + destination.name + f".tmp-{os.getpid()}")
    temporary.write_text(value, encoding="ascii")
    temporary.chmod(mode)
    os.replace(temporary, destination)


def snapshot(phase: str) -> Path:
    BACKUPS.mkdir(parents=True, exist_ok=True, mode=0o700)
    BACKUPS.chmod(0o700)
    backup = BACKUPS / (dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + phase)
    backup.mkdir(parents=True, exist_ok=False, mode=0o700)
    backup.chmod(0o700)
    shutil.copytree(PKI, backup / "pki")
    shutil.copytree(PROXY, backup / "endpoint-proxy")
    if STATE.is_file():
        shutil.copy2(STATE, backup / "state.json")
    return backup


def restore(backup: Path) -> None:
    if not (backup / "pki").is_dir() or not (backup / "endpoint-proxy").is_dir():
        raise RuntimeError("incomplete rollback snapshot; active files unchanged")
    for subdir, target in (("pki", PKI), ("endpoint-proxy", PROXY)):
        for source in (backup / subdir).rglob("*"):
            if source.is_file():
                destination = target / source.relative_to(backup / subdir)
                atomic_copy(source, destination, source.stat().st_mode & 0o777)
    if (backup / "state.json").is_file():
        atomic_copy(backup / "state.json", STATE, 0o600)
    else:
        STATE.unlink(missing_ok=True)
    compose("up", "-d", "--force-recreate", *NODES, "opensearch-endpoint")
    health()


def state_phase() -> str:
    if not STATE.is_file():
        return "legacy"
    return json.loads(STATE.read_text(encoding="utf-8"))["phase"]


def set_phase(phase: str, backup: Path) -> None:
    atomic_text(json.dumps({"phase": phase, "backup": str(backup),
        "changed_at": dt.datetime.now(dt.timezone.utc).isoformat()}, indent=2) + "\n", STATE, 0o600)


def restart_node(node: str) -> None:
    compose("up", "-d", "--no-deps", "--force-recreate", node)
    health()
    print(f"PASS {node}: three-node cluster green", flush=True)


def restart_proxy() -> None:
    compose("up", "-d", "--no-deps", "--force-recreate", "opensearch-endpoint")
    health()
    print("PASS opensearch-endpoint: cluster green", flush=True)


def render_proxy() -> None:
    run(str(ROOT / "dev/scripts/opensearch-cluster/render-endpoint-proxy-config.sh"))


def trust_phase() -> None:
    new = (AGENT / "service-ca.crt").read_text(encoding="ascii")
    old = (PKI / "ca/ca.crt").read_text(encoding="ascii")
    dual = old.rstrip() + "\n" + new
    for node in NODES:
        atomic_text(dual, PKI / "nodes" / node / "ca.crt")
    atomic_text(dual, PKI / "client-trust/oculox-opensearch-ca.crt")
    render_proxy()
    restart_proxy()
    for node in NODES:
        restart_node(node)


def leaf_phase() -> None:
    for number, node in enumerate(NODES, 1):
        source = stage(f"opensearch_node_{number}")
        destination = PKI / "nodes" / node
        atomic_copy(source / "cert.crt", destination / "node.crt", 0o644)
        atomic_copy(source / "key.key", destination / "node.key", 0o600)
        restart_node(node)
    for service, folder, prefix in (("opensearch_admin_client", "admin", "admin"),
                                    ("opensearch_endpoint", "endpoint", "endpoint")):
        source = stage(service)
        destination = PKI / folder
        atomic_copy(source / "cert.crt", destination / f"{prefix}.crt", 0o644)
        atomic_copy(source / "key.key", destination / f"{prefix}.key", 0o600)
        atomic_copy(source / "ca.crt", destination / "ca.crt", 0o644)
    render_proxy()
    restart_proxy()


def retire_phase() -> None:
    new = AGENT / "service-ca.crt"
    atomic_copy(new, PKI / "ca/ca.crt", 0o644)
    atomic_copy(new, PKI / "client-trust/oculox-opensearch-ca.crt", 0o644)
    for node in NODES:
        atomic_copy(new, PKI / "nodes" / node / "ca.crt", 0o644)
    render_proxy()
    restart_proxy()
    for node in NODES:
        restart_node(node)
    old_key = PKI / "ca/ca.key"
    if old_key.exists():
        archive = BACKUPS / "retired-local-ca.key"
        if archive.exists():
            raise RuntimeError("retired CA key archive already exists")
        os.replace(old_key, archive)
        archive.chmod(0o600)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("status", "trust", "leaf", "retire", "rotate", "rollback"))
    parser.add_argument("--backup", type=Path, help="backup directory for explicit rollback")
    parser.add_argument("--check", action="store_true", help="validate staged material without replacement")
    parser.add_argument("--staging-root", type=Path, help="directory containing the five staged service directories")
    args = parser.parse_args()
    if args.phase == "status":
        print(f"phase={state_phase()}")
        health(30)
        print("cluster=green nodes=3")
        return
    if args.phase == "rollback":
        if not args.backup or not args.backup.resolve().is_relative_to(BACKUPS.resolve()):
            raise RuntimeError("--backup must point below pki-migration-backups")
    lock = (GENERATED / ".pki-operation.lock").open("a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        perform_operation(args)
    finally:
        lock.close()


def perform_operation(args: argparse.Namespace) -> None:
    STAGED.clear()
    if args.phase == "rollback":
        restore(args.backup.resolve())
        print("rollback=PASS")
        return
    if args.staging_root:
        STAGED.update({service: args.staging_root.resolve() / service for service in SERVICES})
    if args.phase != "rotate":
        expected = {"trust": "legacy", "leaf": "trust", "retire": "leaf"}[args.phase]
        if state_phase() != expected:
            raise RuntimeError(f"phase {args.phase} requires state {expected}; current={state_phase()}")
    else:
        # Routine renewal preserves the issuer; a CA change needs the trust phases.
        for number, node in enumerate(NODES, 1):
            run("openssl", "verify", "-CAfile", str(AGENT / "service-ca.crt"),
                str(PKI / "nodes" / node / "node.crt"))
        if (PKI / "ca/ca.key").exists() or state_phase() in {"trust", "leaf"}:
            raise RuntimeError("finish the EJBCA CA migration before routine renewal")
    compose("config", "--quiet")
    verify_stages()
    health(30)
    if args.check:
        print(f"phase={args.phase} preflight=PASS; active files unchanged")
        return
    backup = snapshot(args.phase)
    print(f"Backup: {backup}", flush=True)
    try:
        {"trust": trust_phase, "leaf": leaf_phase, "retire": retire_phase, "rotate": leaf_phase}[args.phase]()
        set_phase("retire" if args.phase == "rotate" else args.phase, backup)
    except Exception:
        print("Migration failed; restoring prior active material", file=sys.stderr, flush=True)
        for node in NODES:
            result = subprocess.run(["docker", "compose", "--env-file", str(ENV), "-f", str(COMPOSE),
                                     "logs", "--no-color", "--tail", "400", node],
                                    capture_output=True, text=True, check=False)
            (backup / f"{node}.failure.log").write_text(result.stdout + result.stderr, encoding="utf-8")
        restore(backup)
        raise
    print(f"phase={args.phase} result=PASS", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
