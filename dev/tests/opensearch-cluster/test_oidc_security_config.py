#!/usr/bin/env python3

import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]
RENDERER = ROOT / "dev/scripts/opensearch-cluster/render-oidc-security-config.py"
UPDATER = ROOT / "dev/scripts/opensearch-cluster/update-security-config.sh"
MANAGER = ROOT / "dev/scripts/opensearch-cluster/manage-cluster.sh"
SOURCE = ROOT / "dev/config/opensearch-cluster/security"


class OidcSecurityConfigTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.source = self.base / "source"
        self.output = self.base / "output"
        self.source.mkdir()
        for name in ("config.yml", "roles.yml", "roles_mapping.yml"):
            (self.source / name).write_text((SOURCE / name).read_text(encoding="utf-8"), encoding="utf-8")
        (self.source / "internal_users.yml").write_text("---\n_meta:\n  type: internalusers\n  config_version: 2\n", encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_renderer_adds_oidc_domain_and_preserves_basic(self):
        subprocess.run(
            [
                str(RENDERER),
                "--source",
                str(self.source),
                "--output",
                str(self.output),
                "--keycloak-auth-url",
                "https://core.example.internal/keycloak",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        config = yaml.safe_load((self.output / "config.yml").read_text(encoding="utf-8"))
        mappings = yaml.safe_load((self.output / "roles_mapping.yml").read_text(encoding="utf-8"))
        authc = config["config"]["dynamic"]["authc"]
        self.assertEqual(set(authc), {"openid_auth_domain", "basic_internal_auth_domain"})
        self.assertEqual(authc["openid_auth_domain"]["http_authenticator"]["type"], "openid")
        self.assertFalse(authc["openid_auth_domain"]["http_authenticator"]["challenge"])
        self.assertEqual(
            authc["openid_auth_domain"]["http_authenticator"]["config"]["openid_connect_url"],
            "https://core.example.internal/keycloak/realms/oculox/.well-known/openid-configuration",
        )
        self.assertEqual(
            authc["openid_auth_domain"]["http_authenticator"]["config"]["required_audience"],
            "oculox-dashboards",
        )
        self.assertEqual(
            authc["openid_auth_domain"]["http_authenticator"]["config"]["roles_key"],
            "roles",
        )
        self.assertEqual(
            authc["openid_auth_domain"]["http_authenticator"]["config"]["openid_connect_idp"],
            {
                "enable_ssl": True,
                "verify_hostnames": True,
                "pemtrustedcas_filepath": "/usr/share/opensearch/config/idp-trust/keycloak-ca.crt",
            },
        )
        self.assertEqual(authc["openid_auth_domain"]["authentication_backend"]["type"], "noop")
        self.assertFalse(authc["basic_internal_auth_domain"]["http_authenticator"]["challenge"])
        self.assertIn("oculox_platform_admin", mappings["all_access"]["backend_roles"])
        self.assertIn("admin", mappings["all_access"]["backend_roles"])
        self.assertIn("read_access", mappings["dashboards_read_access"]["backend_roles"])
        self.assertIn("dashboards_read_access", mappings["dashboards_read_access"]["backend_roles"])
        self.assertIn("read_write_access", mappings["dashboards_read_write_access"]["backend_roles"])

    def test_renderer_rejects_non_https_keycloak_url(self):
        result = subprocess.run(
            [
                str(RENDERER),
                "--source",
                str(self.source),
                "--output",
                str(self.output),
                "--keycloak-auth-url",
                "http://core.example.internal/keycloak",
            ],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("URL HTTPS", result.stderr)

    def test_cluster_scripts_expose_controlled_oidc_update(self):
        updater = UPDATER.read_text(encoding="utf-8")
        manager = MANAGER.read_text(encoding="utf-8")
        compose = (ROOT / "dev/compose/opensearch-cluster/compose.yml").read_text(encoding="utf-8")
        self.assertIn("-t \"${category}\"", updater)
        self.assertIn("configure-oidc", manager)
        self.assertIn("--keycloak-ca", manager)
        self.assertIn("idp-trust", compose)
        self.assertIn("idp-egress", compose)
        trust = (ROOT / "dev/scripts/opensearch-cluster/oidc-trust.py").read_text(encoding="utf-8")
        self.assertIn("oidc-trust.py", manager)
        self.assertIn("render-oidc-security-config.py", trust)
        self.assertIn("update-security-config.sh", trust)


if __name__ == "__main__":
    unittest.main(verbosity=2)
