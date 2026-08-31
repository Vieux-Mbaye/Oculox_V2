#!/usr/bin/env python3

import hashlib
import os
import socket
import subprocess
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
CONFIGURE = ROOT / "dev/scripts/configure-public-endpoint.py"
GENERATE = ROOT / "dev/scripts/generate-web-pki.sh"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class PortableWebIdentityTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.identity = self.base / "public-endpoint.env"
        self.keycloak = self.base / "keycloak.env"
        self.deployment = self.base / "deployment.env"
        self.pki = self.base / "web-pki"
        self.certs = self.base / "nginx-certs"
        self.trust = self.base / "ca-trust"
        self.bundle = self.base / "web-trust"
        self.keycloak.write_text(
            "KEYCLOAK_AUTH_REALM=master\n"
            "KEYCLOAK_AUTH_URL=\n"
            "KEYCLOAK_CLIENT_ID=oculox-portal\n"
            "KEYCLOAK_CLIENT_SECRET=secret-that-must-not-change\n"
            "KEYCLOAK_SSL_VERIFY=false\n"
            "KC_HOSTNAME=\n"
            "KC_HOSTNAME_STRICT=false\n"
        )
        self.deployment.write_text("OCULOX_ROLE=principal\nOCULOX_SERVER_NAME=old\n")

    def tearDown(self):
        self.temp.cleanup()

    def configure(self, host: str, check: bool = True):
        return subprocess.run(
            [
                str(CONFIGURE),
                "--public-host",
                host,
                "--output",
                str(self.identity),
                "--keycloak-env",
                str(self.keycloak),
                "--deployment-env",
                str(self.deployment),
            ],
            text=True,
            capture_output=True,
            check=check,
        )

    def generate(self, extra=None):
        command = [
            str(GENERATE),
            "--identity-env",
            str(self.identity),
            "--pki-dir",
            str(self.pki),
            "--cert-dir",
            str(self.certs),
            "--trust-dir",
            str(self.trust),
            "--bundle-dir",
            str(self.bundle),
        ]
        command.extend(extra or [])
        return subprocess.run(command, text=True, capture_output=True, check=True)

    def test_ipv4_dns_and_ipv6_rendering(self):
        cases = {
            "192.0.2.25": ("ipv4", "IP:192.0.2.25", "https://192.0.2.25"),
            "Core.Example.Internal": (
                "dns",
                "DNS:core.example.internal",
                "https://core.example.internal",
            ),
            "2001:db8::25": ("ipv6", "IP:2001:db8::25", "https://[2001:db8::25]"),
        }
        for host, expected in cases.items():
            with self.subTest(host=host):
                self.configure(host)
                content = self.identity.read_text()
                self.assertIn(f"OCULOX_PUBLIC_IDENTITY_TYPE={expected[0]}", content)
                self.assertIn(f"OCULOX_PUBLIC_SAN={expected[1]}", content)
                self.assertIn(f"OCULOX_PUBLIC_URL={expected[2]}", content)
                self.assertIn(f"KEYCLOAK_AUTH_URL={expected[2]}/keycloak", self.keycloak.read_text())

    def test_invalid_public_identities_are_rejected(self):
        for value in ("", "http://core.example", "https://core.example", "core.example/path", "bad_name"):
            with self.subTest(value=value):
                result = self.configure(value, check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Invalid public identity", result.stderr)

    def test_second_render_preserves_client_secret_and_files(self):
        self.configure("core.example.internal")
        first_identity = self.identity.read_bytes()
        first_keycloak = self.keycloak.read_bytes()
        first_mtime = self.keycloak.stat().st_mtime_ns
        self.configure("core.example.internal")
        self.assertEqual(first_identity, self.identity.read_bytes())
        self.assertEqual(first_keycloak, self.keycloak.read_bytes())
        self.assertEqual(first_mtime, self.keycloak.stat().st_mtime_ns)
        self.assertIn("KEYCLOAK_CLIENT_SECRET=secret-that-must-not-change", self.keycloak.read_text())

    def test_development_pki_is_valid_idempotent_and_public_bundle_has_no_key(self):
        self.configure("127.0.0.1")
        self.generate()
        subprocess.run(
            ["openssl", "verify", "-CAfile", str(self.pki / "ca.crt"), str(self.pki / "server.crt")],
            check=True,
            capture_output=True,
            text=True,
        )
        check = subprocess.run(
            ["openssl", "x509", "-in", str(self.pki / "server.crt"), "-noout", "-checkip", "127.0.0.1"],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("does match certificate", check.stdout)
        self.assertEqual(self.certs.joinpath("key.pem").stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.pki.joinpath("ca.key").stat().st_mode & 0o777, 0o600)
        self.assertFalse(any(path.suffix == ".key" or path.name.endswith("key.pem") for path in self.bundle.iterdir()))
        subprocess.run(["sha256sum", "-c", "SHA256SUMS"], cwd=self.bundle, check=True, capture_output=True)

        ca_key_hash = digest(self.pki / "ca.key")
        server_key_hash = digest(self.pki / "server.key")
        self.generate()
        self.assertEqual(ca_key_hash, digest(self.pki / "ca.key"))
        self.assertEqual(server_key_hash, digest(self.pki / "server.key"))

    def test_identity_change_reissues_leaf_but_preserves_deployment_ca(self):
        self.configure("192.0.2.25")
        self.generate()
        ca_key_hash = digest(self.pki / "ca.key")
        first_server = digest(self.pki / "server.crt")
        self.configure("core.example.internal")
        self.generate()
        self.assertEqual(ca_key_hash, digest(self.pki / "ca.key"))
        self.assertNotEqual(first_server, digest(self.pki / "server.crt"))
        check = subprocess.run(
            ["openssl", "x509", "-in", str(self.pki / "server.crt"), "-noout", "-checkhost", "core.example.internal"],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("does match certificate", check.stdout)

    def test_force_rotates_ca_without_removing_unrelated_files(self):
        self.configure("192.0.2.25")
        self.generate()
        marker = self.pki / "operator-note.txt"
        marker.write_text("keep\n")
        first_ca = digest(self.pki / "ca.crt")
        self.generate(["--force"])
        self.assertNotEqual(first_ca, digest(self.pki / "ca.crt"))
        self.assertEqual(marker.read_text(), "keep\n")

    def test_curl_requires_the_generated_ca(self):
        self.configure("127.0.0.1")
        self.generate()
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        server = subprocess.Popen(
            [
                "openssl",
                "s_server",
                "-quiet",
                "-www",
                "-accept",
                f"127.0.0.1:{port}",
                "-cert",
                str(self.pki / "server.crt"),
                "-key",
                str(self.pki / "server.key"),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            time.sleep(0.3)
            rejected = subprocess.run(
                ["curl", "--silent", "--show-error", f"https://127.0.0.1:{port}/"],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(rejected.returncode, 0)
            accepted = subprocess.run(
                [
                    "curl",
                    "--silent",
                    "--show-error",
                    "--cacert",
                    str(self.bundle / "oculox-web-ca.crt"),
                    f"https://127.0.0.1:{port}/",
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(accepted.returncode, 0, accepted.stderr)
            self.assertIn("s_server", accepted.stdout)
        finally:
            server.terminate()
            server.wait(timeout=5)

    def test_provided_certificate_mode_validates_and_installs_material(self):
        self.configure("core.example.internal")
        self.generate()
        provided_certs = self.base / "provided-certs"
        provided_trust = self.base / "provided-trust"
        provided_bundle = self.base / "provided-bundle"
        subprocess.run(
            [
                str(GENERATE),
                "--identity-env",
                str(self.identity),
                "--mode",
                "provided",
                "--certificate",
                str(self.pki / "server.crt"),
                "--private-key",
                str(self.pki / "server.key"),
                "--ca-certificate",
                str(self.pki / "ca.crt"),
                "--cert-dir",
                str(provided_certs),
                "--trust-dir",
                str(provided_trust),
                "--bundle-dir",
                str(provided_bundle),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(digest(self.pki / "server.crt"), digest(provided_certs / "cert.pem"))
        self.assertEqual(provided_certs.joinpath("key.pem").stat().st_mode & 0o777, 0o600)
        self.assertFalse(any("key" in path.name for path in provided_bundle.iterdir()))

    def test_provided_certificate_with_wrong_san_is_rejected(self):
        self.configure("first.example.internal")
        self.generate()
        self.configure("second.example.internal")
        result = subprocess.run(
            [
                str(GENERATE),
                "--identity-env",
                str(self.identity),
                "--mode",
                "provided",
                "--certificate",
                str(self.pki / "server.crt"),
                "--private-key",
                str(self.pki / "server.key"),
                "--ca-certificate",
                str(self.pki / "ca.crt"),
                "--cert-dir",
                str(self.base / "rejected-certs"),
                "--trust-dir",
                str(self.base / "rejected-trust"),
                "--bundle-dir",
                str(self.base / "rejected-bundle"),
            ],
            text=True,
            capture_output=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("failed certificate, SAN, chain or key validation", result.stderr)

    def test_oculox_prepare_calls_identity_before_web_pki(self):
        launcher = (ROOT / "oculox").read_text()
        identity_call = launcher.index("configure-public-endpoint.py")
        pki_call = launcher.index("generate-web-pki.sh")
        self.assertLess(identity_call, pki_call)

    def test_implementation_does_not_embed_lab_addresses(self):
        sources = "\n".join(
            path.read_text()
            for path in (CONFIGURE, GENERATE, ROOT / "config/keycloak.env.example")
        )
        for address in ("192.168.1.174", "192.168.1.200", "192.168.1.241"):
            self.assertNotIn(address, sources)


if __name__ == "__main__":
    unittest.main(verbosity=2)
