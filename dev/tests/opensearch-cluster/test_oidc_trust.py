#!/usr/bin/env python3
"""Regression checks for separate OpenSearch-to-Keycloak EJBCA trust."""

import importlib.util
import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location("oidc_trust", ROOT / "dev/scripts/opensearch-cluster/oidc-trust.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class TrustTest(unittest.TestCase):
    def test_https_discovery_dns_and_ip(self):
        for host in ("core.example.internal", "192.168.1.174"):
            issuer = f"https://{host}/keycloak/realms/oculox"
            keys = issuer + "/protocol/openid-connect/certs"
            self.assertEqual(MODULE.check_metadata({"issuer": issuer, "jwks_uri": keys},
                issuer + "/.well-known/openid-configuration"), keys)

    def test_reject_foreign_issuer_and_insecure_jwks(self):
        for data in ({"issuer": "https://foreign/realm", "jwks_uri": "https://foreign/keys"},
                     {"issuer": "https://core/realm", "jwks_uri": "http://core/keys"},
                     {"issuer": "https://core/realm", "jwks_uri": "https://foreign/keys"}):
            with self.assertRaises(RuntimeError):
                MODULE.check_metadata(data, "https://core/realm/.well-known/openid-configuration")

    def test_rolling_restart_not_recreate(self):
        migration = Mock()
        MODULE.reload_nodes(migration)
        self.assertEqual(migration.health.call_count, 3)
        self.assertEqual([call.args for call in migration.compose.call_args_list],
                         [("restart", node) for node in MODULE.NODES])

    def test_rollback_trust_after_failed_reload(self):
        with tempfile.TemporaryDirectory() as tmp:
            trust, ca, backup = Path(tmp) / "active", Path(tmp) / "new", Path(tmp) / "backup"
            trust.write_text("old CA")
            ca.write_text("new CA")
            backup.mkdir()
            (backup / "keycloak-ca.crt").write_text("old CA")
            migration = MODULE.module("test_migration", "migrate-ejbca.py")
            with patch.object(MODULE, "TRUST", trust), patch.object(MODULE, "validate_ca"), \
                    patch.object(MODULE, "probe"), patch.object(MODULE, "security", return_value={}), \
                    patch.object(MODULE, "module", return_value=migration), \
                    patch.object(migration, "health"), patch.object(MODULE, "snapshot", return_value=backup), \
                    patch.object(MODULE, "reload_nodes", side_effect=[RuntimeError("reload failed"), None]):
                with self.assertRaisesRegex(RuntimeError, "reload failed"):
                    MODULE.apply_trust(ca, "https://core/discovery")
                self.assertEqual(trust.read_text(), "old CA")

    def test_no_security_rewrite_in_trust_only(self):
        source = (ROOT / "dev/scripts/opensearch-cluster/oidc-trust.py").read_text()
        block = source.split("def apply_trust(", 1)[1].split("def write_security(", 1)[0]
        self.assertNotIn("update-security-config", block)
        self.assertIn('security("rolesmapping") != mappings', block)

    def test_fresh_oidc_uses_live_settings_and_preserves_custom_roles(self):
        config = {"config": {"dynamic": {"authc": {"basic_internal_auth_domain": {
            "http_enabled": True, "authentication_backend": {"type": "intern"}}},
            "custom_setting": "preserve"}}}
        mappings = {"customer_role": {"backend_roles": ["customer_team"], "users": ["alice"],
                                      "hosts": [], "and_backend_roles": []}}
        renderer = MODULE.module("test_renderer", "render-oidc-security-config.py")
        active = renderer.render_mappings(json.loads(json.dumps(mappings)))
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            migration = Mock()
            migration.env_value.return_value = "opensearch-image"
            def modules(name, filename):
                return renderer if filename.startswith("render-") else migration
            with patch.object(MODULE, "module", side_effect=modules), \
                    patch.object(MODULE, "apply_trust"), patch.object(MODULE, "snapshot", return_value=folder), \
                    patch.object(MODULE, "security", side_effect=[config, mappings, active]), \
                    patch.object(MODULE, "verify"), patch.object(MODULE, "run") as execute:
                MODULE.configure(argparse.Namespace(keycloak_auth_url="https://core.example/keycloak",
                    realm="oculox", client_id="oculox-dashboards", keycloak_ca=folder / "ca"))
            import yaml
            updated = yaml.safe_load((folder / "candidate/config.yml").read_text())
            saved = yaml.safe_load((folder / "candidate/roles_mapping.yml").read_text())
            self.assertEqual(updated["config"]["dynamic"]["custom_setting"], "preserve")
            self.assertEqual(saved["customer_role"], mappings["customer_role"])
            self.assertEqual(execute.call_count, 1)
            self.assertNotIn("internal_users", str(execute.call_args))

    def test_idempotent_current_trust_does_not_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            trust, ca = Path(tmp) / "active", Path(tmp) / "new"
            trust.write_text("current CA")
            ca.write_text("current CA")
            migration = Mock()
            with patch.object(MODULE, "TRUST", trust), patch.object(MODULE, "validate_ca"), \
                    patch.object(MODULE, "probe"), patch.object(MODULE, "security", return_value={}), \
                    patch.object(MODULE, "module", return_value=migration), \
                    patch.object(MODULE, "reload_nodes") as reload:
                MODULE.apply_trust(ca, "https://core/discovery")
                reload.assert_not_called()

    def test_tls_verification_cannot_be_disabled(self):
        config = {"config": {"dynamic": {"authc": {"oidc": {"http_enabled": True,
            "http_authenticator": {"type": "openid", "config": {"openid_connect_idp": {
                "enable_ssl": True, "verify_hostnames": False}}}}}}}}
        with self.assertRaisesRegex(RuntimeError, "verify TLS"):
            MODULE.oidc_settings(config)


if __name__ == "__main__":
    unittest.main(verbosity=2)
