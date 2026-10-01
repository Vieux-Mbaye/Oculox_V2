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


def rejected_request(remote, profile, ca):
    config = json.loads((remote.STATE / "config.json").read_text())
    context = ssl.create_default_context(cafile=str(remote.STATE / "api-ca.crt"))
    context.load_cert_chain(str(remote.STATE / "agent.crt"), str(remote.STATE / "agent.key"))
    csr = remote.STATE / "forbidden.csr"
    remote.openssl("req", "-new", "-key", str(remote.STATE / "agent.key"), "-subj", "/CN=forbidden-test", "-out", str(csr))
    body = {"certificate_request": csr.read_text(), "certificate_profile_name": profile,
            "end_entity_profile_name": profile + "-enroll-v3", "certificate_authority_name": ca,
            "username": "oculox-forbidden-" + secrets.token_hex(8), "password": secrets.token_urlsafe(24)}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context))
    request = urllib.request.Request(config["api_url"], data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    try:
        with opener.open(request, timeout=30):
            pass
    except urllib.error.HTTPError as exc:
        if exc.code in {401, 403}:
            return
        raise RuntimeError(f"Expected authorization denial, received HTTP {exc.code}") from exc
    raise RuntimeError("EJBCA issued a forbidden certificate")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="create and revoke disposable EJBCA identities")
    args = parser.parse_args()
    if not args.run:
        parser.error("Use --run to authorize disposable test issuance and revocation")
    remote = load()
    original_root = remote.ROOT
    lib = remote.lifecycle()
    with tempfile.TemporaryDirectory(prefix="oculox-ejbca-live-") as directory:
        test_root = Path(directory)
        remote.ROOT = test_root
        for role, service in (("cluster", "opensearch_node_1"), ("collector", "filebeat_client")):
            name = "test-" + secrets.token_hex(6)
            remote.STATE = test_root / role / "agent"
            bundle = test_root / role / "public"
            auth = argparse.Namespace(role=role, identity=name, csr=remote.STATE / "agent.csr", output=bundle)
            authorized = False
            try:
                remote.init_agent(argparse.Namespace(role=role, identity=name, renew=False))
                remote.authorize_agent(auth)
                authorized = True
                remote.install_agent(argparse.Namespace(bundle=bundle, root_sha256=remote.fingerprint(bundle / "root.crt"), renew=False))
                remote.agent_status(argparse.Namespace(online=True))
                remote.request_service(argparse.Namespace(service=service, install=False, restart=False))
                print(f"LIVE_ENROLL_{role.upper()}=PASS", flush=True)
                rejected_request(remote, "oculox-web-server", "Oculox Web CA")
                print(f"LIVE_FORBIDDEN_PROFILE_{role.upper()}=PASS", flush=True)
                old_key = (remote.STATE / "agent.key").read_bytes()
                remote.init_agent(argparse.Namespace(role=role, identity=name, renew=True))
                renewed = test_root / role / "renewed-public"
                remote.authorize_agent(argparse.Namespace(role=role, identity=name,
                    csr=remote.STATE / "pending.csr", output=renewed, renew=True))
                remote.install_agent(argparse.Namespace(bundle=renewed,
                    root_sha256=remote.fingerprint(renewed / "root.crt"), renew=True))
                remote.agent_status(argparse.Namespace(online=True))
                if (remote.STATE / "agent.key").read_bytes() == old_key:
                    raise RuntimeError("Agent renewal did not rotate its private key")
                print(f"LIVE_AGENT_RENEWAL_{role.upper()}=PASS", flush=True)
                # Revoke this exact staged certificate and verify its serial is in the signed CRL.
                stage = sorted((test_root / "dev/ejbca/generated/enrollments").glob(f"*/{service}"))[-1]
                crl = test_root / role / "revoked.crl"
                remote.call(str(original_root / "oculox"), "pki-ca", "revoke-certificate",
                            "--certificate", str(stage / "cert.crt"), "--reason", "superseded", "--output-crl", str(crl))
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
                if authorized:
                    # Removing the role denies enrollment even if later cleanup fails.
                    remote.ejbca("roles", "removerole", remote.role_name(role, name))
                    members = lib.matching_end_entities(remote.agent_dn(role, name))
                    for username, status in members:
                        if status not in {"50", "60"}:
                            remote.ejbca("ra", "revokeendentity", username, "9")
                    remote.ejbca("ca", "createcrl", remote.AGENT_CA)
    print("EJBCA_LIVE_RESULT=PASS; production service certificates unchanged")


if __name__ == "__main__":
    main()
