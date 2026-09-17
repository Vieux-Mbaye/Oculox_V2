#!/usr/bin/env python3

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
CONFIGURE = ROOT / "dev/scripts/keycloak/configure-dashboards-oidc.py"
DASHBOARDS_CONFIG = ROOT / "dashboards/opensearch_dashboards.yml"
DASHBOARDS_ENTRYPOINT = ROOT / "dashboards/scripts/docker_entrypoint.sh"
LAUNCHER = ROOT / "oculox"


def values(path: Path) -> dict[str, str]:
    return {
        key: value
        for line in path.read_text().splitlines()
        if "=" in line and not line.startswith("#")
        for key, value in [line.split("=", 1)]
    }


class DashboardsOidcActivationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.dashboards = self.base / "dashboards.env"
        self.keycloak = self.base / "keycloak.env"
        self.public = self.base / "public-endpoint.env"
        self.report = self.base / "realm-report.json"
        self.dashboards.write_text("DASHBOARDS_URL=http://dashboards:5601/dashboards\nDASHBOARDS_AUTH_TYPE=basicauth\n")
        self.keycloak.write_text(
            "KEYCLOAK_AUTH_REALM=oculox\n"
            "KEYCLOAK_AUTH_URL=https://core.example.internal/keycloak\n"
            "KEYCLOAK_DASHBOARDS_CLIENT_ID=oculox-dashboards\n"
            "KEYCLOAK_DASHBOARDS_CLIENT_SECRET=dashboards-secret-that-is-long-enough\n"
            "KEYCLOAK_DASHBOARDS_REDIRECT_URI=https://core.example.internal:5601/dashboards/auth/openid/login\n"
            "KEYCLOAK_SSL_VERIFY=true\n"
        )
        self.public.write_text(
            "OCULOX_PUBLIC_HOST=core.example.internal\n"
            "OCULOX_PUBLIC_URL=https://core.example.internal\n"
            "OCULOX_KEYCLOAK_URL=https://core.example.internal/keycloak\n"
        )

    def tearDown(self):
        self.temp.cleanup()

    def run_configure(self, action: str, check=True):
        return subprocess.run(
            [
                str(CONFIGURE),
                action,
                "--dashboards-env",
                str(self.dashboards),
                "--keycloak-env",
                str(self.keycloak),
                "--public-endpoint-env",
                str(self.public),
                "--realm-report",
                str(self.report),
            ],
            text=True,
            capture_output=True,
            check=check,
        )

    def test_activation_requires_successful_keycloak_realm(self):
        result = self.run_configure("activate", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("keycloak provision first", result.stderr)
        self.report.write_text(json.dumps({"result": "FAIL"}))
        result = self.run_configure("activate", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("realm report is not PASS", result.stderr)

    def test_activation_sets_dashboards_to_openid(self):
        self.report.write_text(json.dumps({"result": "PASS"}))
        self.run_configure("activate")
        self.assertEqual(values(self.dashboards)["DASHBOARDS_AUTH_TYPE"], "openid")
        verify = self.run_configure("verify")
        self.assertIn('"result": "PASS"', verify.stdout)

    def test_deactivation_returns_dashboards_to_basic(self):
        self.report.write_text(json.dumps({"result": "PASS"}))
        self.run_configure("activate")
        self.run_configure("deactivate")
        self.assertEqual(values(self.dashboards)["DASHBOARDS_AUTH_TYPE"], "basicauth")

    def test_dashboards_template_and_entrypoint_support_openid(self):
        config = DASHBOARDS_CONFIG.read_text(encoding="utf-8")
        entrypoint = DASHBOARDS_ENTRYPOINT.read_text(encoding="utf-8")
        self.assertIn('type: "_MALCOLM_DASHBOARDS_AUTH_TYPE_"', config)
        self.assertIn("DASHBOARDS_AUTH_TYPE", entrypoint)
        self.assertIn("KEYCLOAK_DASHBOARDS_CONNECT_URL", entrypoint)
        self.assertIn("opensearch_security.openid.connect_url", entrypoint)
        self.assertIn("opensearch_security.openid.client_id", entrypoint)
        self.assertIn("opensearch_security.openid.client_secret", entrypoint)
        self.assertIn("opensearch_security.openid.base_redirect_url", entrypoint)

    def test_launcher_exposes_dashboards_oidc_commands(self):
        launcher = LAUNCHER.read_text(encoding="utf-8")
        self.assertIn("keycloak activate-dashboards", launcher)
        self.assertIn("configure-dashboards-oidc.py activate", launcher)
        self.assertIn("keycloak deactivate-dashboards", launcher)
        self.assertIn("keycloak verify-dashboards", launcher)


if __name__ == "__main__":
    unittest.main(verbosity=2)
