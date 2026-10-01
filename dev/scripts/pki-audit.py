#!/usr/bin/env python3
"""Audit PKI material declared in dev/ejbca/pki-manifest.yml.

This tool is intentionally read-only. It never generates, replaces, removes or
reloads certificate material. It exists to give Oculox a reliable inventory
for installation, renewal and incident diagnosis.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as exc:  # pragma: no cover - exercised on incomplete hosts
    raise SystemExit("PyYAML est requis pour lire dev/ejbca/pki-manifest.yml") from exc


PROJECT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = PROJECT_DIR / "dev/ejbca/pki-manifest.yml"
SECONDS_PER_DAY = 86400


@dataclass
class Check:
    name: str
    status: str
    detail: str


@dataclass
class CertificateAudit:
    name: str
    service: str
    profile: str
    cert_type: str
    required: bool
    cert: str
    key: str | None = None
    ca: str | None = None
    status: str = "UNKNOWN"
    subject: str | None = None
    issuer: str | None = None
    serial: str | None = None
    not_before: str | None = None
    not_after: str | None = None
    expires_in_days: int | None = None
    san: list[str] = field(default_factory=list)
    eku: list[str] = field(default_factory=list)
    checks: list[Check] = field(default_factory=list)


def run(command: list[str], *, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def relpath(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return str(path.relative_to(PROJECT_DIR))
    except ValueError:
        return str(path)


def resolve_path(value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value)
    if path.is_absolute():
        return path
    return PROJECT_DIR / path


def load_manifest(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise SystemExit(f"Manifest PKI absent : {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("certificates"), dict):
        raise SystemExit(f"Manifest PKI invalide : {path}")
    return data


def parse_env_value(reference: str) -> str | None:
    if ":" not in reference:
        return reference
    file_part, key = reference.split(":", 1)
    env_path = resolve_path(file_part)
    if env_path is None or not env_path.is_file():
        return None
    pattern = re.compile(rf"^{re.escape(key)}=(.*)$")
    for line in env_path.read_text(encoding="utf-8").splitlines():
        match = pattern.match(line.strip())
        if match:
            return match.group(1).strip().strip('"').strip("'")
    return None


def normalize_san(value: str) -> str:
    value = value.strip()
    if value.startswith("DNS:"):
        return value[4:]
    if value.startswith("IP Address:"):
        return value[11:]
    if value.startswith("IP:"):
        return value[3:]
    return value


def extract_san(text: str) -> list[str]:
    lines = text.splitlines()
    values: list[str] = []
    capture_next = False
    for line in lines:
        stripped = line.strip()
        if "Subject Alternative Name" in stripped:
            capture_next = True
            continue
        if capture_next:
            for item in stripped.split(","):
                item = normalize_san(item)
                if item:
                    values.append(item)
            break
    return sorted(set(values))


def extract_eku(text: str) -> list[str]:
    values: list[str] = []
    capture_next = False
    for line in text.splitlines():
        stripped = line.strip()
        if "Extended Key Usage" in stripped:
            capture_next = True
            continue
        if capture_next:
            values.extend(item.strip() for item in stripped.split(",") if item.strip())
            break
    normalized: list[str] = []
    mapping = {
        "TLS Web Server Authentication": "serverAuth",
        "TLS Web Client Authentication": "clientAuth",
    }
    for value in values:
        normalized.append(mapping.get(value, value))
    return sorted(set(normalized))


def parse_date(value: str) -> dt.datetime:
    return dt.datetime.strptime(value, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=dt.timezone.utc)


def cert_pubkey_hash(cert_path: Path) -> str | None:
    pubkey = run(["openssl", "x509", "-in", str(cert_path), "-pubkey", "-noout"])
    if pubkey.returncode != 0:
        return None
    normalized = run(["openssl", "pkey", "-pubin", "-pubout"], input_text=pubkey.stdout)
    if normalized.returncode != 0:
        return None
    return hashlib.sha256(normalized.stdout.encode("utf-8")).hexdigest()


def key_pubkey_hash(key_path: Path) -> str | None:
    normalized = run(["openssl", "pkey", "-in", str(key_path), "-pubout"])
    if normalized.returncode != 0:
        return None
    return hashlib.sha256(normalized.stdout.encode("utf-8")).hexdigest()


def set_status(checks: list[Check], required: bool) -> str:
    statuses = {check.status for check in checks}
    if "FAIL" in statuses:
        return "FAIL"
    if "MISSING" in statuses:
        return "FAIL" if required else "SKIP"
    if "WARN" in statuses:
        return "WARN"
    if "INFO" in statuses and len(statuses) == 1:
        return "INFO"
    return "OK"


def audit_certificate(
    name: str,
    spec: dict[str, Any],
    warning_days: int,
    critical_days: int,
) -> CertificateAudit:
    cert_path = resolve_path(spec.get("cert"))
    key_path = resolve_path(spec.get("key"))
    ca_path = resolve_path(spec.get("ca"))
    required = bool(spec.get("required", True))
    audit = CertificateAudit(
        name=name,
        service=str(spec.get("service", "")),
        profile=str(spec.get("profile", "")),
        cert_type=str(spec.get("type", "")),
        required=required,
        cert=relpath(cert_path) or "",
        key=relpath(key_path),
        ca=relpath(ca_path),
    )

    if cert_path is None or not cert_path.is_file():
        audit.checks.append(Check("cert_present", "MISSING", f"certificat absent : {audit.cert}"))
        audit.status = set_status(audit.checks, required)
        return audit
    audit.checks.append(Check("cert_present", "OK", f"certificat present : {audit.cert}"))

    x509 = run(["openssl", "x509", "-in", str(cert_path), "-noout", "-subject", "-issuer", "-serial", "-dates"])
    if x509.returncode != 0:
        audit.checks.append(Check("cert_parse", "FAIL", x509.stderr.strip() or "certificat illisible"))
        audit.status = set_status(audit.checks, required)
        return audit
    audit.checks.append(Check("cert_parse", "OK", "certificat lisible par openssl"))

    for line in x509.stdout.splitlines():
        if line.startswith("subject="):
            audit.subject = line.removeprefix("subject=").strip()
        elif line.startswith("issuer="):
            audit.issuer = line.removeprefix("issuer=").strip()
        elif line.startswith("serial="):
            audit.serial = line.removeprefix("serial=").strip()
        elif line.startswith("notBefore="):
            audit.not_before = line.removeprefix("notBefore=").strip()
        elif line.startswith("notAfter="):
            audit.not_after = line.removeprefix("notAfter=").strip()

    if audit.not_after:
        try:
            expiry = parse_date(audit.not_after)
            now = dt.datetime.now(dt.timezone.utc)
            audit.expires_in_days = int((expiry - now).total_seconds() // SECONDS_PER_DAY)
            if audit.expires_in_days < 0:
                audit.checks.append(Check("expiry", "FAIL", f"certificat expire depuis {-audit.expires_in_days} jour(s)"))
            elif audit.expires_in_days < critical_days:
                audit.checks.append(Check("expiry", "FAIL", f"expiration critique dans {audit.expires_in_days} jour(s)"))
            elif audit.expires_in_days < warning_days:
                audit.checks.append(Check("expiry", "WARN", f"expiration proche dans {audit.expires_in_days} jour(s)"))
            else:
                audit.checks.append(Check("expiry", "OK", f"expire dans {audit.expires_in_days} jour(s)"))
        except ValueError as exc:
            audit.checks.append(Check("expiry", "WARN", f"date d'expiration non analysee : {exc}"))

    san_result = run(["openssl", "x509", "-in", str(cert_path), "-noout", "-ext", "subjectAltName"])
    if san_result.returncode == 0:
        audit.san = extract_san(san_result.stdout)

    eku_result = run(["openssl", "x509", "-in", str(cert_path), "-noout", "-ext", "extendedKeyUsage"])
    if eku_result.returncode == 0:
        audit.eku = extract_eku(eku_result.stdout)

    private_key_managed_by = str(spec.get("private_key_managed_by", "")).strip()
    if key_path is not None and private_key_managed_by:
        audit.checks.append(
            Check(
                "key_external",
                "INFO",
                f"cle privee geree par {private_key_managed_by}; correspondance locale non exigee",
            )
        )
    elif key_path is not None:
        if not key_path.is_file():
            audit.checks.append(Check("key_present", "MISSING", f"cle absente : {audit.key}"))
        else:
            audit.checks.append(Check("key_present", "OK", f"cle presente : {audit.key}"))
            cert_hash = cert_pubkey_hash(cert_path)
            key_hash = key_pubkey_hash(key_path)
            if cert_hash and key_hash and cert_hash == key_hash:
                audit.checks.append(Check("key_match", "OK", "la cle privee correspond au certificat"))
            else:
                audit.checks.append(Check("key_match", "FAIL", "la cle privee ne correspond pas au certificat"))

    if ca_path is not None:
        if not ca_path.is_file():
            audit.checks.append(Check("ca_present", "MISSING", f"CA absente : {audit.ca}"))
        else:
            audit.checks.append(Check("ca_present", "OK", f"CA presente : {audit.ca}"))
            verify = run(["openssl", "verify", "-CAfile", str(ca_path), str(cert_path)])
            if verify.returncode == 0:
                audit.checks.append(Check("chain", "OK", "chaine valide avec la CA declaree"))
            else:
                audit.checks.append(Check("chain", "FAIL", verify.stderr.strip() or verify.stdout.strip()))

    if spec.get("expected_ca"):
        text = run(["openssl", "x509", "-in", str(cert_path), "-noout", "-text"])
        if text.returncode == 0 and "CA:TRUE" in text.stdout:
            audit.checks.append(Check("ca_basic_constraint", "OK", "Basic Constraints CA:TRUE present"))
        else:
            audit.checks.append(Check("ca_basic_constraint", "FAIL", "Basic Constraints CA:TRUE absent"))

    expected_usage = [str(item) for item in spec.get("expected_usage", [])]
    for usage in expected_usage:
        if usage in audit.eku:
            audit.checks.append(Check(f"eku_{usage}", "OK", f"EKU {usage} present"))
        else:
            audit.checks.append(Check(f"eku_{usage}", "FAIL", f"EKU {usage} absent"))

    san_required = [str(item) for item in spec.get("san_required", [])]
    for reference in spec.get("san_optional_from", []):
        value = parse_env_value(str(reference))
        if value:
            san_required.append(value)
    for reference in spec.get("san_required_from", []):
        value = parse_env_value(str(reference))
        if value:
            san_required.append(value)
        else:
            level = "WARN" if required else "INFO"
            audit.checks.append(Check("san_reference", level, f"valeur SAN runtime introuvable : {reference}"))

    for san in san_required:
        if san in audit.san:
            audit.checks.append(Check(f"san_{san}", "OK", f"SAN present : {san}"))
        else:
            audit.checks.append(Check(f"san_{san}", "FAIL", f"SAN absent : {san}"))

    audit.status = set_status(audit.checks, required)
    return audit


def audit_all(manifest_path: Path) -> tuple[dict[str, Any], list[CertificateAudit]]:
    manifest = load_manifest(manifest_path)
    defaults = manifest.get("defaults", {})
    warning_days = int(defaults.get("warning_days", 60))
    critical_days = int(defaults.get("critical_days", 30))
    cluster = (PROJECT_DIR / "dev/generated/opensearch-cluster/cluster.env").is_file()
    role = parse_env_value("dev/generated/deployment.env:OCULOX_ROLE")
    collector = role == "hedgehog"
    cluster_only = cluster and role not in {"principal", "hedgehog"}
    audits = []
    for name, original in manifest["certificates"].items():
        spec = dict(original)
        if cluster_only and (spec.get("zone") != "opensearch" or name == "opensearch_remote_trust"):
            continue
        if spec.get("zone") == "opensearch" and not cluster and name != "opensearch_remote_trust":
            continue
        if collector and name in {"web_server", "web_ca", "logstash_server", "ejbca_api_server", "enrollment_agent"}:
            continue
        if cluster and spec.get("zone") == "opensearch" and name != "opensearch_remote_trust":
            spec["required"] = True
        if name == "opensearch_remote_trust" and parse_env_value("config/opensearch.env:OPENSEARCH_URL"):
            spec["required"] = True
        if name == "filebeat_client" and not collector:
            spec["san_required_from"] = []
        audits.append(audit_certificate(name, spec, warning_days, critical_days))
    agent = PROJECT_DIR / "dev/generated/pki/remote-agent"
    if (agent / "config.json").is_file():
        config = json.loads((agent / "config.json").read_text(encoding="utf-8"))
        spec = {"service": "ejbca-enrollment", "profile": "oculox-enrollment-agent", "type": "client", "required": True,
                "cert": str(agent / "agent.crt"), "key": str(agent / "agent.key"), "ca": str(agent / "agent-ca.crt"),
                "expected_usage": ["clientAuth"], "san_required": [f"oculox-{config['role']}-{config['identity']}"]}
        audits.append(audit_certificate("remote_enrollment_agent", spec, warning_days, critical_days))
    return manifest, audits


def overall_status(audits: list[CertificateAudit]) -> str:
    required = [audit for audit in audits if audit.required]
    if any(audit.status == "FAIL" for audit in required):
        return "FAIL"
    if any(audit.status == "WARN" for audit in required):
        return "WARN"
    return "OK"


def as_dict(audit: CertificateAudit) -> dict[str, Any]:
    return {
        "name": audit.name,
        "service": audit.service,
        "profile": audit.profile,
        "type": audit.cert_type,
        "required": audit.required,
        "cert": audit.cert,
        "key": audit.key,
        "ca": audit.ca,
        "status": audit.status,
        "subject": audit.subject,
        "issuer": audit.issuer,
        "serial": audit.serial,
        "not_before": audit.not_before,
        "not_after": audit.not_after,
        "expires_in_days": audit.expires_in_days,
        "san": audit.san,
        "eku": audit.eku,
        "checks": [check.__dict__ for check in audit.checks],
    }


def print_audit(audits: list[CertificateAudit]) -> None:
    print("=== Audit PKI Oculox ===")
    for audit in audits:
        required = "required" if audit.required else "optional"
        print(f"\n[{audit.status}] {audit.name} ({required})")
        print(f"  service : {audit.service}")
        print(f"  profile : {audit.profile}")
        print(f"  type    : {audit.cert_type}")
        print(f"  cert    : {audit.cert}")
        if audit.key:
            print(f"  key     : {audit.key}")
        if audit.ca:
            print(f"  ca      : {audit.ca}")
        if audit.subject:
            print(f"  subject : {audit.subject}")
        if audit.issuer:
            print(f"  issuer  : {audit.issuer}")
        if audit.expires_in_days is not None:
            print(f"  expiry  : {audit.expires_in_days} day(s)")
        if audit.san:
            print(f"  san     : {', '.join(audit.san)}")
        if audit.eku:
            print(f"  eku     : {', '.join(audit.eku)}")
        for check in audit.checks:
            print(f"    - {check.status:<7} {check.name}: {check.detail}")


def print_status(audits: list[CertificateAudit]) -> None:
    print("=== Statut PKI Oculox ===")
    for audit in audits:
        required = "" if audit.required else " (optional)"
        expiry = ""
        if audit.expires_in_days is not None:
            expiry = f" expires_in={audit.expires_in_days}d"
        print(f"{audit.name:<30} {audit.status:<6} service={audit.service}{expiry}{required}")


def print_expiry(audits: list[CertificateAudit]) -> None:
    print("=== Expiration PKI Oculox ===")
    for audit in sorted(audits, key=lambda item: 999999 if item.expires_in_days is None else item.expires_in_days):
        value = "unknown" if audit.expires_in_days is None else f"{audit.expires_in_days} day(s)"
        print(f"{audit.name:<30} {audit.status:<6} {value:<15} {audit.cert}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit read-only des certificats Oculox")
    parser.add_argument("command", choices=("audit", "status", "expiry"))
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST), help="chemin du manifeste PKI")
    parser.add_argument("--json", action="store_true", help="emettre un rapport JSON")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    _, audits = audit_all(Path(args.manifest))

    if args.json:
        print(json.dumps({"overall_status": overall_status(audits), "certificates": [as_dict(audit) for audit in audits]}, indent=2))
    elif args.command == "audit":
        print_audit(audits)
    elif args.command == "status":
        print_status(audits)
    elif args.command == "expiry":
        print_expiry(audits)

    return 0 if overall_status(audits) in {"OK", "WARN"} else 1


if __name__ == "__main__":
    sys.exit(main())
