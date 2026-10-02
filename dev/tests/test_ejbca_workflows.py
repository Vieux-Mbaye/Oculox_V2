#!/usr/bin/env python3
"""Regression tests for authenticated enrollment and repeatable PKI operations."""

import argparse
import copy
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[name] = loaded
    spec.loader.exec_module(loaded)
    return loaded


REMOTE = module("test_remote_pki", "dev/scripts/ejbca/remote-enrollment.py")
PROFILES = module("test_profiles_pki", "dev/scripts/ejbca/provision-profiles.py")
ROTATION = module("test_rotation_pki", "dev/scripts/opensearch-cluster/migrate-ejbca.py")
RENDER = module("test_dns_pki", "dev/scripts/opensearch-cluster/render-cluster-config.py")
AUDIT = module("test_role_audit_pki", "dev/scripts/pki-audit.py")
BACKUP = module("test_backup_pki", "dev/scripts/ejbca/backup-restore.py")


class PinnedTrustTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.base = Path(cls.temp.name)
        for name in ("root", "foreign"):
            subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                "-subj", f"/CN={name}", "-keyout", str(cls.base / f"{name}.key"), "-out", str(cls.base / f"{name}.crt"),
                "-addext", "basicConstraints=critical,CA:TRUE", "-addext", "keyUsage=critical,keyCertSign,cRLSign"],
                capture_output=True, check=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def bundle(self, path, foreign=False):
        for name in ("root.crt", "agent-ca.crt", "api-ca.crt", "service-ca.crt"):
            source = "foreign.crt" if foreign and name != "root.crt" else "root.crt"
            (path / name).write_bytes((self.base / source).read_bytes())

    def test_all_trust_bundles_must_chain_to_pinned_root(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            self.bundle(path)
            REMOTE.verify_pinned_bundle(path, REMOTE.fingerprint(path / "root.crt"))
            self.bundle(path, foreign=True)
            with self.assertRaises(RuntimeError):
                REMOTE.verify_pinned_bundle(path, REMOTE.fingerprint(path / "root.crt"))

    def test_appended_foreign_anchor_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            self.bundle(path)
            (path / "api-ca.crt").write_bytes((self.base / "root.crt").read_bytes() + (self.base / "foreign.crt").read_bytes())
            with self.assertRaises(RuntimeError):
                REMOTE.verify_pinned_bundle(path, REMOTE.fingerprint(path / "root.crt"))

    def test_wrong_fingerprint_is_rejected(self):
        with self.assertRaises(RuntimeError):
            REMOTE.verify_pinned_bundle(self.base, "0" * 64)


class EnrollmentPolicyTests(unittest.TestCase):
    def test_profile_expansion_ignores_only_trailing_disabled_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "entity.xml"
            PROFILES.render_entity(PROFILES.PROFILES / "entity-profile-template.xml", path, 123, 456)
            root = ET.parse(path).getroot().find("object")
            expected = REMOTE.profile_policy(root)
            counts = next(item[1] for item in root.findall("void")
                          if len(item) == 2 and item[0].text == "NUMBERARRAY")
            for _ in range(10):
                ET.SubElement(ET.SubElement(counts, "void", {"method": "add"}), "int").text = "0"
            self.assertEqual(REMOTE.profile_policy(root), expected)
            counts[-1][0].text = "1"
            self.assertNotEqual(REMOTE.profile_policy(root), expected)
            counts[-1][0].text = "0"
            counts[5][0].text = "2"
            self.assertNotEqual(REMOTE.profile_policy(root), expected)

    def test_runtime_validation_rejects_stopped_ca_and_failed_database(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manager = root / "dev/scripts/ejbca/manage-ejbca.sh"
            manager.parent.mkdir(parents=True)
            shutil.copy2(ROOT / "dev/scripts/ejbca/manage-ejbca.sh", manager)
            env = root / "dev/ejbca/generated/ejbca.env"
            env.parent.mkdir(parents=True)
            env.write_text("EJBCA_CA_TOKEN_PASSWORD=fixture\nEJBCA_ADMIN_USERNAME=fixture\n")
            shell = '''docker() {
                case "$*" in
                    *"ps --services"*)
                        if [[ "$SCENARIO" != stopped ]]; then printf 'ejbca\\n'; fi ;;
                    *"exec -T ejbca-db"*) return 1 ;;
                    *) return 0 ;;
                esac
            }
            python3() { return 0; }
            export -f docker python3
            bash "$1" validate
            '''
            for scenario in ("stopped", "database-failed"):
                result = subprocess.run(["bash", "-c", shell, "fixture", str(manager)],
                                        env={**os.environ, "SCENARIO": scenario}, capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0, scenario)
            self.assertIn("validation operationnelle en echec", subprocess.run(
                ["bash", "-c", shell, "fixture", str(manager)], env={**os.environ, "SCENARIO": "stopped"},
                capture_output=True, text=True).stderr)

    def test_server_profile_binds_all_dn_and_san_fields(self):
        for role in REMOTE.ROLE_SERVICES:
            for service in REMOTE.ROLE_SERVICES[role]:
                with self.subTest(role=role, service=service), tempfile.TemporaryDirectory() as directory:
                    profile = Path(directory) / "entity.xml"
                    PROFILES.render_entity(PROFILES.PROFILES / "entity-profile-template.xml", profile, 123, 456)
                    tree = ET.parse(profile)
                    subject = REMOTE.scoped_subject(role, "sensor-01", service)
                    dns, ips = REMOTE.scoped_sans(role, "sensor-01", service, "192.0.2.20", "search.example.internal")
                    REMOTE.bind_profile_identity(tree.getroot().find("object"), subject, dns, ips)
                    tree.write(profile)
                    values = PROFILES.profile_values(profile)
                    dn = dict(part.split("=", 1) for part in subject.split(","))
                    for field, names in ((5, [dn["CN"]]), (11, [dn["OU"]]), (12, [dn["O"]]),
                                         (16, [dn["C"]]), (18, dns), (19, ips)):
                        self.assertEqual(values["NUMBERARRAY"][field], str(len(names)))
                        for slot, name in enumerate(names):
                            index = field + slot * 100
                            self.assertEqual(values[str(index)], name)
                            self.assertEqual(values[str(10000 + index)], "true")
                            self.assertEqual(values[str(20000 + index)], "true")
                            self.assertEqual(values[str(30000 + index)], "false")

    def test_fresh_role_skips_only_nonexistent_legacy_profile(self):
        calls = []

        def ejbca(*args):
            calls.append(args)
            if args[:2] == ("roles", "listroles"):
                return ""
            if args[:2] == ("roles", "changerule") and args[3].endswith("-enroll-v1/"):
                raise RuntimeError(f"No resource with name '{args[3]}' is available")
            return ""
        with patch.object(REMOTE, "ejbca", side_effect=ejbca):
            REMOTE.provision_role("collector", "sensor-01", "agent")
        self.assertIn(("roles", "changerule", "Oculox Enrollment collector sensor-01",
                       "/ra_functionality/edit_end_entity/", "DECLINE"), calls)
        self.assertNotIn(("roles", "changerule", "Oculox Enrollment collector sensor-01",
                          "/ra_functionality/edit_end_entity/", "ACCEPT"), calls)
        with patch.object(REMOTE, "ejbca", side_effect=RuntimeError("database unavailable")):
            with self.assertRaises(RuntimeError):
                REMOTE.provision_role("collector", "sensor-01", "agent")

    def test_agent_renewal_restores_previous_files_after_install_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state, bundle = root / "state", root / "bundle"
            state.mkdir()
            bundle.mkdir()
            config = {"role": "collector", "identity": "sensor-01", "allowed_services": ["filebeat_client"],
                      "end_entity_profile": REMOTE.collector_profile_name("sensor-01"),
                      "api_url": "https://core.example:18443/ejbca/ejbca-rest-api/v1/certificate/pkcs10enroll"}
            for name in ("agent.crt", "agent-ca.crt", "api-ca.crt", "service-ca.crt", "root.crt"):
                (state / name).write_text("old " + name)
                (bundle / name).write_text("new " + name)
            for path in (state / "config.json", bundle / "config.json"):
                path.write_text(json.dumps(config))
            for name in ("agent.key", "agent.csr", "pending.key", "pending.csr"):
                (state / name).write_text(name)
                (state / name).chmod(0o600)
            original = {path.name: path.read_bytes() for path in state.iterdir()}
            copy = shutil.copy2
            failed = False

            def fail_once(source, target):
                nonlocal failed
                if Path(source) == bundle / "api-ca.crt" and not failed:
                    failed = True
                    raise OSError("simulated full disk")
                return copy(source, target)

            def openssl(*args):
                if "-subject" in args:
                    return "subject=" + REMOTE.agent_dn("collector", "sensor-01")
                return "public-key"

            args = argparse.Namespace(bundle=bundle, root_sha256="0" * 64, renew=True)
            with patch.object(REMOTE, "STATE", state), patch.object(REMOTE, "verify_pinned_bundle"), patch.object(REMOTE, "openssl", side_effect=openssl), patch.object(REMOTE.shutil, "copy2", side_effect=fail_once):
                with self.assertRaises(OSError):
                    REMOTE.install_agent(args)
            self.assertEqual({name: (state / name).read_bytes() for name in original}, original)
            self.assertEqual((state / "agent.key").stat().st_mode & 0o777, 0o600)

    def test_restore_sql_quotes_identifiers_without_shell_substitution(self):
        sql = BACKUP.reset_database_sql("ejbca")
        self.assertIn("CREATE DATABASE `ejbca`", sql)
        for name in ("$(id)", "bad`name", "db; DROP DATABASE other", ""):
            with self.assertRaises(RuntimeError):
                BACKUP.reset_database_sql(name)

    def test_https_policy(self):
        base = {"role": "collector", "identity": "sensor-01", "allowed_services": ["filebeat_client"],
                "end_entity_profile": REMOTE.collector_profile_name("sensor-01"),
                "api_url": "https://core.example:18443/ejbca/ejbca-rest-api/v1/certificate/pkcs10enroll"}
        REMOTE.validate_agent_config(base)
        for url in ("http://core.example/enroll", "https://user:secret@core.example/enroll", "https://core.example/admin"):
            with self.assertRaises(RuntimeError):
                REMOTE.validate_agent_config({**base, "api_url": url})
        with self.assertRaises(RuntimeError):
            REMOTE.validate_agent_config({**base, "allowed_services": ["web_server"]})
        with self.assertRaises(RuntimeError):
            REMOTE.validate_agent_config({**base, "end_entity_profile": "oculox-filebeat-client-enroll-v3"})

    def test_dns_separate_from_listener_ip(self):
        config = copy.deepcopy(RENDER.DEFAULT_CONFIG)
        config["endpoint"].update(ip="192.0.2.15", dns="search.client.example")
        RENDER.validate(config)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cluster.env"
            RENDER.render_env(config, path, 1000, 1000)
            values = dict(line.split("=", 1) for line in path.read_text().splitlines())
            self.assertEqual(values["OPENSEARCH_CLUSTER_ENDPOINT"], "https://search.client.example:9200")
            self.assertEqual(values["OPENSEARCH_ENDPOINT_BIND_IP"], "192.0.2.15")
        for dns in ("-invalid.example", "bad\nname.example", "192.0.2.16", "bad..example"):
            config["endpoint"]["dns"] = dns
            with self.assertRaises(ValueError):
                RENDER.validate(config)

    def test_cluster_agent_profile_and_endpoint_binding(self):
        services = list(REMOTE.ROLE_SERVICES["cluster"])
        config = {"role": "cluster", "identity": "cluster-01", "allowed_services": services,
                  "api_url": "https://core.example:18443/ejbca/ejbca-rest-api/v1/certificate/pkcs10enroll",
                  "endpoint_ip": "192.0.2.20", "endpoint_dns": "search.example.internal",
                  "end_entity_profiles": {service: REMOTE.scoped_profile_name("cluster", "cluster-01", service)
                                          for service in services}}
        REMOTE.validate_agent_config(config)
        self.assertEqual(REMOTE.scoped_sans("cluster", "cluster-01", "opensearch_endpoint",
                                            config["endpoint_ip"], config["endpoint_dns"]),
                         (["opensearch-endpoint", "search.example.internal"], ["192.0.2.20"]))
        with self.assertRaises(RuntimeError):
            REMOTE.validate_agent_config({**config, "end_entity_profiles": {}})
        with self.assertRaises(ValueError):
            REMOTE.validate_agent_config({**config, "endpoint_dns": "bad..domain"})

    def test_core_audit_excludes_nonactive_cluster_files(self):
        manifest = {"certificates": {"opensearch_node_1": {"zone": "opensearch"}, "filebeat_client": {}}}
        with patch.object(AUDIT, "load_manifest", return_value=manifest), patch.object(AUDIT, "parse_env_value", return_value="principal"), patch.object(AUDIT, "audit_certificate") as audit, tempfile.TemporaryDirectory() as directory, patch.object(AUDIT, "PROJECT_DIR", Path(directory)):
            AUDIT.audit_all(Path("unused"))
            self.assertEqual(audit.call_count, 1)
            self.assertEqual(audit.call_args.args[0], "filebeat_client")

    def test_cluster_audit_does_not_require_core_certificates(self):
        manifest = {"certificates": {"opensearch_node_1": {"zone": "opensearch"},
                    "opensearch_remote_trust": {"zone": "opensearch"}, "web_server": {"zone": "web"}}}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "dev/generated/opensearch-cluster/cluster.env"
            config.parent.mkdir(parents=True)
            config.touch()
            with patch.object(AUDIT, "load_manifest", return_value=manifest), patch.object(AUDIT, "parse_env_value", return_value=None), patch.object(AUDIT, "audit_certificate") as audit, patch.object(AUDIT, "PROJECT_DIR", root):
                AUDIT.audit_all(Path("unused"))
            self.assertEqual(audit.call_count, 1)
            self.assertEqual(audit.call_args.args[0], "opensearch_node_1")
            self.assertTrue(audit.call_args.args[1]["required"])

    def test_profile_parameter_drift_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            expected, actual = Path(directory) / "expected.xml", Path(directory) / "actual.xml"
            settings = {"validity": "1y", "key_size": 3072, "extended_key_usage": ["serverAuth"],
                        "key_usage": ["digitalSignature", "keyEncipherment"]}
            PROFILES.render_certificate(PROFILES.PROFILES / "certificate-profile-template.xml", expected, 1234, settings)
            actual.write_bytes(expected.read_bytes())
            PROFILES.verify_profile(expected, actual, False)
            actual.write_text(actual.read_text().replace("<string>1y</string>", "<string>10y</string>"))
            with self.assertRaises(RuntimeError):
                PROFILES.verify_profile(expected, actual, False)

    def test_rotate_preflight_after_retire_does_not_replace_files(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(ROTATION, "GENERATED", Path(directory)), patch.object(ROTATION, "state_phase", return_value="retire"), patch.object(ROTATION, "run", return_value=""), patch.object(ROTATION, "compose"), patch.object(ROTATION, "verify_stages"), patch.object(ROTATION, "health"), patch.object(ROTATION, "snapshot") as backup, patch.object(ROTATION, "leaf_phase") as leaf, patch.object(sys, "argv", ["pki-migrate", "rotate", "--check"]):
            ROTATION.main()
            backup.assert_not_called()
            leaf.assert_not_called()


if __name__ == "__main__":
    unittest.main()
