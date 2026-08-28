#!/usr/bin/env python3

import importlib.util
import json
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[3]
CONFIG_DIR = PROJECT_DIR / "dev/config/opensearch-cluster/storage-policy"
SCRIPT = PROJECT_DIR / "dev/scripts/opensearch-cluster/apply-storage-policy.py"


def load_module():
    spec = importlib.util.spec_from_file_location("storage_policy", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def test_cluster_settings():
    settings = json.loads((CONFIG_DIR / "cluster-settings.json").read_text())["persistent"]
    assert settings["cluster.default_number_of_replicas"] == "1"
    assert settings["cluster.routing.allocation.disk.threshold_enabled"] == "true"
    assert settings["cluster.routing.allocation.disk.watermark.low"] == "75%"
    assert settings["cluster.routing.allocation.disk.watermark.high"] == "85%"
    assert settings["cluster.routing.allocation.disk.watermark.flood_stage"] == "90%"
    assert settings["cluster.info.update.interval"] == "30s"


def test_policies():
    expected = {
        "arkime-sessions-policy.json": ("arkime_sessions3-*", "90d"),
        "arkime-history-policy.json": ("arkime_history_v*", "91d"),
        "malcolm-beats-policy.json": ("malcolm_beats_*", "90d"),
    }
    for filename, (pattern, retention) in expected.items():
        policy = json.loads((CONFIG_DIR / filename).read_text())["policy"]
        assert policy["ism_template"][0]["index_patterns"] == [pattern]
        encoded = json.dumps(policy)
        assert f'"min_index_age": "{retention}"' in encoded
        assert '"number_of_replicas": 1' in encoded
        assert '"number_of_replicas": 0' not in encoded


def test_generated_policy_respects_operator_retention_choice():
    module = load_module()
    source = json.loads((CONFIG_DIR / "arkime-sessions-policy.json").read_text())
    retained = module.configure_policy(
        source,
        enabled=True,
        replicas=2,
        optimize_days=45,
        delete_enabled=False,
        delete_days=365,
    )
    encoded = json.dumps(retained)
    assert '"number_of_replicas": 2' in encoded
    assert '"min_index_age": "45d"' in encoded
    assert '"state_name": "delete"' not in encoded
    assert '"name": "delete"' not in encoded

    expiring = module.configure_policy(
        source,
        enabled=True,
        replicas=1,
        optimize_days=30,
        delete_enabled=True,
        delete_days=180,
    )
    assert '"min_index_age": "180d"' in json.dumps(expiring)


def test_generated_cluster_settings_respect_operator_values():
    module = load_module()
    payload = module.configured_cluster_settings(
        {
            "OPENSEARCH_REPLICAS": "2",
            "OPENSEARCH_WATERMARK_LOW": "70",
            "OPENSEARCH_WATERMARK_HIGH": "80",
            "OPENSEARCH_WATERMARK_FLOOD_STAGE": "90",
        }
    )
    settings = payload["persistent"]
    assert settings["cluster.default_number_of_replicas"] == "2"
    assert settings["cluster.routing.allocation.disk.watermark.low"] == "70%"
    assert settings["cluster.routing.allocation.disk.watermark.high"] == "80%"
    assert settings["cluster.routing.allocation.disk.watermark.flood_stage"] == "90%"


class FakeApi:
    def __init__(self, composable=None, legacy=None):
        self.composable = composable
        self.legacy = legacy
        self.puts = []

    def request(self, method, path, payload=None, **_kwargs):
        if method == "GET" and path.startswith("/_index_template/"):
            if self.composable is None:
                return 404, {}
            return 200, {"index_templates": [{"name": "fixture", "index_template": self.composable}]}
        if method == "GET" and path.startswith("/_template/"):
            if self.legacy is None:
                return 404, {}
            return 200, {"fixture": self.legacy}
        if method == "PUT":
            self.puts.append((path, payload))
            return 200, {"acknowledged": True}
        raise AssertionError((method, path, payload))


def test_composable_template_is_preserved():
    module = load_module()
    original = {
        "index_patterns": ["fixture-*"],
        "priority": 42,
        "template": {
            "settings": {"index.number_of_shards": "1", "index.number_of_replicas": "0",
                         "index.routing.allocation.total_shards_per_node": "1"},
            "mappings": {"properties": {"source.ip": {"type": "ip"}}},
            "aliases": {"fixture-read": {}},
        },
    }
    api = FakeApi(composable=original)
    assert module.reconcile_template(api, "fixture") == "composable-updated"
    body = api.puts[0][1]
    assert body["template"]["settings"]["index.number_of_replicas"] == "1"
    assert body["template"]["settings"]["index.routing.allocation.total_shards_per_node"] == "-1"
    assert body["template"]["mappings"] == original["template"]["mappings"]
    assert body["template"]["aliases"] == original["template"]["aliases"]
    assert original["template"]["settings"]["index.number_of_replicas"] == "0"


def test_legacy_template_is_preserved():
    module = load_module()
    original = {
        "order": 99,
        "index_patterns": ["fixture-*"],
        "settings": {"index.number_of_shards": "1", "index.number_of_replicas": "0",
                     "index.routing.allocation.total_shards_per_node": "2"},
        "mappings": {"properties": {"network.bytes": {"type": "long"}}},
        "aliases": {"fixture-read": {}},
    }
    api = FakeApi(legacy=original)
    assert module.reconcile_template(api, "fixture") == "legacy-updated"
    body = api.puts[0][1]
    assert body["settings"]["index.number_of_replicas"] == "1"
    assert body["settings"]["index.routing.allocation.total_shards_per_node"] == "-1"
    assert body["mappings"] == original["mappings"]
    assert body["aliases"] == original["aliases"]


def test_nested_template_settings_are_preserved():
    module = load_module()
    settings = {
        "index": {
            "number_of_shards": "3",
            "number_of_replicas": "0",
            "routing": {"allocation": {"total_shards_per_node": "1"}},
            "mapping": {"total_fields": {"limit": "5000"}},
        }
    }
    module.set_resilience_settings(settings)
    assert settings["index"]["number_of_shards"] == "3"
    assert settings["index"]["number_of_replicas"] == "1"
    assert settings["index"]["routing"]["allocation"]["total_shards_per_node"] == "-1"
    assert settings["index"]["mapping"]["total_fields"]["limit"] == "5000"


def test_arkime_search_limit_is_added_to_template():
    module = load_module()
    original = {
        "index_patterns": ["arkime_sessions3-*"],
        "template": {"settings": {"index": {"number_of_replicas": "0"}}},
    }
    api = FakeApi(composable=original)
    assert module.reconcile_template(api, "malcolm_template") == "composable-updated"
    settings = api.puts[0][1]["template"]["settings"]["index"]
    assert settings["number_of_shards"] == "1"
    assert settings["max_docvalue_fields_search"] == "200"


def test_arkime_search_limit_is_added_to_existing_indices():
    module = load_module()
    settings = {
        "arkime_sessions3-260807": {"settings": {"index": {}}},
        "arkime_sessions3-260814": {
            "settings": {"index": {"max_docvalue_fields_search": "200"}}
        },
        "malcolm_beats_zeek_260814": {"settings": {"index": {}}},
    }
    api = FakeApi()
    changed = module.ensure_arkime_search_limits(api, settings)
    assert changed == ["arkime_sessions3-260807"]
    assert api.puts == [
        (
            "/arkime_sessions3-260807/_settings",
            {"index": {"max_docvalue_fields_search": 200}},
        )
    ]


def test_mapping_conflicts_ignore_unmapped_fields():
    module = load_module()
    field_caps = {
        "fields": {
            "dns.queryHost": {
                "keyword": {"type": "keyword"},
                "text": {"type": "text"},
                "unmapped": {"type": "unmapped"},
            },
            "network.protocol": {
                "keyword": {"type": "keyword"},
                "unmapped": {"type": "unmapped"},
            },
        }
    }
    assert module.find_mapping_conflicts(field_caps) == {
        "dns.queryHost": ["keyword", "text"]
    }


if __name__ == "__main__":
    tests = [value for name, value in globals().items() if name.startswith("test_")]
    for test in tests:
        test()
        print(f"{test.__name__}=PASS")
    print("STORAGE_POLICY_STATIC_RESULT=PASS")
