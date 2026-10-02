"""Regression checks for TLS validation against the configured cluster."""
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts/pki-validate-services.py"
SPEC = importlib.util.spec_from_file_location("pki_service_validation", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

LIFECYCLE_SPEC = importlib.util.spec_from_file_location("pki_lifecycle", MODULE_PATH.parent / "ejbca/pki-lifecycle.py")
LIFECYCLE = importlib.util.module_from_spec(LIFECYCLE_SPEC)
sys.modules[LIFECYCLE_SPEC.name] = LIFECYCLE
LIFECYCLE_SPEC.loader.exec_module(LIFECYCLE)


class ServiceValidationTests(unittest.TestCase):
    def test_global_validation_fails_when_configured_ejbca_is_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env = root / "dev/ejbca/generated/ejbca.env"
            env.parent.mkdir(parents=True)
            env.write_text("OCULOX_EJBCA_HTTPS_PORT=18443\n")
            failure = subprocess.CompletedProcess([], 22, "", "HTTP 500")
            with patch.object(MODULE, "PROJECT_DIR", root), patch.object(MODULE, "run", return_value=failure):
                checks = MODULE.ejbca_required()
            self.assertEqual(checks[0].status, "FAIL")
            self.assertIn("HTTP 500", checks[0].detail)

    def test_global_validation_skips_ejbca_when_external_pki_is_used(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(MODULE, "PROJECT_DIR", Path(directory)), patch.object(MODULE, "run") as run:
                self.assertEqual(MODULE.ejbca_required(), [])
            run.assert_not_called()

    def test_first_certificate_install_does_not_require_the_rest_of_the_platform(self):
        with tempfile.TemporaryDirectory() as directory:
            cert = Path(directory) / "ca.crt"
            subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "365",
                "-subj", "/CN=Bootstrap test CA", "-keyout", str(cert.with_suffix(".key")), "-out", str(cert),
                "-addext", "basicConstraints=critical,CA:TRUE"], capture_output=True, check=True)
            with patch.object(LIFECYCLE, "run", side_effect=AssertionError("global platform audit during bootstrap")):
                LIFECYCLE.run_validation({"first_ca": {"type": "ca", "cert": str(cert), "expected_ca": True}})

    def test_rollback_preserves_private_pem_permissions_and_removes_new_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            key = root / "key.pem"
            key.write_text("old private key")
            key.chmod(0o600)
            cert = root / "new-cert.crt"
            backup = LIFECYCLE.backup_all({"web": {"key": str(key), "cert": str(cert)}}, root / "backup")
            key.write_text("replacement")
            cert.write_text("new certificate")
            LIFECYCLE.restore_all(backup)
            self.assertEqual(key.read_text(), "old private key")
            self.assertEqual(key.stat().st_mode & 0o777, 0o600)
            self.assertFalse(cert.exists())

    def test_incompatible_trust_is_rejected_before_install(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "dev/generated/opensearch-clients").mkdir(parents=True)
            target = root / "nginx/ca-trust/oculox-opensearch-ca.crt"
            specs = {"remote": {"type": "ca", "cert": str(target)}}
            with patch.object(LIFECYCLE, "PROJECT_DIR", root), patch.object(LIFECYCLE, "parse_env_reference", return_value="https://cluster.example:9200"), patch.object(LIFECYCLE, "run", return_value=subprocess.CompletedProcess([], 60, "", "untrusted CA")), patch.object(LIFECYCLE, "install_one") as install:
                with self.assertRaises(LIFECYCLE.LifecycleError):
                    LIFECYCLE.maybe_install({"remote": root / "staged"}, specs, True, False)
            install.assert_not_called()

    def test_distributed_trust_is_backed_up(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            trust = root / "trust.crt"
            trust.write_text("previous trust")
            result = LIFECYCLE.backup_all({"ca": {"trust_distribution": [str(trust)]}}, root / "backup")
            self.assertEqual(result[str(trust)].read_text(), "previous trust")

    def test_tls_error_is_failure(self):
        with patch.object(MODULE, "run", return_value=subprocess.CompletedProcess([], 60, "", "certificate verify failed")) as run:
            result = MODULE.curl_check("opensearch", "https://cluster.example:9200")
        self.assertEqual(result.status, "FAIL")
        self.assertIn("--cacert", run.call_args.args[0])
        self.assertNotIn("-ksS", run.call_args.args[0])

    def test_remote_endpoint_is_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config").mkdir()
            (root / "config/opensearch.env").write_text("OPENSEARCH_URL=https://cluster.example:9200\n")
            with patch.object(MODULE, "PROJECT_DIR", root), patch.object(MODULE, "pki_audit_required", return_value=MODULE.Check("pki", "OK", "")), patch.object(MODULE, "curl_check", return_value=MODULE.Check("opensearch", "OK", "")) as check:
                MODULE.validate_opensearch()
            self.assertEqual(check.call_args.args[1], "https://cluster.example:9200/_cluster/health")


if __name__ == "__main__":
    unittest.main()
