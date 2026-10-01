#!/usr/bin/env python3
"""EJBCA and customer PKI lifecycle integration for Oculox.

The default behaviour is deliberately non-disruptive: enroll and renew create
validated staging material under dev/ejbca/generated/enrollments, but they do
not replace active certificates unless --install is explicitly provided.
"""

from __future__ import annotations

import argparse
import datetime as dt
import ipaddress
import importlib.util
import json
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import time
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    raise SystemExit("PyYAML est requis pour lire les manifestes PKI") from exc


PROJECT_DIR = Path(__file__).resolve().parents[3]
MANIFEST_PATH = PROJECT_DIR / "dev/ejbca/pki-manifest.yml"
CA_PLAN_PATH = PROJECT_DIR / "dev/ejbca/profiles/ca-plan.yml"
GENERATED_DIR = PROJECT_DIR / "dev/ejbca/generated"
ENROLLMENTS_DIR = GENERATED_DIR / "enrollments"
BACKUPS_DIR = GENERATED_DIR / "backups"
EJBCA_CONTAINER = "oculox-ejbca"
EJBCA_CLI = "/opt/keyfactor/bin/ejbca.sh"


@dataclass
class Result:
    status: str
    detail: str


class LifecycleError(RuntimeError):
    pass


def run(command: list[str], *, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def require_ok(result: subprocess.CompletedProcess[str], action: str) -> str:
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"code retour {result.returncode}"
        raise LifecycleError(f"{action}: {detail}")
    return result.stdout


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise LifecycleError(f"fichier absent: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise LifecycleError(f"YAML invalide: {path}")
    return data


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_DIR))
    except ValueError:
        return str(path)


def resolve(path_value: str | None) -> Path | None:
    if not path_value:
        return None
    path = Path(path_value)
    return path if path.is_absolute() else PROJECT_DIR / path


def parse_env_reference(reference: str) -> str | None:
    if ":" not in reference:
        return reference
    file_name, key = reference.split(":", 1)
    path = resolve(file_name)
    if path is None or not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def manifest_entries(manifest: dict[str, Any], service: str | None) -> dict[str, dict[str, Any]]:
    entries = manifest.get("certificates")
    if not isinstance(entries, dict):
        raise LifecycleError("dev/ejbca/pki-manifest.yml ne contient pas certificates")
    if service:
        if service not in entries:
            raise LifecycleError(f"entrée PKI inconnue: {service}")
        return {service: entries[service]}
    return {name: spec for name, spec in entries.items() if bool(spec.get("required", True))}


def profile_plan(ca_plan: dict[str, Any], profile: str) -> dict[str, Any]:
    profiles = ca_plan.get("certificate_profiles", {})
    if profile not in profiles:
        raise LifecycleError(f"profil absent du plan CA: {profile}")
    plan = profiles[profile]
    ca_key = plan.get("issuer")
    cas = ca_plan.get("certificate_authorities", {})
    if ca_key not in cas:
        raise LifecycleError(f"issuer absent du plan CA pour {profile}: {ca_key}")
    issuer = dict(cas[ca_key])
    plan = dict(plan)
    plan["issuer_display_name"] = issuer["display_name"]
    return plan


def ca_display_for_manifest_ca(profile: str, ca_plan: dict[str, Any]) -> str:
    mapping = {
        "oculox-web-ca": "oculox_web_ca",
        "oculox-internal-services-ca": "oculox_internal_services_ca",
        "oculox-opensearch-ca": "oculox_opensearch_ca",
    }
    ca_key = mapping.get(profile)
    if not ca_key:
        raise LifecycleError(f"profil CA non mappe vers une autorite EJBCA: {profile}")
    cas = ca_plan.get("certificate_authorities", {})
    if ca_key not in cas:
        raise LifecycleError(f"autorite absente du plan CA: {ca_key}")
    return str(cas[ca_key]["display_name"])


def san_values(spec: dict[str, Any]) -> list[str]:
    values = [str(item) for item in spec.get("san_required", [])]
    for reference in [*spec.get("san_required_from", []), *spec.get("san_optional_from", [])]:
        value = parse_env_reference(str(reference))
        if value:
            values.append(value)
    return sorted(set(values))


def ejbca_altname(values: list[str]) -> str:
    parts: list[str] = []
    for value in values:
        try:
            ipaddress.ip_address(value)
            parts.append(f"ipaddress={value}")
        except ValueError:
            parts.append(f"dNSName={value}")
    return ",".join(parts)


def ejbca_cert_profile(cert_type: str) -> str:
    if cert_type == "client":
        return "ENDUSER"
    if cert_type in {"server", "server-client"}:
        return "SERVER"
    raise LifecycleError(f"EJBCA ne signe pas directement le type {cert_type}")


def ensure_ejbca_running() -> None:
    result = run(["docker", "exec", EJBCA_CONTAINER, "curl", "-kfsS", "https://127.0.0.1:8443/ejbca/publicweb/healthcheck/ejbcahealth"])
    require_ok(result, "EJBCA ne répond pas")


def ejbca(*args: str) -> str:
    return require_ok(run(["docker", "exec", EJBCA_CONTAINER, EJBCA_CLI, *args]), "commande EJBCA")


def docker_exec(*args: str) -> str:
    return require_ok(run(["docker", "exec", EJBCA_CONTAINER, *args]), "docker exec")


def docker_cp_from(remote: str, local: Path) -> None:
    local.parent.mkdir(parents=True, exist_ok=True)
    require_ok(run(["docker", "cp", f"{EJBCA_CONTAINER}:{remote}", str(local)]), "docker cp")


def export_ca(ca_name: str, destination: Path) -> None:
    remote = f"/tmp/oculox-ca-{secrets.token_hex(8)}.crt"
    ejbca("ca", "getcacert", ca_name, remote)
    docker_cp_from(remote, destination)
    docker_exec("rm", "-f", remote)
    normalized = destination.with_suffix(".normalized.crt")
    require_ok(run(["openssl", "x509", "-in", str(destination), "-out", str(normalized)]), "normalize CA PEM")
    os.replace(normalized, destination)
    destination.chmod(0o644)


def matching_end_entities(subject_dn: str) -> list[tuple[str, str]]:
    output = ejbca("ra", "listendentities", "00")
    matches: list[tuple[str, str]] = []
    pattern = re.compile(r"End Entity:\s*([^,]+),\s*\"([^\"]+)\",\s*\"[^\"]*\",\s*[^,]*,\s*([0-9]+),")
    for line in output.splitlines():
        match = pattern.search(line)
        if match and match.group(2) == subject_dn:
            matches.append((match.group(1).strip(), match.group(3).strip()))
    return matches


def revoke_matching_subjects(subject_dn: str) -> None:
    for username, status in matching_end_entities(subject_dn):
        if status in {"50", "60"}:
            continue
        ejbca("ra", "revokeendentity", username, "4")


def reusable_end_entity(subject_dn: str) -> str | None:
    matches = matching_end_entities(subject_dn)
    for username, status in matches:
        if status == "40":
            return username
    return matches[0][0] if matches else None


def export_ca_bundle(issuer_name: str, destination: Path) -> None:
    """Write a verification bundle for an issued certificate.

    EJBCA service certificates are signed by an intermediate CA. OpenSSL needs
    the issuer and the root in the trust bundle during staging validation.
    """
    issuer_file = destination.with_name(f"{destination.stem}.issuer.crt")
    root_file = destination.with_name(f"{destination.stem}.root.crt")
    export_ca(issuer_name, issuer_file)
    if issuer_name == "Oculox Root CA":
        destination.write_text(issuer_file.read_text(encoding="utf-8"), encoding="utf-8")
    else:
        export_ca("Oculox Root CA", root_file)
        destination.write_text(
            issuer_file.read_text(encoding="utf-8") + root_file.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    destination.chmod(0o644)


def cert_subject(name: str, spec: dict[str, Any], unique_suffix: str | None = None) -> str:
    explicit = spec.get("subject_dn")
    if explicit:
        return str(explicit)
    cn = name.replace("_", "-")
    if unique_suffix:
        cn = f"{cn}-{unique_suffix}"
    zone = str(spec.get("zone", "services")).replace(",", "")
    return f"CN={cn},OU=Oculox {zone},O=Oculox,C=SN"


def openssl_extract_p12(p12: Path, password: str, cert: Path, key: Path) -> None:
    require_ok(
        run(["openssl", "pkcs12", "-in", str(p12), "-clcerts", "-nokeys", "-out", str(cert), "-passin", f"pass:{password}"]),
        "extraction certificat P12",
    )
    require_ok(
        run(["openssl", "pkcs12", "-in", str(p12), "-nocerts", "-nodes", "-out", str(key), "-passin", f"pass:{password}"]),
        "extraction clé P12",
    )
    normalized_key = key.with_name(f".{key.name}.normalized-{os.getpid()}")
    require_ok(
        run(["openssl", "pkey", "-in", str(key), "-out", str(normalized_key)]),
        "normalisation clé privée",
    )
    os.replace(normalized_key, key)
    cert.chmod(0o644)
    key.chmod(0o600)


def validate_material(name: str, spec: dict[str, Any], stage_dir: Path) -> list[Result]:
    results: list[Result] = []
    cert = stage_dir / "cert.crt"
    key = stage_dir / "key.key"
    ca = stage_dir / "ca.crt"
    cert_type = str(spec.get("type", ""))

    if cert_type == "ca":
        target = cert if cert.is_file() else ca
        parsed = run(["openssl", "x509", "-in", str(target), "-noout", "-text"])
        if parsed.returncode == 0 and "CA:TRUE" in parsed.stdout:
            results.append(Result("OK", "certificat CA valide"))
        else:
            results.append(Result("FAIL", "certificat CA absent ou sans Basic Constraints CA:TRUE"))
        return results

    for path, label in ((cert, "certificat"), (key, "clé privée"), (ca, "CA")):
        if path.is_file():
            results.append(Result("OK", f"{label} présent: {path.name}"))
        else:
            results.append(Result("FAIL", f"{label} absent: {path}"))
    if any(item.status == "FAIL" for item in results):
        return results

    cert_hash = require_ok(run(["openssl", "x509", "-in", str(cert), "-pubkey", "-noout"]), "lecture clé publique certificat")
    cert_pub = require_ok(run(["openssl", "pkey", "-pubin", "-pubout"], input_text=cert_hash), "normalisation clé publique certificat")
    key_pub = require_ok(run(["openssl", "pkey", "-in", str(key), "-pubout"]), "lecture clé publique privée")
    if cert_pub == key_pub:
        results.append(Result("OK", "la clé privée correspond au certificat"))
    else:
        results.append(Result("FAIL", "la clé privée ne correspond pas au certificat"))

    verify = run(["openssl", "verify", "-CAfile", str(ca), str(cert)])
    if verify.returncode == 0:
        results.append(Result("OK", "chaîne validée avec la CA déclarée"))
    else:
        results.append(Result("FAIL", verify.stderr.strip() or verify.stdout.strip()))

    text = require_ok(run(["openssl", "x509", "-in", str(cert), "-noout", "-text"]), "lecture certificat")
    for usage in spec.get("expected_usage", []):
        if usage not in {"serverAuth", "clientAuth"}:
            results.append(Result("FAIL", f"EKU non pris en charge: {usage}"))
            continue
        needle = "TLS Web Server Authentication" if usage == "serverAuth" else "TLS Web Client Authentication"
        if needle in text:
            results.append(Result("OK", f"EKU {usage} présent"))
        else:
            results.append(Result("FAIL", f"EKU {usage} absent"))
    san_text = require_ok(run(["openssl", "x509", "-in", str(cert), "-noout", "-ext", "subjectAltName"]), "lecture SAN")
    actual_sans = set()
    for kind, value in re.findall(r"(DNS|IP Address):([^,\s]+)", san_text):
        actual_sans.add((kind, str(ipaddress.ip_address(value)) if kind == "IP Address" else value.lower()))
    for san in san_values(spec):
        try:
            expected = ("IP Address", str(ipaddress.ip_address(san)))
        except ValueError:
            expected = ("DNS", san.lower())
        if expected in actual_sans:
            results.append(Result("OK", f"SAN présent: {san}"))
        else:
            results.append(Result("FAIL", f"SAN absent: {san}"))
    return results


def write_metadata(stage_dir: Path, data: dict[str, Any]) -> None:
    (stage_dir / "metadata.json").write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    (stage_dir / "README.txt").write_text(
        "Materiel PKI genere en staging. Aucun certificat actif n'est remplace tant que --install n'est pas utilise.\n",
        encoding="utf-8",
    )


def enroll_one(name: str, spec: dict[str, Any], plan: dict[str, Any], root: Path, force: bool) -> Path:
    stage_dir = root / name
    stage_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    stage_dir.chmod(0o700)
    cert_type = str(spec.get("type", ""))
    issuer = str(plan["issuer_display_name"])

    if cert_type == "ca":
        export_ca(issuer, stage_dir / "cert.crt")
        export_ca_bundle(issuer, stage_dir / "ca.crt")
        write_metadata(stage_dir, {"name": name, "type": cert_type, "issuer": issuer, "provider": "ejbca"})
        return stage_dir

    subject = cert_subject(name, spec, None)
    username = f"oculox-{name.replace('_', '-')}-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(3)}"
    subject_suffix = username.rsplit("-", 2)[-2] + "-" + username.rsplit("-", 1)[-1]
    password = secrets.token_urlsafe(24)
    remote_dir = f"/tmp/oculox-enroll-{username}"
    key_path = stage_dir / "key.key"
    csr_path = stage_dir / "request.csr"
    # Exclusive creation prevents overwriting a staged key during retries.
    descriptor = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(descriptor)
    require_ok(run(["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:3072", "-out", str(key_path)]), "generation locale de la cle")
    # The authoritative subject and SAN are the server-side end entity values.
    require_ok(run(["openssl", "req", "-new", "-sha256", "-key", str(key_path), "-subj", f"/CN={username}", "-out", str(csr_path)]), "generation locale de la CSR")

    args = [
        "ra",
        "addendentity",
        "--username",
        username,
        "--dn",
        subject if spec.get("subject_dn") else cert_subject(name, spec, subject_suffix),
        "--caname",
        issuer,
        "--type",
        "1",
        "--token",
        "USERGENERATED",
        "--password",
        password,
        "--certprofile",
        str(spec["profile"]),
        "--eeprofile",
        str(spec["profile"]) + "-enroll-v3",
    ]
    altname = ejbca_altname(san_values(spec))
    if altname:
        args.extend(["--altname", altname])
    ejbca(*args)
    ejbca("ra", "setpwd", username, "--password", password)
    ejbca("ra", "setendentitystatus", username, "10")
    docker_exec("mkdir", "-p", remote_dir)
    try:
        require_ok(run(["docker", "cp", str(csr_path), f"{EJBCA_CONTAINER}:{remote_dir}/request.csr"]), "transfert de la CSR publique")
        ejbca("createcert", "--username", username, "--password", password, "-c", f"{remote_dir}/request.csr", "-f", f"{remote_dir}/cert.crt")
        docker_cp_from(f"{remote_dir}/cert.crt", stage_dir / "cert.crt")
    finally:
        docker_exec("rm", "-rf", remote_dir)
    export_ca_bundle(issuer, stage_dir / "ca.crt")
    (stage_dir / "cert.crt").chmod(0o644)
    write_metadata(
        stage_dir,
        {
            "name": name,
            "type": cert_type,
            "issuer": issuer,
            "provider": "ejbca",
            "key_origin": "local",
            "issuance_transport": "local-docker-cli",
            "ejbca_username": username,
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "force": force,
        },
    )
    return stage_dir


def atomic_copy(source: Path, destination: Path, mode: int) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_name(f".{destination.name}.tmp-{os.getpid()}")
    shutil.copy2(source, tmp)
    tmp.chmod(mode)
    os.replace(tmp, destination)


def install_one(name: str, spec: dict[str, Any], stage_dir: Path, backup_root: Path) -> Path:
    backup_dir = backup_root / name
    backup_dir.mkdir(parents=True, exist_ok=True)
    cert_type = str(spec.get("type", ""))
    cert_target = resolve(spec.get("cert"))
    key_target = resolve(spec.get("key"))
    ca_target = resolve(spec.get("ca"))
    if cert_target:
        cert_source = stage_dir / "ca.crt" if cert_type == "ca" and (stage_dir / "ca.crt").is_file() else stage_dir / "cert.crt"
        if spec.get("full_chain"):
            leaf = re.findall(r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", cert_source.read_text(), re.S)
            if not leaf:
                raise LifecycleError("missing leaf certificate for HTTPS full chain")
            chain = [leaf[0]]
            for certificate in re.findall(r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", (stage_dir / "ca.crt").read_text(), re.S):
                names = require_ok(run(["openssl", "x509", "-noout", "-subject", "-issuer", "-nameopt", "RFC2253"], input_text=certificate), "read intermediate")
                subject, issuer = names.strip().splitlines()[:2]
                if subject.removeprefix("subject=") != issuer.removeprefix("issuer="):
                    chain.append(certificate)
            cert_source = stage_dir / "fullchain.crt"
            cert_source.write_text("\n".join(dict.fromkeys(chain)) + "\n", encoding="ascii")
        atomic_copy(cert_source, cert_target, 0o644)
    if cert_type != "ca" and key_target:
        atomic_copy(stage_dir / "key.key", key_target, 0o600)
    if cert_type == "ca" and key_target and spec.get("private_key_managed_by") and key_target.exists():
        key_target.unlink()
    if ca_target and (stage_dir / "ca.crt").is_file():
        atomic_copy(stage_dir / "ca.crt", ca_target, 0o644)
    if cert_type == "ca":
        for item in spec.get("trust_distribution", []):
            atomic_copy(stage_dir / "ca.crt", resolve(str(item)), 0o644)  # type: ignore[arg-type]
    for item in spec.get("install_copies", []):
        source_name = str(item.get("source", "ca.crt"))
        destination_value = item.get("destination")
        if not destination_value:
            continue
        source = stage_dir / source_name
        if source.is_file():
            atomic_copy(source, resolve(str(destination_value)), int(str(item.get("mode", "0644")), 8))  # type: ignore[arg-type]
    return backup_dir


def backup_all(specs: dict[str, dict[str, Any]], backup_root: Path) -> dict[str, Path | None]:
    """Back up each active destination path once before any replacement.

    Some manifest entries intentionally share files. For example web_server.ca
    and web_ca.cert both target nginx/ca-trust/oculox-web-ca.crt. A global
    backup must therefore happen before the first install mutates any path.
    """
    backup_root.mkdir(parents=True, exist_ok=True)
    backup_root.chmod(0o700)
    index: dict[str, str | None] = {}
    for name, spec in specs.items():
        entry_dir = backup_root / name
        entry_dir.mkdir(parents=True, exist_ok=True)
        entry_dir.chmod(0o700)
        for field in ("cert", "key", "ca"):
            source = resolve(spec.get(field))
            if not source:
                continue
            source_key = str(source.resolve())
            if source_key in index:
                continue
            if not source.is_file():
                index[source_key] = None
                continue
            destination = entry_dir / f"{field}-{source.name}"
            shutil.copy2(source, destination)
            index[source_key] = str(destination.relative_to(backup_root))
        additional = [*spec.get("trust_distribution", []),
                      *[item["destination"] for item in spec.get("install_copies", []) if item.get("destination")]]
        for number, item in enumerate(additional):
            source = resolve(str(item))
            if source is None or str(source.resolve()) in index:
                continue
            if not source.is_file():
                index[str(source.resolve())] = None
                continue
            destination = entry_dir / f"trust-{number}-{source.name}"
            shutil.copy2(source, destination)
            index[str(source.resolve())] = str(destination.relative_to(backup_root))
    (backup_root / "index.json").write_text(json.dumps(index, indent=2, sort_keys=True), encoding="utf-8")
    return {path: backup_root / relative if relative is not None else None for path, relative in index.items()}


def restore_all(backup_map: dict[str, Path | None]) -> None:
    for destination, backup in backup_map.items():
        target = Path(destination)
        if backup is None:
            target.unlink(missing_ok=True)
            continue
        atomic_copy(backup, target, backup.stat().st_mode & 0o777)


def restart_services(specs: list[dict[str, Any]]) -> None:
    services = sorted({service for spec in specs for service in spec.get("reload", [])})
    if not services:
        print("Aucun service à redémarrer pour ces entrées.")
        return
    runtime = PROJECT_DIR / "dev/generated/docker-compose.runtime.yml"
    profile = parse_env_reference("config/process.env:MALCOLM_PROFILE") or "malcolm"
    base = ["docker", "compose", "-f", str(runtime), "--profile", profile]
    result = run([*base, "restart", *services])
    if result.returncode != 0:
        raise LifecycleError(result.stderr.strip() or result.stdout.strip() or "redémarrage échoué")
    print(result.stdout.strip())
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        status = run([*base, "ps", "--format", "json"])
        records = [json.loads(line) for line in status.stdout.splitlines() if line.strip()] if status.returncode == 0 else []
        if all(any(record.get("Service") == service and record.get("State") == "running"
                   and record.get("Health") in {"", "healthy"} for record in records) for service in services):
            return
        time.sleep(3)
    raise LifecycleError("restarted services did not become healthy; rollback required")


def run_validation(specs: dict[str, dict[str, Any]]) -> None:
    # Bootstrap installs identities one at a time; unrelated identities may not exist yet.
    module_spec = importlib.util.spec_from_file_location("oculox_installed_pki_audit", PROJECT_DIR / "dev/scripts/pki-audit.py")
    audit = importlib.util.module_from_spec(module_spec)
    sys.modules[module_spec.name] = audit
    module_spec.loader.exec_module(audit)
    for name, spec in specs.items():
        result = audit.audit_certificate(name, {**spec, "required": True}, 60, 30)
        print(f"INSTALLED_VALIDATION {name}: {result.status}")
        if result.status == "FAIL":
            details = "; ".join(item.detail for item in result.checks if item.status in {"FAIL", "MISSING"})
            raise LifecycleError(f"validation PKI installée échouée: {name}: {details}")


def maybe_install(staged: dict[str, Path], specs: dict[str, dict[str, Any]], install: bool, restart: bool) -> None:
    if not install:
        print("\nStaging terminé. Aucun certificat actif n'a été remplacé.")
        print("Ajoutez --install pour installer, puis --restart pour redémarrer uniquement les services concernés.")
        return
    trust_target = PROJECT_DIR / "nginx/ca-trust/oculox-opensearch-ca.crt"
    for name, spec in specs.items():
        targets = [resolve(spec.get("cert")), *[resolve(str(item)) for item in spec.get("trust_distribution", [])]]
        if trust_target not in targets or not (PROJECT_DIR / "dev/generated/opensearch-clients").is_dir():
            continue
        endpoint = parse_env_reference("config/opensearch.env:OPENSEARCH_URL")
        if endpoint:
            result = run(["curl", "--silent", "--show-error", "--max-time", "15", "--cacert", str(staged[name] / "ca.crt"), "-o", "/dev/null", endpoint])
            require_ok(result, "Nouvelle CA incompatible avec le cluster actif; conserver la confiance existante et coordonner la rotation du serveur")
    backup_root = BACKUPS_DIR / dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_map = backup_all(specs, backup_root)
    installed: dict[str, Path] = {}
    try:
        for name, stage_dir in staged.items():
            installed[name] = install_one(name, specs[name], stage_dir, backup_root)
            print(f"INSTALL {name}: backup={rel(installed[name])}")
        if restart:
            restart_services([specs[name] for name in staged])
        run_validation({name: specs[name] for name in staged})
    except Exception:
        print("Echec après installation. Restauration des certificats précédents.", file=sys.stderr)
        restore_all(backup_map)
        if restart and installed:
            restart_services([specs[name] for name in installed])
        raise


def command_enroll(args: argparse.Namespace) -> int:
    if args.service == "ejbca_api_server" and args.restart:
        raise LifecycleError("Use ./oculox pki-ca configure-api to rotate the EJBCA HTTPS keystore")
    ensure_ejbca_running()
    manifest = load_yaml(MANIFEST_PATH)
    ca_plan = load_yaml(CA_PLAN_PATH)
    specs = manifest_entries(manifest, args.service)
    root = ENROLLMENTS_DIR / dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    staged: dict[str, Path] = {}
    failures = 0
    for name, spec in specs.items():
        try:
            plan = profile_plan(ca_plan, str(spec.get("profile")))
            if str(spec.get("type")) == "ca":
                plan["issuer_display_name"] = ca_display_for_manifest_ca(str(spec.get("profile")), ca_plan)
            stage_dir = enroll_one(name, spec, plan, root, args.force)
            checks = validate_material(name, spec, stage_dir)
            for check in checks:
                print(f"{check.status:<5} {name}: {check.detail}")
            if any(check.status == "FAIL" for check in checks):
                failures += 1
            else:
                staged[name] = stage_dir
                print(f"STAGE {name}: {rel(stage_dir)}")
        except Exception as exc:
            required = bool(spec.get("required", True)) or bool(args.service)
            level = "FAIL" if required else "WARN"
            print(f"{level:<5} {name}: {exc}")
            if required:
                failures += 1
    if failures:
        return 1
    maybe_install(staged, specs, args.install, args.restart)
    return 0


def copy_customer_material(bundle: Path, name: str, root: Path) -> Path:
    source_dir = bundle / name
    if not source_dir.is_dir():
        raise LifecycleError(f"bundle client incomplet pour {name}: {source_dir}")
    stage_dir = root / name
    stage_dir.mkdir(parents=True, exist_ok=True)
    stage_dir.chmod(0o700)
    mapping = {
        "cert.crt": stage_dir / "cert.crt",
        "key.key": stage_dir / "key.key",
        "ca.crt": stage_dir / "ca.crt",
    }
    for filename, destination in mapping.items():
        source = source_dir / filename
        if source.is_file():
            shutil.copy2(source, destination)
            destination.chmod(0o600 if filename.endswith(".key") else 0o644)
    write_metadata(stage_dir, {"name": name, "provider": "customer", "source": str(source_dir)})
    return stage_dir


def command_import(args: argparse.Namespace) -> int:
    bundle = Path(args.bundle).resolve()
    if not bundle.is_dir():
        raise LifecycleError(f"bundle client absent: {bundle}")
    manifest = load_yaml(MANIFEST_PATH)
    specs = manifest_entries(manifest, args.service)
    root = ENROLLMENTS_DIR / f"customer-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    staged: dict[str, Path] = {}
    failures = 0
    for name, spec in specs.items():
        try:
            stage_dir = copy_customer_material(bundle, name, root)
            checks = validate_material(name, spec, stage_dir)
            for check in checks:
                print(f"{check.status:<5} {name}: {check.detail}")
            if any(check.status == "FAIL" for check in checks):
                failures += 1
            else:
                staged[name] = stage_dir
                print(f"STAGE {name}: {rel(stage_dir)}")
        except Exception as exc:
            print(f"FAIL  {name}: {exc}")
            failures += 1
    if failures:
        return 1
    maybe_install(staged, specs, args.install, args.restart)
    return 0


def command_chain(args: argparse.Namespace) -> int:
    specs = manifest_entries(load_yaml(MANIFEST_PATH), args.service)
    name, spec = next(iter(specs.items()))
    if not spec.get("full_chain"):
        raise LifecycleError("This manifest service does not use a PEM HTTPS full chain")
    with tempfile.TemporaryDirectory(prefix="oculox-fullchain-") as directory:
        stage = Path(directory)
        for field, filename in (("cert", "cert.crt"), ("key", "key.key"), ("ca", "ca.crt")):
            shutil.copy2(resolve(spec[field]), stage / filename)
        if any(result.status == "FAIL" for result in validate_material(name, spec, stage)):
            raise LifecycleError("active material is invalid; no chain installation performed")
        maybe_install({name: stage}, specs, args.install, args.restart)
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Cycle de vie PKI Oculox/EJBCA")
    sub = parser.add_subparsers(dest="command", required=True)

    for name in ("enroll", "renew"):
        cmd = sub.add_parser(name, help=f"{name} via EJBCA en staging")
        cmd.add_argument("--provider", choices=("ejbca",), required=True)
        cmd.add_argument("--service", help="entrée du manifest à traiter")
        cmd.add_argument("--install", action="store_true", help="installer les certificats après validation")
        cmd.add_argument("--restart", action="store_true", help="redémarrer uniquement les services concernés après installation")
        cmd.add_argument("--force", action="store_true", help="réémettre même si un certificat actif existe")

    imp = sub.add_parser("import", help="valider/importer un bundle PKI client")
    imp.add_argument("--provider", choices=("customer",), required=True)
    imp.add_argument("--bundle", required=True, help="répertoire contenant un sous-répertoire par entrée du manifest")
    imp.add_argument("--service", help="entrée du manifest à traiter")
    imp.add_argument("--install", action="store_true")
    imp.add_argument("--restart", action="store_true")
    chain = sub.add_parser("chain", help="install the HTTPS full chain without reissuing certificates")
    chain.add_argument("--service", required=True)
    chain.add_argument("--install", action="store_true")
    chain.add_argument("--restart", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.command in {"enroll", "renew"}:
            return command_enroll(args)
        if args.command == "import":
            return command_import(args)
        if args.command == "chain":
            return command_chain(args)
        raise LifecycleError(f"commande inconnue: {args.command}")
    except LifecycleError as exc:
        print(f"ERREUR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
