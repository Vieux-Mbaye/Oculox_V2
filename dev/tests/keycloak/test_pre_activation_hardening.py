#!/usr/bin/env python3

import os
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PREFLIGHT = ROOT / "keycloak/scripts/hardening-preflight.sh"


def valid_environment():
    return {
        "NGINX_AUTH_MODE": "keycloak",
        "KEYCLOAK_AUTH_REALM": "oculox",
        "KEYCLOAK_BOOTSTRAP_REALM": "master",
        "KEYCLOAK_AUTH_URL": "https://192.0.2.10/keycloak",
        "KEYCLOAK_AUTH_REDIRECT_URI": "/index.html",
        "KEYCLOAK_CLIENT_ID": "oculox-portal",
        "KEYCLOAK_CLIENT_SECRET": "a" * 32,
        "KEYCLOAK_SSL_VERIFY": "true",
        "KC_HOSTNAME": "https://192.0.2.10/keycloak",
        "KC_HOSTNAME_STRICT": "true",
        "KC_HTTP_RELATIVE_PATH": "/keycloak",
        "KC_PROXY_HEADERS": "xforwarded",
        "ROLE_BASED_ACCESS": "true",
        "NGINX_REQUIRE_GROUP": "/oculox-users",
        "KEYCLOAK_PASSWORD_MIN_LENGTH": "14",
        "KEYCLOAK_ACCESS_TOKEN_LIFESPAN_SECONDS": "300",
        "KEYCLOAK_SSO_SESSION_IDLE_SECONDS": "1800",
        "KEYCLOAK_SSO_SESSION_MAX_SECONDS": "28800",
        "KEYCLOAK_EVENTS_EXPIRATION_SECONDS": "604800",
    }


class PreActivationHardeningTest(unittest.TestCase):
    def run_preflight(self, overrides=None):
        environment = os.environ.copy()
        environment.update(valid_environment())
        environment.update(overrides or {})
        return subprocess.run(
            [str(PREFLIGHT)],
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_valid_hardened_configuration_passes(self):
        result = self.run_preflight()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("a" * 32, result.stderr)

    def test_basic_mode_is_not_activated_or_blocked(self):
        result = self.run_preflight({"NGINX_AUTH_MODE": "basic"})
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_weak_configurations_are_rejected(self):
        cases = {
            "master target realm": {"KEYCLOAK_AUTH_REALM": "master"},
            "plain HTTP": {"KEYCLOAK_AUTH_URL": "http://192.0.2.10/keycloak"},
            "wildcard redirect": {"KEYCLOAK_AUTH_REDIRECT_URI": "/*"},
            "foreign redirect": {"KEYCLOAK_AUTH_REDIRECT_URI": "https://example.net/callback"},
            "short client secret": {"KEYCLOAK_CLIENT_SECRET": "short"},
            "disabled TLS verification": {"KEYCLOAK_SSL_VERIFY": "false"},
            "non-strict hostname": {"KC_HOSTNAME_STRICT": "false"},
            "disabled RBAC": {"ROLE_BASED_ACCESS": "false"},
            "missing required group": {"NGINX_REQUIRE_GROUP": ""},
            "long access token": {"KEYCLOAK_ACCESS_TOKEN_LIFESPAN_SECONDS": "3600"},
            "weak password policy": {"KEYCLOAK_PASSWORD_MIN_LENGTH": "10"},
            "partial bootstrap credentials": {"KC_BOOTSTRAP_ADMIN_USERNAME": "temporary-admin"},
        }
        for label, overrides in cases.items():
            with self.subTest(label=label):
                result = self.run_preflight(overrides)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("hardening preflight failed", result.stderr)

    def test_examples_remain_safe_and_do_not_activate_keycloak(self):
        auth_example = (ROOT / "config/auth-common.env.example").read_text()
        keycloak_example = (ROOT / "config/keycloak.env.example").read_text()
        self.assertIn("NGINX_AUTH_MODE=basic", auth_example)
        self.assertIn("KEYCLOAK_AUTH_REALM=oculox", keycloak_example)
        self.assertIn("KEYCLOAK_BOOTSTRAP_REALM=master", keycloak_example)
        self.assertIn("KEYCLOAK_SSL_VERIFY=true", keycloak_example)
        self.assertIn("KC_HOSTNAME_STRICT=true", keycloak_example)
        self.assertIn("KEYCLOAK_MFA_REQUIRED=true", keycloak_example)

    def test_provisioning_uses_restricted_oidc_flow(self):
        setup = (ROOT / "keycloak/scripts/realm-setup.sh").read_text()
        self.assertIn('BOOTSTRAP_REALM="${KEYCLOAK_BOOTSTRAP_REALM:-master}"', setup)
        self.assertIn("directAccessGrantsEnabled: false", setup)
        self.assertIn("implicitFlowEnabled: false", setup)
        self.assertIn("standardFlowEnabled: true", setup)
        self.assertIn("redirectUris: [$redirect_uri]", setup)
        self.assertNotIn("[\"/*\"]", setup)
        self.assertIn("bruteForceProtected=true", setup)
        self.assertIn("revokeRefreshToken=true", setup)
        self.assertIn("adminEventsEnabled=true", setup)
        self.assertIn("CONFIGURE_TOTP", setup)
        self.assertIn("oculox_portal_audience", setup)

    def test_reviewed_scripts_are_mounted_read_only(self):
        compose = (ROOT / "dev/compose/docker-compose.dev.yml").read_text()
        for script in (
            "docker-entrypoint.sh",
            "hardening-preflight.sh",
            "realm-setup.sh",
        ):
            self.assertIn(f"keycloak/scripts/{script}", compose)
            self.assertRegex(compose, rf"keycloak/scripts/{script}:[^\n]+:ro")


if __name__ == "__main__":
    unittest.main(verbosity=2)
