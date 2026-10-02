#!/usr/bin/env python3
"""Opt-in live EJBCA tests using disposable agents and VM-local staging only."""

import argparse
import base64
import importlib.util
import json
import secrets
import ssl
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load():
    spec = importlib.util.spec_from_file_location("oculox_live_remote", ROOT / "dev/scripts/ejbca/remote-enrollment.py")
    remote = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = remote
    spec.loader.exec_module(remote)
    return remote


def rejected_scoped_identity(remote, service, *, field="CN", foreign_dns=False, username=None):
    """Call REST directly with correct SANs but an unauthorized subject (or DNS)."""
    config = json.loads((remote.STATE / "config.json").read_text())
    role = config["role"]
    lib = remote.lifecycle()
    spec = lib.load_yaml(remote.MANIFEST)["certificates"][service]
    subject = remote.scoped_subject(role, config["identity"], service)
    if not foreign_dns and field is not None:
        foreign_value = "FR" if field == "C" else "foreign-test"
        subject = ",".join(f"{key}={foreign_value}" if key == field else part
                           for part in subject.split(",") for key in [part.split("=", 1)[0]])
    dns, ips = remote.scoped_sans(role, config["identity"], service,
                                config.get("endpoint_ip"), config.get("endpoint_dns"))
    if foreign_dns:
        dns = ["opensearch-endpoint", "unapproved.example.internal"]
    csr = remote.STATE / "wrong-subject.csr"
    command = ["req", "-new", "-newkey", "rsa:3072", "-nodes", "-sha256",
               "-keyout", str(remote.STATE / "wrong-subject.key"), "-out", str(csr),
               "-subj", "/" + subject.replace(",", "/")]
    sans = ["DNS:" + value for value in dns] + ["IP:" + value for value in ips]
    if sans:
        command.extend(["-addext", "subjectAltName=" + ",".join(sans)])
    remote.openssl(*command)
    context = ssl.create_default_context(cafile=str(remote.STATE / "api-ca.crt"))
    context.load_cert_chain(str(remote.STATE / "agent.crt"), str(remote.STATE / "agent.key"))
    body = {"certificate_request": csr.read_text(), "certificate_profile_name": spec["profile"],
            "end_entity_profile_name": (config["end_entity_profile"] if role == "collector"
                                         else config["end_entity_profiles"][service]),
            "certificate_authority_name": remote.ROLE_CA[role],
            "username": username or "oculox-wrong-dn-" + secrets.token_hex(8), "password": secrets.token_urlsafe(24)}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context))
    request = urllib.request.Request(config["api_url"], data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
    try:
        with opener.open(request, timeout=30) as response:
            issued = json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read(4096).decode("utf-8", "replace").lower()
        if exc.code in {401, 403} or (field is not None and exc.code == 400 and any(term in detail for term in
                ("profile", "commonname", "organizationalunit", "organization", "country", "dnsname"))):
            return
        raise RuntimeError(f"Identity test returned unrelated HTTP {exc.code}: {detail}") from exc
    certificate = remote.STATE / "unexpected-identity.crt"
    certificate.write_text(remote.pem(base64.b64decode(issued["certificate"])))
    remote.call(str(ROOT / "oculox"), "pki-ca", "revoke-certificate", "--certificate", str(certificate),
                "--reason", "superseded", "--output-crl", str(remote.STATE / "unexpected-identity.crl"))
    raise RuntimeError(f"EJBCA accepted unauthorized {field if not foreign_dns else 'DNS'} for {service}")


def rejected_request(remote, profile, ca, *, san=None):
    config = json.loads((remote.STATE / "config.json").read_text())
    context = ssl.create_default_context(cafile=str(remote.STATE / "api-ca.crt"))
    context.load_cert_chain(str(remote.STATE / "agent.crt"), str(remote.STATE / "agent.key"))
    csr = remote.STATE / "forbidden.csr"
    command = ["req", "-new", "-key", str(remote.STATE / "agent.key"),
               "-subj", "/CN=forbidden-test", "-out", str(csr)]
    if san:
        command.extend(["-addext", "subjectAltName=" + san])
    remote.openssl(*command)
    body = {"certificate_request": csr.read_text(), "certificate_profile_name": profile,
            "end_entity_profile_name": profile + "-enroll-v3", "certificate_authority_name": ca,
            "username": "oculox-forbidden-" + secrets.token_hex(8), "password": secrets.token_urlsafe(24)}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context))
    request = urllib.request.Request(config["api_url"], data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    try:
        with opener.open(request, timeout=30) as response:
            issued = json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code in {401, 403}:
            return
        raise RuntimeError(f"Expected authorization denial, received HTTP {exc.code}") from exc
    certificate = remote.STATE / "unexpected-forbidden.crt"
    certificate.write_text(remote.pem(base64.b64decode(issued["certificate"])))
    remote.call(str(ROOT / "oculox"), "pki-ca", "revoke-certificate", "--certificate", str(certificate),
                "--reason", "superseded", "--output-crl", str(remote.STATE / "unexpected-forbidden.crl"))
    raise RuntimeError("EJBCA issued a forbidden certificate")


def rejected_foreign_collector_identity(remote, lib):
    config = json.loads((remote.STATE / "config.json").read_text())
    context = ssl.create_default_context(cafile=str(remote.STATE / "api-ca.crt"))
    context.load_cert_chain(str(remote.STATE / "agent.crt"), str(remote.STATE / "agent.key"))
    key = remote.STATE / "foreign.key"
    csr = remote.STATE / "foreign.csr"
    foreign = "other-" + secrets.token_hex(6)
    subject = remote.scoped_subject("collector", config["identity"], "filebeat_client")
    username = "oculox-foreign-test-" + secrets.token_hex(8)
    remote.openssl("req", "-new", "-newkey", "rsa:3072", "-nodes", "-sha256",
                   "-keyout", str(key), "-out", str(csr),
                   "-subj", "/" + subject.replace(",", "/"),
                   "-addext", f"subjectAltName=DNS:filebeat,DNS:{foreign}")
    body = {"certificate_request": csr.read_text(),
            "certificate_profile_name": "oculox-filebeat-client",
            "end_entity_profile_name": config["end_entity_profile"],
            "certificate_authority_name": "Oculox Internal Services CA",
            "username": username, "password": secrets.token_urlsafe(24), "include_chain": True}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context))
    request = urllib.request.Request(config["api_url"], data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
    try:
        try:
            with opener.open(request, timeout=30):
                raise RuntimeError("EJBCA accepted an unauthorized collector SAN")
        except urllib.error.HTTPError as exc:
            if exc.code in {401, 403}:
                return
            detail = exc.read(4096).decode("utf-8", "replace")
            if exc.code == 400 and any(term in detail.lower() for term in
                    ("subject alternative", "subjectalt", "end entity profile", "profile field", "dNSName".lower())):
                return
            raise RuntimeError(f"Foreign identity request returned HTTP {exc.code}: {detail}") from exc
    finally:
        matches = lib.matching_end_entities(subject)
        for issued_username, status in matches:
            if issued_username == username and status not in {"50", "60"}:
                remote.ejbca("ra", "revokeendentity", username, "9")
                remote.ejbca("ca", "createcrl", "Oculox Internal Services CA")


def rejected_foreign_cluster_endpoint(remote, lib):
    config = json.loads((remote.STATE / "config.json").read_text())
    context = ssl.create_default_context(cafile=str(remote.STATE / "api-ca.crt"))
    context.load_cert_chain(str(remote.STATE / "agent.crt"), str(remote.STATE / "agent.key"))
    csr = remote.STATE / "foreign-endpoint.csr"
    username = "oculox-foreign-endpoint-" + secrets.token_hex(8)
    remote.openssl("req", "-new", "-newkey", "rsa:3072", "-nodes", "-sha256",
                   "-keyout", str(remote.STATE / "foreign-endpoint.key"),
                   "-subj", "/CN=opensearch-endpoint/OU=OpenSearch HTTP/O=Oculox/C=SN",
                   "-addext", "subjectAltName=DNS:opensearch-endpoint,DNS:search.example.internal,IP:192.0.2.201",
                   "-out", str(csr))
    body = {"certificate_request": csr.read_text(),
            "certificate_profile_name": "oculox-opensearch-endpoint",
            "end_entity_profile_name": config["end_entity_profiles"]["opensearch_endpoint"],
            "certificate_authority_name": "Oculox OpenSearch CA", "username": username,
            "password": secrets.token_urlsafe(24)}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context))
    request = urllib.request.Request(config["api_url"], data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
    try:
        try:
            with opener.open(request, timeout=30):
                raise RuntimeError("EJBCA issued an endpoint certificate for an unapproved IP")
        except urllib.error.HTTPError as exc:
            detail = exc.read(4096).decode("utf-8", "replace").lower()
            if exc.code in {401, 403} or (exc.code == 400 and any(
                    term in detail for term in ("subject alternative", "subjectalt", "profile field", "ipaddress"))):
                return
            raise RuntimeError(f"Foreign endpoint request returned HTTP {exc.code}: {detail}") from exc
    finally:
        matches = lib.matching_end_entities(
            "CN=opensearch-endpoint,OU=OpenSearch HTTP,O=Oculox,C=SN")
        for issued_username, status in matches:
            if issued_username == username and status not in {"50", "60"}:
                remote.ejbca("ra", "revokeendentity", username, "9")
                remote.ejbca("ca", "createcrl", "Oculox OpenSearch CA")


def rejected_foreign_entity_update(remote):
    config = json.loads((remote.STATE / "config.json").read_text())
    role = config["role"]
    service = remote.ROLE_SERVICES[role][0]
    spec = remote.lifecycle().load_yaml(remote.MANIFEST)["certificates"][service]
    owner = "other-" + secrets.token_hex(6)
    username = f"oculox-foreign-owner-{secrets.token_hex(8)}"
    profile = remote.provision_scoped_profile(role, owner, service)
    dns, ips = remote.scoped_sans(role, owner, service, None, None)
    altname = ",".join(["dNSName=" + value for value in dns] + ["ipaddress=" + value for value in ips])
    remote.ejbca("ra", "addendentity", "--username", username,
                 "--dn", remote.scoped_subject(role, owner, service),
                 "--caname", remote.ROLE_CA[role], "--type", "1", "--token", "USERGENERATED",
                 "--password", secrets.token_urlsafe(24), "--certprofile", spec["profile"],
                 "--eeprofile", profile, "--altname", altname)
    try:
        rejected_scoped_identity(remote, service, field=None, username=username)
    finally:
        remote.ejbca("ra", "revokeendentity", username, "9")
        remote.ejbca("ca", "createcrl", remote.ROLE_CA[role])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="create and revoke disposable EJBCA identities")
    parser.add_argument("--role", choices=("all", "cluster", "collector"), default="all")
    args = parser.parse_args()
    if not args.run:
        parser.error("Use --run to authorize disposable test issuance and revocation")
    remote = load()
    original_root = remote.ROOT
    lib = remote.lifecycle()
    with tempfile.TemporaryDirectory(prefix="oculox-ejbca-live-") as directory:
        test_root = Path(directory)
        revoked_stages = set()
        remote.ROOT = test_root
        for role, service in (("cluster", "opensearch_node_1"), ("collector", "filebeat_client")):
            if args.role not in ("all", role):
                continue
            name = "test-" + secrets.token_hex(6)
            remote.STATE = test_root / role / "agent"
            bundle = test_root / role / "public"
            auth = argparse.Namespace(role=role, identity=name, csr=remote.STATE / "agent.csr",
                                     output=bundle, endpoint_ip="192.0.2.200" if role == "cluster" else None,
                                     endpoint_dns="search.example.internal" if role == "cluster" else None)
            authorized = False
            try:
                remote.init_agent(argparse.Namespace(role=role, identity=name, renew=False))
                remote.authorize_agent(auth)
                authorized = True
                remote.install_agent(argparse.Namespace(bundle=bundle, root_sha256=remote.fingerprint(bundle / "root.crt"), renew=False))
                remote.agent_status(argparse.Namespace(online=True))
                # Test before initial issuance: unique-DN checks must not mask authorization.
                rejected_foreign_entity_update(remote)
                print(f"LIVE_FOREIGN_END_ENTITY_UPDATE_DENIED_{role.upper()}=PASS", flush=True)
                remote.request_service(argparse.Namespace(service=service, install=False, restart=False))
                if role == "cluster":
                    for additional in remote.ROLE_SERVICES[role][1:]:
                        remote.request_service(argparse.Namespace(service=additional, install=False, restart=False))
                    endpoint = sorted((test_root / "dev/ejbca/generated/enrollments").glob(
                        "*/opensearch_endpoint/cert.crt"))[-1]
                    endpoint_sans = remote.openssl("x509", "-in", str(endpoint), "-noout", "-ext", "subjectAltName")
                    if "IP Address:192.0.2.200" not in endpoint_sans or "DNS:search.example.internal" not in endpoint_sans:
                        raise RuntimeError("Issued endpoint certificate lacks approved IP or DNS")
                    print("LIVE_CLUSTER_ENDPOINT_APPROVED_IP=PASS", flush=True)
                if role == "collector":
                    issued = sorted((test_root / "dev/ejbca/generated/enrollments").glob("*/filebeat_client/cert.crt"))[-1]
                    sans = remote.openssl("x509", "-in", str(issued), "-noout", "-ext", "subjectAltName")
                    if f"DNS:{name}" not in sans:
                        raise RuntimeError("Issued collector certificate lacks its fixed identity SAN")
                print(f"LIVE_ENROLL_{role.upper()}=PASS", flush=True)
                for bound_service in remote.ROLE_SERVICES[role]:
                    for field in ("CN", "OU", "O", "C"):
                        rejected_scoped_identity(remote, bound_service, field=field)
                print(f"LIVE_FOREIGN_DN_{role.upper()}=PASS", flush=True)
                if role == "cluster":
                    rejected_scoped_identity(remote, "opensearch_endpoint", foreign_dns=True)
                    print("LIVE_FOREIGN_ENDPOINT_DNS=PASS", flush=True)
                rejected_request(remote, "oculox-web-server", "Oculox Web CA")
                print(f"LIVE_FORBIDDEN_PROFILE_{role.upper()}=PASS", flush=True)
                if role == "cluster":
                    rejected_request(remote, "oculox-opensearch-node", "Oculox OpenSearch CA",
                                     san="DNS:opensearch-1")
                    print("LIVE_SHARED_CLUSTER_PROFILE_DENIED=PASS", flush=True)
                    rejected_foreign_cluster_endpoint(remote, lib)
                    print("LIVE_FOREIGN_CLUSTER_ENDPOINT=PASS", flush=True)
                if role == "collector":
                    rejected_foreign_collector_identity(remote, lib)
                    print("LIVE_FOREIGN_COLLECTOR_IDENTITY=PASS", flush=True)
                    rejected_request(remote, "oculox-filebeat-client", "Oculox Internal Services CA",
                                     san="DNS:filebeat,DNS:" + name)
                    print("LIVE_SHARED_FILEBEAT_PROFILE_DENIED=PASS", flush=True)
                old_key = (remote.STATE / "agent.key").read_bytes()
                remote.init_agent(argparse.Namespace(role=role, identity=name, renew=True))
                renewed = test_root / role / "renewed-public"
                remote.authorize_agent(argparse.Namespace(role=role, identity=name,
                    csr=remote.STATE / "pending.csr", output=renewed, renew=True,
                    endpoint_ip="192.0.2.200" if role == "cluster" else None,
                    endpoint_dns="search.example.internal" if role == "cluster" else None))
                remote.install_agent(argparse.Namespace(bundle=renewed,
                    root_sha256=remote.fingerprint(renewed / "root.crt"), renew=True))
                remote.agent_status(argparse.Namespace(online=True))
                if (remote.STATE / "agent.key").read_bytes() == old_key:
                    raise RuntimeError("Agent renewal did not rotate its private key")
                print(f"LIVE_AGENT_RENEWAL_{role.upper()}=PASS", flush=True)
                previous_state = sorted(remote.STATE.glob("backup-*"))[-1]
                remote.call(str(original_root / "oculox"), "pki-ca", "revoke-certificate",
                            "--certificate", str(previous_state / "agent.crt"), "--reason", "superseded",
                            "--output-crl", str(test_root / role / "old-agent.crl"))
                current_state = remote.STATE
                try:
                    remote.STATE = previous_state
                    rejected_scoped_identity(remote, service, field=None)
                finally:
                    remote.STATE = current_state
                print(f"LIVE_OLD_AGENT_CERTIFICATE_REVOKED_{role.upper()}=PASS", flush=True)
                prior = sorted((test_root / "dev/ejbca/generated/enrollments").glob(f"*/{service}/key.key"))[-1]
                old_service_key = prior.read_bytes()
                remote.request_service(argparse.Namespace(service=service, install=False, restart=False))
                current = sorted((test_root / "dev/ejbca/generated/enrollments").glob(f"*/{service}/key.key"))[-1]
                if current.read_bytes() == old_service_key:
                    raise RuntimeError("Service renewal did not rotate its local private key")
                print(f"LIVE_SERVICE_RENEWAL_{role.upper()}=PASS", flush=True)
                # Revoke this exact staged certificate and verify its serial is in the signed CRL.
                for number, issued_service in enumerate((service, "opensearch_endpoint") if role == "cluster" else (service,)):
                    stage = sorted((test_root / "dev/ejbca/generated/enrollments").glob(f"*/{issued_service}"))[-1]
                    crl = test_root / role / f"revoked-{number}.crl"
                    remote.call(str(original_root / "oculox"), "pki-ca", "revoke-certificate",
                                "--certificate", str(stage / "cert.crt"), "--reason", "superseded", "--output-crl", str(crl))
                    revoked_stages.add(stage / "cert.crt")
                    serial = remote.openssl("x509", "-in", str(stage / "cert.crt"), "-noout", "-serial").strip().split("=", 1)[1]
                    crl_text = remote.openssl("crl", "-in", str(crl), "-noout", "-text")
                    if serial.upper() not in crl_text.upper():
                        raise RuntimeError("Revoked serial absent from CRL")
                    remote.openssl("crl", "-in", str(crl), "-noout", "-verify", "-CAfile", str(bundle / "service-ca.crt"))
                print(f"LIVE_REVOCATION_{role.upper()}=PASS", flush=True)
                remote.revoke_agent(argparse.Namespace(role=role, identity=name, dry_run=False))
                rejected_request(remote, lib.load_yaml(remote.MANIFEST)["certificates"][service]["profile"], remote.ROLE_CA[role])
                print(f"LIVE_REVOKED_AGENT_{role.upper()}=PASS", flush=True)
            finally:
                if authorized or f"'{remote.role_name(role, name)}'" in remote.ejbca("roles", "listroles"):
                    # Deny new requests before cleaning up any issued test certificates.
                    remote.ejbca("roles", "removerole", remote.role_name(role, name))
                for certificate in (test_root / "dev/ejbca/generated/enrollments").glob("*/*/cert.crt"):
                    if certificate not in revoked_stages:
                        remote.call(str(original_root / "oculox"), "pki-ca", "revoke-certificate",
                                    "--certificate", str(certificate), "--reason", "superseded",
                                    "--output-crl", str(test_root / role / f"cleanup-{secrets.token_hex(8)}.crl"))
                        revoked_stages.add(certificate)
                if authorized:
                    members = lib.matching_end_entities(remote.agent_dn(role, name))
                    for username, status in members:
                        if status not in {"50", "60"}:
                            remote.ejbca("ra", "revokeendentity", username, "9")
                    remote.ejbca("ca", "createcrl", remote.AGENT_CA)
    print("EJBCA_LIVE_RESULT=PASS; production service certificates unchanged")


if __name__ == "__main__":
    main()
