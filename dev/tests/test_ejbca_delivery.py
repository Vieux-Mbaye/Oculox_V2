#!/usr/bin/env python3
"""Run source-only delivery checks without provisioning CA or replacing certificates."""

import ast
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    manifest = ROOT / "INSTALLATION_SOURCE_MANIFEST.json"
    if manifest.is_file():
        entries = json.loads(manifest.read_text(encoding="utf-8"))
        for name, expected in entries.items():
            path = (ROOT / name).resolve()
            if not path.is_relative_to(ROOT) or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise RuntimeError(f"Source archive integrity failure: {name}")
        print(f"INSTALLATION_SOURCE_INTEGRITY=PASS files={len(entries)}", flush=True)
    environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    commands = [
        [sys.executable, "-m", "unittest", "dev.tests.test_ejbca_workflows",
         "dev.tests.test_pki_local_csr", "dev.tests.test_pki_service_validation"],
        [sys.executable, "dev/tests/opensearch-cluster/test_cluster_config.py"],
        [sys.executable, "dev/tests/opensearch-cluster/test_oidc_security_config.py"],
        [sys.executable, "dev/tests/opensearch-cluster/test_oidc_trust.py"],
        [sys.executable, "-m", "unittest", "discover", "-s", "dev/tests/keycloak", "-p", "test_*.py"],
        [sys.executable, "dev/tests/opensearch-cluster/test_fresh_installation_contract.py"],
        ["bash", "-n", "oculox"],
        ["bash", "-n", "dev/scripts/ejbca/manage-ejbca.sh"],
        ["bash", "-n", "dev/scripts/opensearch-cluster/manage-cluster.sh"],
        ["bash", "-n", "shared/bin/jdk-cacerts-auto-import.sh"],
    ]
    for command in commands:
        subprocess.run(command, cwd=ROOT, env=environment, check=True)
    for path in (ROOT / "dev/scripts/ejbca").glob("*.py"):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for name in ("README.md", "installation_3_vm_et_bundles.md", "livraison_ejbca_2026-09-30.md"):
        if not (ROOT / "dev/ejbca/docs" / name).is_file():
            raise RuntimeError(f"Missing delivery documentation: {name}")
    print("EJBCA_SOURCE_DELIVERY_RESULT=PASS; source/configuration tests only, not a fresh-VM installation")


if __name__ == "__main__":
    main()
