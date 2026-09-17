#!/usr/bin/env python3

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
CONFIGURE = ROOT / "dev/scripts/keycloak/configure-portal-auth.py"
NGINX_AUTH = ROOT / "nginx/nginx_auth_keycloak.conf"
NGINX_HELPERS = ROOT / "nginx/lua/nginx_auth_helpers.lua"
LAUNCHER = ROOT / "oculox"


def values(path: Path) -> dict[str, str]:
    return {
        key: value
        for line in path.read_text().splitlines()
        if "=" in line and not line.startswith("#")
        for key, value in [line.split("=", 1)]
    }


class PortalOidcActivationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.auth_common = self.base / "auth-common.env"
        self.keycloak = self.base / "keycloak.env"
        self.public = self.base / "public-endpoint.env"
        self.report = self.base / "realm-report.json"
        self.auth_common.write_text(
            "NGINX_AUTH_MODE=basic\n"
            "NGINX_KEYCLOAK_BASIC_AUTH=false\n"
            "ROLE_BASED_ACCESS=false\n"
            "NGINX_REQUIRE_GROUP=\n"
            "NGINX_REQUIRE_ROLE=\n"
        )
        self.keycloak.write_text(
            "KEYCLOAK_AUTH_REALM=oculox\n"
            "KEYCLOAK_AUTH_REDIRECT_URI=/index.html\n"
            "KEYCLOAK_AUTH_URL=https://core.example.internal/keycloak\n"
            "KEYCLOAK_CLIENT_ID=oculox-portal\n"
            "KEYCLOAK_CLIENT_SECRET=old-secret\n"
            "KEYCLOAK_PORTAL_CLIENT_ID=oculox-portal\n"
            "KEYCLOAK_PORTAL_CLIENT_SECRET=portal-secret-that-is-long-enough\n"
            "KEYCLOAK_PROVISIONING_ENABLED=false\n"
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
                "--auth-common-env",
                str(self.auth_common),
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

    def test_activation_requires_a_successful_realm_report(self):
        result = self.run_configure("activate", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("run ./oculox keycloak provision first", result.stderr)

        self.report.write_text(json.dumps({"result": "FAIL"}))
        result = self.run_configure("activate", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("realm report is not PASS", result.stderr)

    def test_activation_sets_keycloak_portal_contract(self):
        self.report.write_text(json.dumps({"result": "PASS"}))
        self.run_configure("activate")
        auth = values(self.auth_common)
        keycloak = values(self.keycloak)
        self.assertEqual(auth["NGINX_AUTH_MODE"], "keycloak")
        self.assertEqual(auth["NGINX_KEYCLOAK_BASIC_AUTH"], "false")
        self.assertEqual(auth["ROLE_BASED_ACCESS"], "true")
        self.assertEqual(auth["NGINX_REQUIRE_GROUP"], "/oculox-users")
        self.assertEqual(auth["NGINX_REQUIRE_ROLE"], "")
        self.assertEqual(keycloak["KEYCLOAK_CLIENT_ID"], "oculox-portal")
        self.assertEqual(keycloak["KEYCLOAK_CLIENT_SECRET"], "portal-secret-that-is-long-enough")
        self.assertEqual(keycloak["KEYCLOAK_SSL_VERIFY"], "true")

        verify = self.run_configure("verify")
        self.assertIn('"result": "PASS"', verify.stdout)

    def test_deactivation_returns_to_basic_without_destroying_keycloak_material(self):
        self.report.write_text(json.dumps({"result": "PASS"}))
        self.run_configure("activate")
        self.run_configure("deactivate")
        auth = values(self.auth_common)
        keycloak = values(self.keycloak)
        self.assertEqual(auth["NGINX_AUTH_MODE"], "basic")
        self.assertEqual(auth["ROLE_BASED_ACCESS"], "false")
        self.assertEqual(auth["NGINX_REQUIRE_GROUP"], "")
        self.assertEqual(keycloak["KEYCLOAK_PORTAL_CLIENT_SECRET"], "portal-secret-that-is-long-enough")

    def test_nginx_oidc_cookie_and_header_spoofing_guards_are_present(self):
        auth_conf = NGINX_AUTH.read_text()
        helpers = NGINX_HELPERS.read_text()
        compose = (ROOT / "dev/compose/docker-compose.dev.yml").read_text()
        nginx = (ROOT / "nginx/nginx.conf").read_text()
        envs = (ROOT / "nginx/nginx_envs.conf").read_text()
        self.assertIn("KEYCLOAK_NGINX_CONNECT_URL", envs)
        self.assertIn("KEYCLOAK_NGINX_CONNECT_URL", auth_conf)
        self.assertIn("location ^~ /assets/", nginx)
        self.assertIn("location ^~ /css/", nginx)
        self.assertIn("location ^~ /js/", nginx)
        self.assertNotRegex(
            nginx,
            r"location \^~ /(assets|css|js)/ \{[^}]*nginx_auth_rt\.conf",
        )
        self.assertIn("./nginx/nginx.conf:/etc/nginx/nginx.conf:ro", compose)
        self.assertIn("./nginx/nginx_envs.conf:/etc/nginx/nginx_envs.conf:ro", compose)
        self.assertIn("./nginx/nginx_auth_keycloak.conf:/etc/nginx/nginx_auth_keycloak.conf:ro", compose)
        self.assertIn("./nginx/nginx_auth_keycloak_basic.conf:/etc/nginx/nginx_auth_keycloak_basic.conf:ro", compose)
        self.assertIn("httponly = true", auth_conf)
        self.assertIn('samesite = "Lax"', auth_conf)
        self.assertIn('ngx.req.clear_header("X-Forwarded-User")', helpers)
        self.assertIn('ngx.req.clear_header("X-Forwarded-Groups")', helpers)
        self.assertIn('ngx.req.clear_header("X-Forwarded-Roles")', helpers)
        self.assertLess(
            helpers.index('ngx.req.clear_header("X-Forwarded-Roles")'),
            helpers.index('ngx.req.set_header("X-Forwarded-Roles"'),
        )

    def test_launcher_exposes_k5_portal_commands(self):
        launcher = LAUNCHER.read_text()
        self.assertIn("keycloak activate-portal", launcher)
        self.assertIn("configure-portal-auth.py activate", launcher)
        self.assertIn("keycloak deactivate-portal", launcher)
        self.assertIn("keycloak verify-portal", launcher)


if __name__ == "__main__":
    unittest.main(verbosity=2)
