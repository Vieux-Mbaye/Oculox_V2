#!/usr/bin/env python3

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
VERIFY = ROOT / "dev/scripts/keycloak/verify-functional-hardening.py"
LAUNCHER = ROOT / "oculox"


class FunctionalHardeningTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.auth = self.base / "auth-common.env"
        self.keycloak = self.base / "keycloak.env"
        self.dashboards = self.base / "dashboards.env"
        self.public = self.base / "public-endpoint.env"
        self.report = self.base / "realm-report.json"
        self.credentials = self.base / "keycloak-initial-credentials.env"
        self.auth.write_text("NGINX_AUTH_MODE=keycloak\nROLE_BASED_ACCESS=true\nNGINX_REQUIRE_GROUP=/oculox-users\n")
        self.keycloak.write_text(
            "KEYCLOAK_AUTH_REALM=oculox\n"
            "KEYCLOAK_AUTH_URL=https://core.example.internal/keycloak\n"
            "KEYCLOAK_NGINX_CONNECT_URL=http://keycloak:8080/keycloak\n"
            "KEYCLOAK_DASHBOARDS_CONNECT_URL=http://keycloak:8080/keycloak\n"
            "KEYCLOAK_AUTH_REDIRECT_URI=/index.html\n"
            "KEYCLOAK_DASHBOARDS_REDIRECT_URI=https://core.example.internal:5601/dashboards/auth/openid/login\n"
            "KEYCLOAK_PROVISIONING_ENABLED=false\n"
            "KEYCLOAK_SSL_VERIFY=true\n"
            "KEYCLOAK_ACCESS_TOKEN_LIFESPAN_SECONDS=300\n"
            "KEYCLOAK_MFA_REQUIRED=true\n"
            "KC_HOSTNAME_BACKCHANNEL_DYNAMIC=true\n"
            "KC_HOSTNAME_STRICT=true\n"
            "KC_BOOTSTRAP_ADMIN_USERNAME=\n"
            "KC_BOOTSTRAP_ADMIN_PASSWORD=\n"
            "KEYCLOAK_INITIAL_ADMIN_PASSWORD=\n"
            "KEYCLOAK_USER_ADMIN_PASSWORD=\n"
            "KEYCLOAK_USER_ANALYST_PASSWORD=\n"
            "KEYCLOAK_USER_VIEWER_PASSWORD=\n"
            "KEYCLOAK_USER_INCIDENT_RESPONSE_PASSWORD=\n"
            "KEYCLOAK_USER_DENIED_PASSWORD=\n"
            "KEYCLOAK_CONSOLE_ADMIN_PASSWORD=\n"
            "KEYCLOAK_RECOVERY_CLIENT_ID=\n"
            "KEYCLOAK_RECOVERY_CLIENT_SECRET=\n"
        )
        self.dashboards.write_text("DASHBOARDS_AUTH_TYPE=openid\n")
        self.public.write_text("OCULOX_PUBLIC_URL=https://core.example.internal\n")
        self.report.write_text(json.dumps({
            "result": "PASS",
            "clients": {
                "portal": {"direct_grants": False},
                "dashboards": {"direct_grants": False},
            },
            "realm_security": {
                "mfa_required_action_enabled": True,
                "mfa_required_action_default": True,
                "brute_force_protected": True,
                "refresh_token_rotation": True,
                "events_enabled": True,
                "admin_events_enabled": True,
                "admin_event_details_enabled": True,
            },
            "keycloak_console_admin": {
                "username": "oculox-keycloak-admin",
                "realm": "master",
                "realm_roles": ["admin"],
            },
        }))
        for path in (self.auth, self.keycloak, self.dashboards, self.credentials):
            if not path.exists():
                path.write_text("")
            path.chmod(0o600)

    def tearDown(self):
        self.temp.cleanup()

    def run_verify(self, check=True):
        return subprocess.run(
            [
                str(VERIFY),
                "--auth-common-env", str(self.auth),
                "--keycloak-env", str(self.keycloak),
                "--dashboards-env", str(self.dashboards),
                "--public-endpoint-env", str(self.public),
                "--realm-report", str(self.report),
                "--credentials-file", str(self.credentials),
            ],
            text=True,
            capture_output=True,
            check=check,
        )

    def test_valid_hardening_contract_passes(self):
        result = self.run_verify()
        self.assertIn('"result": "PASS"', result.stdout)
        self.assertIn('"portal_uses_internal_keycloak_connect_url": true', result.stdout)
        self.assertIn('"dashboards_uses_internal_keycloak_connect_url": true', result.stdout)
        self.assertIn('"hostname_backchannel_dynamic": true', result.stdout)

    def test_missing_mfa_fails(self):
        self.keycloak.write_text(self.keycloak.read_text().replace("KEYCLOAK_MFA_REQUIRED=true", "KEYCLOAK_MFA_REQUIRED=false"))
        result = self.run_verify(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('"mfa_required": false', result.stdout)

    def test_leftover_bootstrap_secret_fails(self):
        self.keycloak.write_text(self.keycloak.read_text().replace("KC_BOOTSTRAP_ADMIN_PASSWORD=", "KC_BOOTSTRAP_ADMIN_PASSWORD=temporary-secret"))
        result = self.run_verify(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('"temporary_runtime_secrets_cleared": false', result.stdout)

    def test_launcher_exposes_hardening_verifier(self):
        launcher = LAUNCHER.read_text(encoding="utf-8")
        self.assertIn("keycloak verify-hardening", launcher)
        self.assertIn("verify-functional-hardening.py", launcher)

    def test_keycloak_admin_console_has_network_acl(self):
        config = (ROOT / "nginx/nginx_keycloak_location.conf").read_text(encoding="utf-8")
        self.assertIn("location ^~ /keycloak/admin", config)
        self.assertIn("allow 127.0.0.1;", config)
        self.assertIn("allow 10.0.0.0/8;", config)
        self.assertIn("allow 172.16.0.0/12;", config)
        self.assertIn("allow 192.168.0.0/16;", config)
        self.assertIn("deny all;", config)


if __name__ == "__main__":
    unittest.main(verbosity=2)
