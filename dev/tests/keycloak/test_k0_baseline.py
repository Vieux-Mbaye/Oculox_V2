#!/usr/bin/env python3

import os
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
CAPTURE = ROOT / "dev/scripts/keycloak/capture-baseline.sh"
REPORT = ROOT / "dev/keycloak/04_phase_k0_baseline_retour_arriere.md"


class KeycloakBaselineContractTest(unittest.TestCase):
    def test_capture_script_is_executable_and_strict(self):
        content = CAPTURE.read_text()
        self.assertTrue(os.access(CAPTURE, os.X_OK))
        self.assertIn("set -euo pipefail", content)

    def test_sensitive_backups_are_private_and_generated(self):
        content = CAPTURE.read_text()
        self.assertIn("dev/generated/keycloak-baseline", content)
        self.assertIn('chmod 700 "${OUTPUT_DIR}"', content)
        self.assertIn('chmod 600 "${OUTPUT_DIR}/private/runtime-configs.tar.gz"', content)
        self.assertIn('chmod 600 "${OUTPUT_DIR}/private/keycloak-postgresql.dump"', content)

    def test_capture_contains_required_rollback_material(self):
        content = CAPTURE.read_text()
        for path in (
            "config/auth-common.env",
            "config/keycloak.env",
            "config/postgres.env",
            "config/opensearch.env",
            "config/dashboards.env",
            "dashboards/opensearch_dashboards.yml",
            ".opensearch.primary.curlrc",
            "nginx/htpasswd",
            "nginx/certs",
            "nginx/ca-trust",
        ):
            self.assertIn(path, content)
        self.assertIn("pg_dump --format=custom", content)
        self.assertIn("private-backup-hashes.sha256", content)

    def test_report_documents_basic_and_full_rollback(self):
        report = REPORT.read_text()
        self.assertIn("Retour Rapide Vers Basic", report)
        self.assertIn("Restauration Complète De La Baseline", report)
        self.assertIn("NGINX_AUTH_MODE=basic", report)
        self.assertIn("INGESTION_RESULT=PASS", report)


if __name__ == "__main__":
    unittest.main(verbosity=2)
