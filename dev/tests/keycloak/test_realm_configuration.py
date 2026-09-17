#!/usr/bin/env python3

import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
CONFIGURE = ROOT / "dev/scripts/keycloak/configure-realm.py"


def values(path: Path) -> dict[str, str]:
    return {
        key: value
        for line in path.read_text().splitlines()
        if "=" in line and not line.startswith("#")
        for key, value in [line.split("=", 1)]
    }


class RealmConfigurationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.keycloak = self.base / "keycloak.env"
        self.auth_common = self.base / "auth-common.env"
        self.public = self.base / "public-endpoint.env"
        self.credentials = self.base / "initial-credentials.env"
        self.keycloak.write_text(
            "KEYCLOAK_AUTH_REALM=oculox\n"
            "KEYCLOAK_AUTH_URL=https://core.example.internal/keycloak\n"
            "KEYCLOAK_CLIENT_ID=\n"
            "KEYCLOAK_CLIENT_SECRET=\n"
            "KEYCLOAK_PROVISIONING_ENABLED=false\n"
        )
        self.auth_common.write_text(
            "NGINX_AUTH_MODE=basic\nROLE_BASED_ACCESS=false\nNGINX_REQUIRE_GROUP=\n"
        )
        self.public.write_text(
            "OCULOX_PUBLIC_URL=https://core.example.internal\n"
            "OCULOX_KEYCLOAK_URL=https://core.example.internal/keycloak\n"
        )

    def tearDown(self):
        self.temp.cleanup()

    def execute(self, action: str, admin="operator-admin", check=True):
        return subprocess.run(
            [
                str(CONFIGURE),
                action,
                "--admin-username",
                admin,
                "--keycloak-env",
                str(self.keycloak),
                "--auth-common-env",
                str(self.auth_common),
                "--public-endpoint-env",
                str(self.public),
                "--credentials-file",
                str(self.credentials),
            ],
            text=True,
            capture_output=True,
            check=check,
        )

    def test_prepare_is_portable_hardened_and_preserves_basic(self):
        self.execute("prepare")
        keycloak = values(self.keycloak)
        auth = values(self.auth_common)
        credentials = values(self.credentials)
        self.assertEqual(keycloak["KEYCLOAK_PROVISIONING_ENABLED"], "true")
        self.assertEqual(keycloak["KEYCLOAK_CLIENT_ID"], "oculox-portal")
        self.assertEqual(keycloak["KEYCLOAK_PORTAL_CLIENT_ID"], "oculox-portal")
        self.assertEqual(keycloak["KEYCLOAK_DASHBOARDS_CLIENT_ID"], "oculox-dashboards")
        self.assertEqual(keycloak["KEYCLOAK_PROVISIONER_CLIENT_ID"], "oculox-realm-provisioner")
        self.assertEqual(keycloak["KEYCLOAK_RECOVERY_CLIENT_ID"], "oculox-bootstrap-recovery")
        self.assertEqual(keycloak["KEYCLOAK_CONSOLE_ADMIN_USERNAME"], "oculox-keycloak-admin")
        self.assertEqual(
            keycloak["KEYCLOAK_DASHBOARDS_REDIRECT_URI"],
            "https://core.example.internal:5601/dashboards/auth/openid/login",
        )
        self.assertEqual(keycloak["KEYCLOAK_NGINX_CONNECT_URL"], "http://keycloak:8080/keycloak")
        self.assertEqual(keycloak["KEYCLOAK_DASHBOARDS_CONNECT_URL"], "http://keycloak:8080/keycloak")
        self.assertEqual(auth["NGINX_AUTH_MODE"], "basic")
        self.assertEqual(auth["ROLE_BASED_ACCESS"], "true")
        self.assertEqual(auth["NGINX_REQUIRE_GROUP"], "/oculox-users")
        self.assertGreaterEqual(len(keycloak["KEYCLOAK_CLIENT_SECRET"]), 32)
        self.assertEqual(keycloak["KEYCLOAK_CLIENT_SECRET"], keycloak["KEYCLOAK_PORTAL_CLIENT_SECRET"])
        self.assertGreaterEqual(len(keycloak["KEYCLOAK_CONSOLE_ADMIN_PASSWORD"]), 14)
        self.assertGreaterEqual(len(keycloak["KEYCLOAK_PROVISIONER_CLIENT_SECRET"]), 32)
        self.assertGreaterEqual(len(keycloak["KEYCLOAK_RECOVERY_CLIENT_SECRET"]), 32)
        self.assertEqual(credentials["KEYCLOAK_INITIAL_ADMIN_USERNAME"], "operator-admin")
        self.assertEqual(credentials["KEYCLOAK_CONSOLE_ADMIN_USERNAME"], "oculox-keycloak-admin")
        for key, value in credentials.items():
            if key.endswith("_PASSWORD"):
                self.assertGreaterEqual(len(value), 14)
                self.assertTrue(any(character.isupper() for character in value))
                self.assertTrue(any(character.islower() for character in value))
                self.assertTrue(any(character.isdigit() for character in value))
                self.assertNotIn("$", value)
                self.assertTrue(any(character in "!@#%^&*-_" for character in value))
        self.assertEqual(self.credentials.stat().st_mode & 0o777, 0o600)

    def test_second_prepare_preserves_client_and_initial_credentials(self):
        self.execute("prepare")
        before = values(self.keycloak)
        credentials_before = self.credentials.read_bytes()
        self.execute("prepare")
        after = values(self.keycloak)
        self.assertEqual(before["KEYCLOAK_CLIENT_SECRET"], after["KEYCLOAK_CLIENT_SECRET"])
        self.assertEqual(before["KEYCLOAK_DASHBOARDS_CLIENT_SECRET"], after["KEYCLOAK_DASHBOARDS_CLIENT_SECRET"])
        self.assertEqual(credentials_before, self.credentials.read_bytes())

    def test_finalize_removes_temporary_runtime_passwords_only(self):
        self.execute("prepare")
        before = values(self.keycloak)
        self.execute("finalize")
        after = values(self.keycloak)
        self.assertEqual(after["KEYCLOAK_PROVISIONING_ENABLED"], "false")
        self.assertEqual(after["KC_BOOTSTRAP_ADMIN_USERNAME"], "")
        self.assertEqual(after["KC_BOOTSTRAP_ADMIN_PASSWORD"], "")
        self.assertEqual(after["KEYCLOAK_INITIAL_ADMIN_PASSWORD"], "")
        self.assertEqual(after["KEYCLOAK_CONSOLE_ADMIN_PASSWORD"], "")
        self.assertEqual(after["KEYCLOAK_RECOVERY_CLIENT_ID"], "")
        self.assertEqual(after["KEYCLOAK_RECOVERY_CLIENT_SECRET"], "")
        self.assertEqual(after["KEYCLOAK_CLIENT_SECRET"], before["KEYCLOAK_CLIENT_SECRET"])
        self.assertEqual(after["KEYCLOAK_DASHBOARDS_CLIENT_SECRET"], before["KEYCLOAK_DASHBOARDS_CLIENT_SECRET"])
        self.assertTrue(self.credentials.is_file())

    def test_invalid_administrator_name_is_rejected(self):
        result = self.execute("prepare", admin="bad user", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Invalid initial administrator username", result.stderr)

    def test_launcher_and_service_gate_support_provisioning_without_oidc_activation(self):
        launcher = (ROOT / "oculox").read_text()
        entrypoint = (ROOT / "keycloak/scripts/docker-entrypoint.sh").read_text()
        service_check = (ROOT / "shared/bin/service_check_passthrough.sh").read_text()
        self.assertIn("keycloak provision", launcher)
        self.assertIn("configure-realm.py prepare", launcher)
        self.assertIn("KEYCLOAK_PROVISIONING_ENABLED", entrypoint)
        self.assertIn("KEYCLOAK_PROVISIONING_ENABLED", service_check)

    def test_realm_script_has_idempotent_clients_and_group_based_rbac(self):
        realm_setup = (ROOT / "keycloak/scripts/realm-setup.sh").read_text()
        self.assertIn("oculox-admins", realm_setup)
        self.assertIn("oculox-analysts", realm_setup)
        self.assertIn("oculox-viewers", realm_setup)
        self.assertIn("oculox-incident-response", realm_setup)
        self.assertIn("oculox-admin", realm_setup)
        self.assertIn("oculox-analyst", realm_setup)
        self.assertIn("oculox-viewer", realm_setup)
        self.assertIn("oculox-denied", realm_setup)
        self.assertIn("remove_user_if_present", realm_setup)
        self.assertNotIn("ensure_user oculox-test-admin", realm_setup)
        self.assertIn("ensure_console_admin", realm_setup)
        self.assertIn("KEYCLOAK_CONSOLE_ADMIN_USERNAME", realm_setup)
        self.assertIn("directAccessGrantsEnabled: false", realm_setup)
        self.assertIn("redirectUris: [$redirect_uri, $post_logout_uri]", realm_setup)
        self.assertIn("webOrigins: [$web_origin]", realm_setup)
        self.assertIn('claim.name": "roles"', realm_setup)
        self.assertIn("user_realm_roles_flat", realm_setup)
        self.assertIn("KEYCLOAK_RECOVERY_CLIENT_ID", realm_setup)
        self.assertIn("--rolename admin", realm_setup)
        self.assertIn(".id = $id", realm_setup)


if __name__ == "__main__":
    unittest.main(verbosity=2)
