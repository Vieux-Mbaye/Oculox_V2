#!/usr/bin/env python3
"""Bootstrap role-scoped EJBCA agents and enroll VM-local CSRs over mTLS."""

from __future__ import annotations

import argparse
import base64
import copy
import datetime as dt
import hashlib
import importlib.util
import ipaddress
import json
import os
import re
import secrets
import shutil
import ssl
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
STATE = ROOT / "dev/generated/pki/remote-agent"
EJBCA = ROOT / "dev/ejbca/generated/ejbca.env"
MANIFEST = ROOT / "dev/ejbca/pki-manifest.yml"
PLAN = ROOT / "dev/ejbca/profiles/ca-plan.yml"
ROLE_SERVICES = {
    "cluster": ("opensearch_node_1", "opensearch_node_2", "opensearch_node_3",
                "opensearch_endpoint", "opensearch_admin_client"),
    "collector": ("filebeat_client",),
}
ROLE_CA = {"cluster": "Oculox OpenSearch CA", "collector": "Oculox Internal Services CA"}
AGENT_CA = "Oculox Internal Services CA"
AGENT_PROFILE = "oculox-enrollment-agent"


def lifecycle():
    path = Path(__file__).with_name("pki-lifecycle.py")
    spec = importlib.util.spec_from_file_location("oculox_pki_lifecycle", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def call(*argv: str, input_text: str | None = None) -> str:
    process = subprocess.run(argv, input=input_text, text=True, capture_output=True, check=False)
    if process.returncode:
        raise RuntimeError(process.stderr.strip() or process.stdout.strip() or f"failed: {argv[0]}")
    return process.stdout


def openssl(*argv: str) -> str:
    return call("openssl", *argv)


def env_value(key: str) -> str:
    if not EJBCA.is_file():
        raise RuntimeError(f"EJBCA runtime configuration missing: {EJBCA}")
    for line in EJBCA.read_text(encoding="utf-8").splitlines():
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError(f"EJBCA variable missing: {key}")


def identity(value: str) -> str:
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", value):
        raise ValueError("identity must be a lowercase DNS label")
    return value


def agent_dn(role: str, name: str) -> str:
    return f"CN=oculox-{role}-{name},OU=Oculox Enrollment Agents,O=Oculox,C=SN"


def matching_subject(subject_output: str, expected_dn: str) -> bool:
    actual = subject_output.strip().removeprefix("subject=").strip()
    return set(actual.split(",")) == set(expected_dn.split(",")) and len(actual.split(",")) == 4


def pem(der: bytes) -> str:
    encoded = base64.b64encode(der).decode("ascii")
    return "-----BEGIN CERTIFICATE-----\n" + "\n".join(encoded[i:i+64] for i in range(0, len(encoded), 64)) + "\n-----END CERTIFICATE-----\n"


def fingerprint(path: Path) -> str:
    result = subprocess.run(["openssl", "x509", "-in", str(path), "-outform", "DER"], capture_output=True, check=True)
    return hashlib.sha256(result.stdout).hexdigest()


def verify_pinned_bundle(bundle: Path, expected: str) -> None:
    root = bundle / "root.crt"
    if not re.fullmatch(r"[0-9a-f]{64}", expected) or fingerprint(root) != expected:
        raise RuntimeError("root fingerprint mismatch")
    # Each certificate must chain to the pinned root, never to a bundled trust anchor.
    for filename in ("agent-ca.crt", "api-ca.crt", "service-ca.crt"):
        content = (bundle / filename).read_text(encoding="ascii")
        certificates = re.findall(r"-----BEGIN CERTIFICATE-----\s+.*?-----END CERTIFICATE-----", content, re.S)
        remaining = re.sub(r"-----BEGIN CERTIFICATE-----\s+.*?-----END CERTIFICATE-----", "", content, flags=re.S)
        if not certificates or any(line.strip() and not line.startswith(("Subject:", "Issuer:"))
                                   for line in remaining.splitlines()):
            raise RuntimeError(f"invalid PEM CA bundle: {filename}")
        with tempfile.TemporaryDirectory(prefix="oculox-pinned-ca-") as directory:
            for number, certificate in enumerate(certificates):
                path = Path(directory) / f"{number}.crt"
                path.write_text(certificate + "\n", encoding="ascii")
                openssl("verify", "-no-CAfile", "-no-CApath", "-no-CAstore",
                        "-trusted", str(root), "-untrusted", str(bundle / filename), str(path))


def validate_agent_config(config: dict) -> None:
    role = config.get("role")
    if role not in ROLE_SERVICES or config.get("allowed_services") != list(ROLE_SERVICES[role]):
        raise RuntimeError("invalid agent role/service policy")
    identity(config["identity"])
    if role == "collector" and config.get("end_entity_profile") != collector_profile_name(config["identity"]):
        raise RuntimeError("collector enrollment profile does not match its identity")
    if role == "cluster":
        profiles = {service: scoped_profile_name(role, config["identity"], service)
                    for service in ROLE_SERVICES[role]}
        if config.get("end_entity_profiles") != profiles:
            raise RuntimeError("cluster enrollment profiles do not match its identity")
        ipaddress.ip_address(config["endpoint_ip"])
        endpoint_dns(config.get("endpoint_dns"))
    url = urlsplit(config.get("api_url", ""))
    if (url.scheme != "https" or not url.hostname or url.username or url.password
            or url.query or url.fragment
            or url.path != "/ejbca/ejbca-rest-api/v1/certificate/pkcs10enroll"):
        raise RuntimeError("invalid EJBCA HTTPS enrollment URL")


def init_agent(args: argparse.Namespace) -> None:
    name = identity(args.identity)
    role = args.role
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    STATE.chmod(0o700)
    pending = getattr(args, "renew", False)
    if pending:
        config = json.loads((STATE / "config.json").read_text(encoding="utf-8"))
        if (config["role"], config["identity"]) != (role, name):
            raise RuntimeError("agent renewal identity mismatch")
    key = STATE / ("pending.key" if pending else "agent.key")
    csr = STATE / ("pending.csr" if pending else "agent.csr")
    if key.exists() or csr.exists():
        raise RuntimeError("agent key/CSR already exists; do not overwrite it")
    openssl("genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:3072", "-out", str(key))
    key.chmod(0o600)
    openssl("req", "-new", "-sha256", "-key", str(key), "-subj",
            f"/CN=oculox-{role}-{name}/OU=Oculox Enrollment Agents/O=Oculox/C=SN",
            "-addext", f"subjectAltName=DNS:oculox-{role}-{name}", "-out", str(csr))
    print(f"CSR publique: {csr}")
    print("Clé privée conservée sur cette VM; ne la transférez jamais.")


def ejbca(*args: str) -> str:
    return call("docker", "exec", "oculox-ejbca", "/opt/keyfactor/bin/ejbca.sh", *args)


def role_name(role: str, name: str) -> str:
    return f"Oculox Enrollment {role} {name}"


def collector_profile_name(name: str) -> str:
    return f"oculox-filebeat-client-{identity(name)}-enroll-v2"


def scoped_profile_name(role: str, name: str, service: str) -> str:
    if role == "collector":
        return collector_profile_name(name)
    return f"oculox-{service.replace('_', '-')}-{identity(name)}-enroll-v2"


def scoped_subject(role: str, name: str, service: str) -> str:
    if service not in ROLE_SERVICES[role]:
        raise RuntimeError("service outside enrollment role")
    lib = lifecycle()
    spec = lib.load_yaml(MANIFEST)["certificates"][service]
    return lib.cert_subject(service, spec, identity(name) if role == "collector" else None)


def endpoint_dns(value: str | None) -> str | None:
    if value is None:
        return None
    if len(value) > 253 or not all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                                     for label in value.split(".")):
        raise ValueError("endpoint DNS must contain valid lowercase DNS labels")
    return value


def scoped_sans(role: str, name: str, service: str, endpoint_ip: str | None,
                dns: str | None) -> tuple[list[str], list[str]]:
    if role == "collector":
        return ["filebeat", name], []
    if service.startswith("opensearch_node_"):
        return [service.replace("_node_", "-")], []
    if service == "opensearch_endpoint":
        if not endpoint_ip:
            raise RuntimeError("cluster endpoint IP must be approved before enrollment")
        return ["opensearch-endpoint", *([dns] if dns else [])], [endpoint_ip]
    return [], []


def bind_profile_identity(root: ET.Element, subject: str, dns_sans: list[str], ip_sans: list[str]) -> None:
    entries = {item[0].text: item for item in root.findall("void")
               if item.get("method") == "put" and len(item) == 2}
    counts = entries["NUMBERARRAY"][1].findall("void")
    # EJBCA field IDs: CN=5, OU=11, O=12, C=16, DNS=18, IP=19.
    dn = dict(component.split("=", 1) for component in subject.split(","))
    bindings = ((5, [dn["CN"]]), (11, [dn["OU"]]), (12, [dn["O"]]),
                (16, [dn["C"]]), (18, dns_sans), (19, ip_sans))
    for field, values in bindings:
        counts[field].find("int").text = str(len(values))
        for slot, value in enumerate(values):
            index = field + 100 * slot
            for key, tag, content in ((str(index), "string", value),
                                      (str(10000 + index), "boolean", "true"),
                                      (str(20000 + index), "boolean", "true"),
                                      (str(30000 + index), "boolean", "false")):
                item = entries[key]
                item.remove(item[1])
                ET.SubElement(item, tag).text = content


def profile_policy(root: ET.Element) -> str:
    normalized = copy.deepcopy(root)
    counts = next(item[1] for item in normalized.findall("void")
                  if len(item) == 2 and item[0].tag == "string" and item[0].text == "NUMBERARRAY")
    # EJBCA grows this array on access; absent fields and trailing zero counts are equivalent.
    while len(counts) > 20:
        item = counts[-1]
        if item.get("method") != "add" or len(item) != 1 or item[0].tag != "int" or item[0].text != "0":
            break
        counts.remove(item)
    return ET.canonicalize(ET.tostring(normalized), strip_text=True)


def provision_scoped_profile(role: str, name: str, service: str,
                             endpoint_ip: str | None = None, dns: str | None = None) -> str:
    """Create an agent-specific EJBCA profile with immutable SANs."""
    profile = scoped_profile_name(role, name, service)
    manifest = lifecycle().load_yaml(MANIFEST)["certificates"]
    base_profile = manifest[service]["profile"] + "-enroll-v3"
    dns_sans, ip_sans = scoped_sans(role, name, service, endpoint_ip, dns)
    if len(dns_sans) > 3 or len(ip_sans) > 3:
        raise RuntimeError("too many fixed SANs for EJBCA profile")
    with tempfile.TemporaryDirectory(prefix="oculox-agent-profile-") as directory:
        local = Path(directory)
        remote = f"/tmp/oculox-profiles-{secrets.token_hex(8)}"
        call("docker", "exec", "oculox-ejbca", "mkdir", "-p", remote)
        try:
            ejbca("ca", "exportprofiles", "-d", remote)
            call("docker", "cp", f"oculox-ejbca:{remote}/.", str(local))
        finally:
            call("docker", "exec", "oculox-ejbca", "rm", "-rf", remote)
        base = list(local.glob(f"entityprofile_{base_profile}-*.xml"))
        if len(base) != 1:
            raise RuntimeError(f"base {service} end entity profile is missing or ambiguous")
        profile_id = 1_000_000_000 + int.from_bytes(hashlib.sha256(profile.encode()).digest()[:4], "big") % 1_000_000_000
        expected = local / f"entityprofile_{profile}-{profile_id}.xml"
        for existing in local.glob(f"entityprofile_*-{profile_id}.xml"):
            if existing.name != expected.name:
                raise RuntimeError("scoped profile ID collision")
        tree = ET.parse(base[0])
        root = tree.getroot().find("object")
        if root is None:
            raise RuntimeError("invalid EJBCA end entity profile")
        bind_profile_identity(root, scoped_subject(role, name, service), dns_sans, ip_sans)
        if expected.exists():
            current = ET.parse(expected).getroot().find("object")
            if current is None or profile_policy(current) != profile_policy(root):
                raise RuntimeError("scoped profile drift; refusing to replace EJBCA policy")
            return profile
        with tempfile.TemporaryDirectory(prefix="oculox-collector-import-") as staging:
            source = Path(staging) / expected.name
            tree.write(source, encoding="utf-8", xml_declaration=True)
            destination = f"/tmp/oculox-profile-import-{secrets.token_hex(8)}"
            call("docker", "exec", "oculox-ejbca", "mkdir", "-p", destination)
            try:
                call("docker", "cp", str(source), f"oculox-ejbca:{destination}/{source.name}")
                ejbca("ca", "importprofiles", "-d", destination)
            finally:
                call("docker", "exec", "oculox-ejbca", "rm", "-rf", destination)
    return profile


def provision_role(role: str, name: str, cn: str) -> None:
    title = role_name(role, name)
    existing = ejbca("roles", "listroles")
    if f"'{title}'" not in existing:
        ejbca("roles", "addrole", title)
    rules = ["/administrator/", f"/ca/{ROLE_CA[role]}/",
             "/ca_functionality/create_certificate/", "/ra_functionality/create_end_entity/",
             "/ra_functionality/view_end_entity_profiles/"]
    manifest = lifecycle().load_yaml(MANIFEST)["certificates"]
    for service in ROLE_SERVICES[role]:
        rules.append(f"/endentityprofilesrules/{scoped_profile_name(role, name, service)}/")
    for profile in sorted({manifest[service]["profile"] + "-enroll-v3" for service in ROLE_SERVICES[role]}):
        ejbca("roles", "changerule", title,
              f"/endentityprofilesrules/{profile}/", "DECLINE")
    # Remediate roles created by older releases. Enrollment agents may create
    # entities under their immutable scoped profiles, but must never edit an
    # existing entity owned by another enrollment agent.
    ejbca("roles", "changerule", title,
          "/ra_functionality/edit_end_entity/", "DECLINE")
    for service in ROLE_SERVICES[role]:
        previous = scoped_profile_name(role, name, service).removesuffix("-v2") + "-v1"
        resource = f"/endentityprofilesrules/{previous}/"
        try:
            ejbca("roles", "changerule", title, resource, "DECLINE")
        except RuntimeError as exc:
            # A fresh identity has no v1 profile or permission to remove.
            if f"No resource with name '{resource}' is available" not in str(exc):
                raise
    for rule in rules:
        ejbca("roles", "changerule", title, rule, "ACCEPT")
    members = ejbca("roles", "listadmins", "--role", title)
    marker = f"'{AGENT_CA}' WITH_COMMONNAME TYPE_EQUALCASE \"{cn}\""
    if marker not in members:
        ejbca("roles", "addrolemember", "--role", title, "--caname", AGENT_CA,
              "--with", "WITH_COMMONNAME", "--value", cn)


def revoke_agent(args: argparse.Namespace) -> None:
    name = identity(args.identity)
    role = args.role
    cn = f"oculox-{role}-{name}"
    title = role_name(role, name)
    if f"'{title}'" not in ejbca("roles", "listroles"):
        raise RuntimeError(f"enrollment role does not exist: {title}")
    members = lifecycle().matching_end_entities(agent_dn(role, name))
    if not members:
        raise RuntimeError("no matching enrollment end entity; nothing revoked")
    if args.dry_run:
        print(f"Would remove role membership and revoke {len(members)} agent end entity(s): {title}")
        return
    ejbca("roles", "removeadmin", "--role", title, "--caname", AGENT_CA,
          "--with", "WITH_COMMONNAME", "--value", cn)
    for username, status in members:
        if status not in {"50", "60"}:
            ejbca("ra", "revokeendentity", username, "9")
    ejbca("ca", "createcrl", AGENT_CA)
    print(f"Revoked agent {role}/{name}; role membership removed and CRL regenerated")


def authorize_agent(args: argparse.Namespace) -> None:
    name = identity(args.identity)
    role = args.role
    csr = args.csr.resolve()
    if not csr.is_file():
        raise RuntimeError("CSR not found")
    openssl("req", "-in", str(csr), "-verify", "-noout")
    subject = openssl("req", "-in", str(csr), "-noout", "-subject", "-nameopt", "RFC2253")
    cn = f"oculox-{role}-{name}"
    if not matching_subject(subject, agent_dn(role, name)):
        raise RuntimeError("CSR subject does not match authorized role/identity")
    sans = openssl("req", "-in", str(csr), "-noout", "-text")
    if f"DNS:oculox-{role}-{name}" not in sans:
        raise RuntimeError("CSR SAN does not match authorized role/identity")
    out = args.output.resolve()
    if out.exists():
        raise RuntimeError("output already exists")
    existing = lifecycle().matching_end_entities(agent_dn(role, name))
    renewing = getattr(args, "renew", False)
    if bool(existing) != renewing:
        raise RuntimeError("Use --renew for an existing agent; renewal requires an existing identity")
    if role == "cluster" and not getattr(args, "endpoint_ip", None):
        raise RuntimeError("--endpoint-ip is required when authorizing a cluster agent")
    cluster_ip = str(ipaddress.ip_address(args.endpoint_ip)) if role == "cluster" else None
    cluster_dns = endpoint_dns(getattr(args, "endpoint_dns", None)) if role == "cluster" else None
    for service in ROLE_SERVICES[role]:
        provision_scoped_profile(role, name, service, cluster_ip, cluster_dns)
    provision_role(role, name, cn)
    out.mkdir(parents=True, mode=0o700)
    out.chmod(0o700)
    username = existing[0][0] if renewing else f"oculox-agent-{role}-{name}-{secrets.token_hex(5)}"
    secret = secrets.token_urlsafe(24)
    dn = agent_dn(role, name)
    if not renewing:
        ejbca("ra", "addendentity", "--username", username, "--dn", dn,
              "--caname", AGENT_CA, "--type", "1", "--token", "USERGENERATED",
              "--password", secret, "--certprofile", AGENT_PROFILE,
              "--eeprofile", AGENT_PROFILE + "-enroll-v3",
              "--altname", f"dNSName={cn}")
    ejbca("ra", "setpwd", username, "--password", secret)
    ejbca("ra", "setendentitystatus", username, "10")
    remote = f"/tmp/oculox-agent-{secrets.token_hex(8)}"
    call("docker", "exec", "oculox-ejbca", "mkdir", "-p", remote)
    try:
        call("docker", "cp", str(csr), f"oculox-ejbca:{remote}/request.csr")
        ejbca("createcert", "--username", username, "--password", secret,
              "-c", f"{remote}/request.csr", "-f", f"{remote}/agent.crt")
        call("docker", "cp", f"oculox-ejbca:{remote}/agent.crt", str(out / "agent.crt"))
    finally:
        call("docker", "exec", "oculox-ejbca", "rm", "-rf", remote)
    api_ca = out / "api-ca.crt"
    lib = lifecycle()
    lib.export_ca_bundle("Oculox Web CA", api_ca)
    lib.export_ca_bundle(AGENT_CA, out / "agent-ca.crt")
    lib.export_ca_bundle(ROLE_CA[role], out / "service-ca.crt")
    lib.export_ca("Oculox Root CA", out / "root.crt")
    host = env_value("OCULOX_EJBCA_PUBLIC_HOST")
    port = env_value("OCULOX_EJBCA_HTTPS_PORT")
    (out / "config.json").write_text(json.dumps({"role": role, "identity": name,
        "api_url": f"https://{host}:{port}/ejbca/ejbca-rest-api/v1/certificate/pkcs10enroll",
        "allowed_services": list(ROLE_SERVICES[role]),
        **({"end_entity_profile": collector_profile_name(name)} if role == "collector" else
           {"end_entity_profiles": {service: scoped_profile_name(role, name, service)
                                    for service in ROLE_SERVICES[role]},
            "endpoint_ip": cluster_ip, "endpoint_dns": cluster_dns})}, indent=2) + "\n", encoding="utf-8")
    for item in out.iterdir():
        item.chmod(0o644)
    print(f"Issued public enrollment bundle: {out}")
    print(f"Root SHA256: {fingerprint(out / 'root.crt')}")


def install_agent(args: argparse.Namespace) -> None:
    bundle = args.bundle.resolve()
    config = json.loads((bundle / "config.json").read_text(encoding="utf-8"))
    validate_agent_config(config)
    role, name = config["role"], identity(config["identity"])
    expected = args.root_sha256.lower().replace(":", "")
    verify_pinned_bundle(bundle, expected)
    renewing = getattr(args, "renew", False)
    cert, key = bundle / "agent.crt", STATE / ("pending.key" if renewing else "agent.key")
    if not key.is_file():
        raise RuntimeError("this VM has no locally generated agent key")
    openssl("verify", "-no-CAfile", "-no-CApath", "-no-CAstore", "-purpose", "sslclient",
            "-trusted", str(bundle / "root.crt"), "-untrusted", str(bundle / "agent-ca.crt"), str(cert))
    subject = openssl("x509", "-in", str(cert), "-noout", "-subject", "-nameopt", "RFC2253")
    if not matching_subject(subject, agent_dn(role, name)):
        raise RuntimeError("agent certificate subject mismatch")
    cert_pub = openssl("x509", "-in", str(cert), "-pubkey", "-noout")
    key_pub = openssl("pkey", "-in", str(key), "-pubout")
    if cert_pub != key_pub:
        raise RuntimeError("agent certificate does not match local private key")
    if STATE.joinpath("config.json").exists() and not renewing:
        raise RuntimeError("agent already installed")
    if renewing:
        previous = json.loads((STATE / "config.json").read_text(encoding="utf-8"))
        if (previous["role"], previous["identity"]) != (role, name):
            raise RuntimeError("renewal must preserve agent identity")
        if not (STATE / "pending.csr").is_file():
            raise RuntimeError("pending renewal CSR missing")
    public_files = ("agent.crt", "agent-ca.crt", "api-ca.crt", "service-ca.crt", "root.crt", "config.json")
    for file in public_files:
        if not (bundle / file).is_file():
            raise RuntimeError(f"public enrollment bundle missing {file}")
    backup = STATE / ("backup-" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    backup.mkdir(mode=0o700)
    before = {file.name for file in STATE.iterdir() if file.is_file()}
    for file in before:
        shutil.copy2(STATE / file, backup / file)
    try:
        for file in public_files:
            shutil.copy2(bundle / file, STATE / file)
            (STATE / file).chmod(0o644)
        if renewing:
            os.replace(key, STATE / "agent.key")
            (STATE / "agent.key").chmod(0o600)
            os.replace(STATE / "pending.csr", STATE / "agent.csr")
    except Exception:
        for file in set(public_files) | {"agent.key", "agent.csr", "pending.key", "pending.csr"}:
            if file in before:
                shutil.copy2(backup / file, STATE / file)
            else:
                (STATE / file).unlink(missing_ok=True)
        raise
    print(f"Agent {role}/{name} installed. Private key never left this VM.")


def request_service(args: argparse.Namespace) -> None:
    if not STATE.joinpath("config.json").is_file():
        raise RuntimeError("run agent-init and agent-install first")
    config = json.loads((STATE / "config.json").read_text(encoding="utf-8"))
    validate_agent_config(config)
    verify_pinned_bundle(STATE, fingerprint(STATE / "root.crt"))
    service = args.service
    if service not in ROLE_SERVICES.get(config["role"], ()):
        raise RuntimeError(f"service {service} is not allowed for role {config['role']}")
    lib = lifecycle()
    spec = dict(lib.load_yaml(MANIFEST)["certificates"][service])
    if config["role"] == "collector":
        spec["san_required"] = [*spec.get("san_required", []), config["identity"]]
    elif service == "opensearch_endpoint":
        spec["san_required"] = [*spec.get("san_required", []), config["endpoint_ip"]]
        if config.get("endpoint_dns"):
            spec["san_required"].append(config["endpoint_dns"])
    plan = lib.profile_plan(lib.load_yaml(PLAN), spec["profile"])
    stage = ROOT / "dev/ejbca/generated/enrollments" / dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") / service
    stage.mkdir(parents=True, mode=0o700)
    stage.chmod(0o700)
    key, csr = stage / "key.key", stage / "request.csr"
    if key.exists():
        raise RuntimeError("staged private key already exists")
    openssl("genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:3072", "-out", str(key))
    key.chmod(0o600)
    subject = scoped_subject(config["role"], config["identity"], service)
    dn = "/" + "/".join(subject.split(","))
    req = ["req", "-new", "-sha256", "-key", str(key), "-subj", dn, "-out", str(csr)]
    sans = lib.san_values(spec)
    if sans:
        formatted = []
        for san in sans:
            try:
                ipaddress.ip_address(san)
                formatted.append("IP:" + san)
            except ValueError:
                formatted.append("DNS:" + san)
        req.extend(["-addext", "subjectAltName=" + ",".join(formatted)])
    openssl(*req)
    body = {"certificate_request": csr.read_text(encoding="ascii"),
            "certificate_profile_name": spec["profile"],
            "end_entity_profile_name": (config["end_entity_profile"] if config["role"] == "collector"
                                        else config["end_entity_profiles"][service]),
            "certificate_authority_name": plan["issuer_display_name"],
            "username": f"oculox-{service}-{secrets.token_hex(8)}",
            "password": secrets.token_urlsafe(24), "include_chain": True}
    context = ssl.create_default_context(cafile=str(STATE / "api-ca.crt"))
    context.load_cert_chain(str(STATE / "agent.crt"), str(STATE / "agent.key"))
    request = urllib.request.Request(config["api_url"],
        data=json.dumps(body).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context))
        with opener.open(request, timeout=30) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"EJBCA rejected {service}: HTTP {exc.code}: {exc.read(400).decode('utf-8', 'replace')}") from exc
    (stage / "cert.crt").write_text(pem(base64.b64decode(result["certificate"])), encoding="ascii")
    shutil.copy2(STATE / "service-ca.crt", stage / "ca.crt")
    lib.write_metadata(stage, {"name": service, "provider": "ejbca", "key_origin": "local",
                              "issuance_transport": "rest-mtls", "ejbca_username": body["username"],
                              "agent_identity": config["identity"]})
    issued_subject = openssl("x509", "-in", str(stage / "cert.crt"), "-noout", "-subject", "-nameopt", "RFC2253")
    if not matching_subject(issued_subject, subject):
        raise RuntimeError("issued subject differs from authorized identity; active files untouched")
    checks = lib.validate_material(service, spec, stage)
    for check in checks:
        print(f"{check.status:<5} {service}: {check.detail}")
    if any(check.status == "FAIL" for check in checks):
        raise RuntimeError("issued certificate failed local validation; active files untouched")
    print(f"STAGE {service}: {stage}")
    if args.install:
        if config["role"] == "cluster":
            active = subprocess.run(["docker", "ps", "--filter", "name=oculox-opensearch-cluster-opensearch-1-1",
                                     "--format", "{{.Names}}"], capture_output=True, text=True, check=False)
            if active.returncode == 0 and active.stdout.strip():
                raise RuntimeError("active cluster requires the coordinated pki-migrate command")
        if args.restart and config["role"] == "cluster":
            raise RuntimeError("--restart requires coordinated cluster rotation")
        backup = lib.BACKUPS_DIR / dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        previous = lib.backup_all({service: spec}, backup)
        try:
            lib.install_one(service, spec, stage, backup)
            if args.restart:
                lib.restart_services([spec])
                lib.run_validation()
        except Exception:
            lib.restore_all(previous)
            if args.restart:
                lib.restart_services([spec])
            raise
        print(f"INSTALL {service}: backup={backup}")


def agent_status(args: argparse.Namespace) -> None:
    config = json.loads((STATE / "config.json").read_text(encoding="utf-8"))
    validate_agent_config(config)
    verify_pinned_bundle(STATE, fingerprint(STATE / "root.crt"))
    openssl("verify", "-purpose", "sslclient", "-CAfile", str(STATE / "agent-ca.crt"), str(STATE / "agent.crt"))
    openssl("x509", "-in", str(STATE / "agent.crt"), "-checkend", str(30 * 86400), "-noout")
    if args.online:
        context = ssl.create_default_context(cafile=str(STATE / "api-ca.crt"))
        context.load_cert_chain(str(STATE / "agent.crt"), str(STATE / "agent.key"))
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context))
        with opener.open(config["api_url"].rsplit("/", 1)[0] + "/status", timeout=15) as response:
            if json.load(response).get("status") != "OK":
                raise RuntimeError("EJBCA API is not ready")
    print(f"AGENT_STATUS=PASS role={config['role']} identity={config['identity']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("agent-init")
    init.add_argument("--role", choices=ROLE_SERVICES, required=True)
    init.add_argument("--identity", required=True)
    init.add_argument("--renew", action="store_true")
    auth = sub.add_parser("authorize-agent")
    auth.add_argument("--role", choices=ROLE_SERVICES, required=True)
    auth.add_argument("--identity", required=True)
    auth.add_argument("--csr", type=Path, required=True)
    auth.add_argument("--output", type=Path, required=True)
    auth.add_argument("--renew", action="store_true")
    auth.add_argument("--endpoint-ip", help="approved OpenSearch endpoint IP (required for cluster)")
    auth.add_argument("--endpoint-dns", help="optional approved OpenSearch endpoint DNS")
    revoke = sub.add_parser("revoke-agent")
    revoke.add_argument("--role", choices=ROLE_SERVICES, required=True)
    revoke.add_argument("--identity", required=True)
    revoke.add_argument("--dry-run", action="store_true")
    install = sub.add_parser("agent-install")
    install.add_argument("--bundle", type=Path, required=True)
    install.add_argument("--root-sha256", required=True)
    install.add_argument("--renew", action="store_true")
    req = sub.add_parser("request")
    req.add_argument("--service", required=True)
    req.add_argument("--install", action="store_true")
    req.add_argument("--restart", action="store_true")
    status = sub.add_parser("agent-status")
    status.add_argument("--online", action="store_true")
    args = parser.parse_args()
    {"agent-init": init_agent, "authorize-agent": authorize_agent, "revoke-agent": revoke_agent,
     "agent-install": install_agent, "agent-status": agent_status, "request": request_service}[args.command](args)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
