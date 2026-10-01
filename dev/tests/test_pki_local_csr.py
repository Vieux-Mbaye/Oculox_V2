"""Regression tests for local key custody and external PKI protection."""
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("local_csr_lifecycle", ROOT / "dev/scripts/ejbca/pki-lifecycle.py")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class LocalKeyTests(unittest.TestCase):
    def test_only_public_csr_is_transferred(self):
        commands = []
        real_run = MODULE.run

        def run(command, **kwargs):
            commands.append(command)
            if command[0] == "docker":
                return subprocess.CompletedProcess(command, 0, "", "")
            return real_run(command, **kwargs)

        with tempfile.TemporaryDirectory() as directory:
            with patch.object(MODULE, "run", side_effect=run), patch.object(MODULE, "ejbca") as ejbca, patch.object(MODULE, "docker_exec"), patch.object(MODULE, "docker_cp_from", side_effect=lambda remote, local: local.write_text("issued")), patch.object(MODULE, "export_ca_bundle"):
                stage = MODULE.enroll_one("client", {"type": "client", "profile": "oculox-filebeat-client"}, {"issuer_display_name": "Test CA"}, Path(directory), False)
            self.assertEqual((stage / "key.key").stat().st_mode & 0o777, 0o600)
            self.assertEqual(stage.stat().st_mode & 0o777, 0o700)
            self.assertFalse((stage / "identity.p12").exists())
            metadata = json.loads((stage / "metadata.json").read_text())
            self.assertEqual(metadata["key_origin"], "local")
            verified = subprocess.run(["openssl", "req", "-in", str(stage / "request.csr"), "-verify", "-noout"], capture_output=True)
            self.assertEqual(verified.returncode, 0)
            transferred = [cmd[2] for cmd in commands if cmd[:2] == ["docker", "cp"]]
            self.assertEqual(transferred, [str(stage / "request.csr")])
            self.assertTrue(any(call.args[0] == "createcert" for call in ejbca.call_args_list))
            self.assertFalse(any(call.args[0] == "batch" for call in ejbca.call_args_list))

    def test_existing_key_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            stage = Path(directory) / "client"
            stage.mkdir()
            (stage / "key.key").write_text("previous key")
            with self.assertRaises(FileExistsError):
                MODULE.enroll_one("client", {"type": "client", "profile": "oculox-filebeat-client"}, {"issuer_display_name": "Test CA"}, Path(directory), False)
            self.assertEqual((stage / "key.key").read_text(), "previous key")

    def test_external_web_certificate_never_triggers_local_ca(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            certs = root / "certs"
            certs.mkdir()
            (certs / "cert.pem").write_text("invalid external certificate")
            identity = root / "identity.env"
            identity.write_text("OCULOX_PUBLIC_HOST=10.0.0.1\nOCULOX_PUBLIC_IDENTITY_TYPE=ipv4\nOCULOX_PUBLIC_SAN=IP:10.0.0.1\nOCULOX_PUBLIC_URL=https://10.0.0.1\n")
            command = [str(ROOT / "dev/scripts/generate-web-pki.sh"), "--identity-env", str(identity), "--pki-dir", str(root / "pki"), "--cert-dir", str(certs), "--trust-dir", str(root / "trust"), "--bundle-dir", str(root / "bundle")]
            for options in ([], ["--force"]):
                result = subprocess.run(command + options, capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((root / "pki/ca.key").exists())
                self.assertEqual((certs / "cert.pem").read_text(), "invalid external certificate")
            # Stale development CA material must not authorize a downgrade.
            (root / "pki").mkdir()
            (root / "pki/ca.key").write_text("stale development key")
            (root / "pki/ca.crt").write_text("stale development CA")
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual((root / "pki/ca.key").read_text(), "stale development key")
            self.assertEqual((certs / "cert.pem").read_text(), "invalid external certificate")


if __name__ == "__main__":
    unittest.main()
