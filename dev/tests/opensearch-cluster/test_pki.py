#!/usr/bin/env python3

import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
from urllib.parse import urlparse


PROJECT_DIR = Path(__file__).resolve().parents[3]
PKI_DIR = PROJECT_DIR / "dev/generated/opensearch-cluster/pki"
COMPOSE_FILE = PROJECT_DIR / "dev/compose/opensearch-cluster/compose.yml"
ENV_FILE = Path(os.environ.get(
    "OPENSEARCH_CLUSTER_ENV_FILE",
    PROJECT_DIR / "dev/config/opensearch-cluster/cluster.env.example",
))
CONFIG_FILE = PROJECT_DIR / "dev/config/opensearch-cluster/opensearch.yml"
EXPECTED_NODES = ("opensearch-1", "opensearch-2", "opensearch-3")
def expected_endpoint_ip() -> str:
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        if line.startswith("OPENSEARCH_CLUSTER_ENDPOINT="):
            endpoint = line.split("=", 1)[1]
            hostname = urlparse(endpoint).hostname
            assert hostname, f"Endpoint invalide: {endpoint}"
            return hostname
    raise AssertionError("OPENSEARCH_CLUSTER_ENDPOINT absent")


def run(*args: str, input_text: str | None = None) -> str:
    result = subprocess.run(
        args,
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(f"Commande en echec: {' '.join(args)}\n{result.stdout}")
    return result.stdout


def certificate_text(path: Path) -> str:
    return run("openssl", "x509", "-in", str(path), "-noout", "-text")


def public_key_digest_from_key(path: Path) -> str:
    public_key = run("openssl", "pkey", "-in", str(path), "-pubout")
    return hashlib.sha256(public_key.encode()).hexdigest()


def public_key_digest_from_cert(path: Path) -> str:
    public_key = run("openssl", "x509", "-in", str(path), "-pubkey", "-noout")
    return hashlib.sha256(public_key.encode()).hexdigest()


def assert_private_key(path: Path) -> None:
    assert path.is_file(), f"Cle absente: {path}"
    first_line = path.read_text(encoding="ascii").splitlines()[0]
    assert first_line == "-----BEGIN PRIVATE KEY-----", f"Cle non PKCS#8: {path}"
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode & 0o077 == 0, f"Permissions trop ouvertes ({mode:o}): {path}"


def assert_pair(cert: Path, key: Path) -> str:
    assert cert.is_file(), f"Certificat absent: {cert}"
    assert_private_key(key)
    key_digest = public_key_digest_from_key(key)
    assert key_digest == public_key_digest_from_cert(cert), f"Couple cert/cle incoherent: {cert}"
    return key_digest


def assert_verify(cert: Path, purpose: str, identity_flag: str | None = None, identity: str | None = None) -> None:
    command = [
        "openssl",
        "verify",
        "-CAfile",
        str(PKI_DIR / "ca/ca.crt"),
        "-purpose",
        purpose,
    ]
    if identity_flag and identity:
        command.extend((identity_flag, identity))
    command.append(str(cert))
    output = run(*command)
    assert output.rstrip().endswith(": OK"), output


def compose_config() -> dict:
    output = run(
        "docker",
        "compose",
        "--env-file",
        str(ENV_FILE),
        "-f",
        str(COMPOSE_FILE),
        "config",
        "--format",
        "json",
    )
    return json.loads(output)


def main() -> int:
    endpoint_ip = expected_endpoint_ip()
    assert (PKI_DIR / ".oculox-opensearch-pki").is_file()
    ca_cert = PKI_DIR / "ca/ca.crt"
    ca_key = PKI_DIR / "ca/ca.key"
    assert_pair(ca_cert, ca_key)
    ca_text = certificate_text(ca_cert)
    assert "CA:TRUE" in ca_text
    assert "Certificate Sign" in ca_text

    key_digests: set[str] = {public_key_digest_from_key(ca_key)}
    for node in EXPECTED_NODES:
        node_dir = PKI_DIR / "nodes" / node
        cert = node_dir / "node.crt"
        key = node_dir / "node.key"
        assert (node_dir / "ca.crt").read_bytes() == ca_cert.read_bytes()
        digest = assert_pair(cert, key)
        assert digest not in key_digests, f"Cle reutilisee pour {node}"
        key_digests.add(digest)
        text = certificate_text(cert)
        assert f"DNS:{node}" in text
        assert "TLS Web Server Authentication" in text
        assert "TLS Web Client Authentication" in text
        assert_verify(cert, "sslserver", "-verify_hostname", node)
        assert_verify(cert, "sslclient")
        subject = run(
            "openssl", "x509", "-in", str(cert), "-noout", "-subject", "-nameopt", "RFC2253"
        )
        assert f"CN={node},OU=OpenSearch Nodes,O=Oculox,C=SN" in subject

    endpoint_cert = PKI_DIR / "endpoint/endpoint.crt"
    endpoint_key = PKI_DIR / "endpoint/endpoint.key"
    endpoint_digest = assert_pair(endpoint_cert, endpoint_key)
    assert endpoint_digest not in key_digests, "Cle endpoint reutilisee"
    key_digests.add(endpoint_digest)
    endpoint_text = certificate_text(endpoint_cert)
    assert f"IP Address:{endpoint_ip}" in endpoint_text
    assert "TLS Web Server Authentication" in endpoint_text
    assert "TLS Web Client Authentication" not in endpoint_text
    assert_verify(endpoint_cert, "sslserver", "-verify_ip", endpoint_ip)

    admin_cert = PKI_DIR / "admin/admin.crt"
    admin_key = PKI_DIR / "admin/admin.key"
    admin_digest = assert_pair(admin_cert, admin_key)
    assert admin_digest not in key_digests, "Cle administrateur reutilisee"
    admin_text = certificate_text(admin_cert)
    assert "TLS Web Client Authentication" in admin_text
    assert "TLS Web Server Authentication" not in admin_text
    assert_verify(admin_cert, "sslclient")
    admin_subject = run(
        "openssl", "x509", "-in", str(admin_cert), "-noout", "-subject", "-nameopt", "RFC2253"
    )
    assert "CN=oculox-opensearch-admin,OU=OpenSearch Administration,O=Oculox,C=SN" in admin_subject
    client_ca = PKI_DIR / "client-trust/oculox-opensearch-ca.crt"
    assert client_ca.read_bytes() == ca_cert.read_bytes()

    config_text = CONFIG_FILE.read_text(encoding="utf-8")
    for node in EXPECTED_NODES:
        assert f'"CN={node},OU=OpenSearch Nodes,O=Oculox,C=SN"' in config_text
    assert '"CN=oculox-opensearch-admin,OU=OpenSearch Administration,O=Oculox,C=SN"' in config_text
    assert "pemcert_filepath: certs/node.crt" in config_text
    assert "pemkey_filepath: certs/node.key" in config_text
    assert "pemtrustedcas_filepath: certs/ca.crt" in config_text
    assert "clientauth_mode: OPTIONAL" in config_text
    assert "enforce_hostname_verification: true" in config_text

    compose = compose_config()
    compose_source = COMPOSE_FILE.read_text(encoding="utf-8")
    assert "--insecure" not in compose_source
    assert "--cacert /usr/share/opensearch/config/certs/ca.crt" in compose_source
    for node in EXPECTED_NODES:
        service = compose["services"][node]
        transport_network = service["networks"].get("cluster-transport") or {}
        assert "ipv4_address" not in transport_network
        assert str(service["environment"]["OPENSEARCH_SKIP_SELF_SIGNED_KEY_GEN"]).lower() == "true"
        mounts = {mount["target"]: mount for mount in service["volumes"]}
        cert_mount = mounts["/usr/share/opensearch/config/certs"]
        assert cert_mount["read_only"] is True
        assert cert_mount["source"].endswith(f"/pki/nodes/{node}")
        assert mounts["/usr/share/opensearch/config/opensearch.yml"]["read_only"] is True
        assert mounts["/usr/local/bin/setup-post-start.sh"]["read_only"] is True

    git_root = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=PROJECT_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if git_root.returncode == 0:
        tracked = run("git", "ls-files", "dev/generated/opensearch-cluster/pki")
        assert tracked.strip() == "", "Des secrets PKI sont suivis par Git"

    print("ca_chain=PASS")
    print("node_certificates=3/3 PASS")
    print(f"endpoint_san=IP:{endpoint_ip} PASS")
    print("admin_certificate=PASS")
    print("unique_leaf_private_keys=5/5 PASS")
    print("compose_read_only_mounts=3/3 PASS")
    print("healthcheck_tls_verification=PASS")
    print(
        "generated_pki_git_tracking=NONE PASS"
        if git_root.returncode == 0
        else "generated_pki_git_tracking=NOT_APPLICABLE_DEPLOYED_TREE PASS"
    )
    print("client_trust_bundle=PASS")
    print("PKI_TEST_RESULT=PASS")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, OSError, ValueError) as error:
        print(f"PKI_TEST_RESULT=FAIL: {error}", file=sys.stderr)
        raise SystemExit(1)
