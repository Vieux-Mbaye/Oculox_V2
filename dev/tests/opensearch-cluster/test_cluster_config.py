#!/usr/bin/env python3

"""Validate the operator-facing cluster configuration contract."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import yaml


PROJECT_DIR = Path(__file__).resolve().parents[3]
RENDERER = PROJECT_DIR / "dev/scripts/opensearch-cluster/render-cluster-config.py"


def render(source: str) -> tuple[subprocess.CompletedProcess[str], dict, dict[str, str]]:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        config = root / "input.yml"
        normalized = root / "normalized.yml"
        env_file = root / "cluster.env"
        config.write_text(source, encoding="utf-8")
        result = subprocess.run(
            [
                str(RENDERER),
                "--config",
                str(config),
                "--output-config",
                str(normalized),
                "--output-env",
                str(env_file),
                "--proxy-uid",
                "1234",
                "--proxy-gid",
                "5678",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        rendered_config = yaml.safe_load(normalized.read_text()) if normalized.exists() else {}
        rendered_env = {}
        if env_file.exists():
            rendered_env = dict(
                line.split("=", 1)
                for line in env_file.read_text(encoding="ascii").splitlines()
                if line
            )
        return result, rendered_config, rendered_env


def test_custom_configuration() -> None:
    result, config, env = render(
        """
version: 1
cluster:
  heap_per_node: 3g
endpoint:
  ip: 192.0.2.25
  port: 9443
  monitoring_port: 8405
storage:
  primary_shards: 2
  replicas: 2
  watermarks:
    low: 70
    high: 80
    flood_stage: 90
policies:
  beats:
    delete_enabled: true
    delete_after_days: 180
"""
    )
    assert result.returncode == 0, result.stderr
    assert config["cluster"]["heap_per_node"] == "3g"
    assert config["policies"]["arkime_sessions"]["delete_enabled"] is False
    assert env["OPENSEARCH_CLUSTER_ENDPOINT"] == "https://192.0.2.25:9443"
    assert env["OPENSEARCH_MONITORING_PORT"] == "8405"
    assert env["OPENSEARCH_PRIMARY_SHARDS"] == "2"
    assert env["OPENSEARCH_REPLICAS"] == "2"
    assert env["OPENSEARCH_POLICY_BEATS_DELETE_ENABLED"] == "true"
    assert env["OPENSEARCH_PROXY_UID"] == "1234"
    assert env["OPENSEARCH_PROXY_GID"] == "5678"


def test_unknown_setting_is_rejected() -> None:
    result, _, _ = render("version: 1\nendpoint:\n  ip: 192.0.2.25\nunknown: true\n")
    assert result.returncode != 0
    assert "Unknown setting" in result.stderr


def test_invalid_watermarks_are_rejected() -> None:
    result, _, _ = render(
        "version: 1\nendpoint:\n  ip: 192.0.2.25\nstorage:\n"
        "  watermarks:\n    low: 90\n    high: 80\n    flood_stage: 95\n"
    )
    assert result.returncode != 0
    assert "low < high < flood_stage" in result.stderr


def test_unimplemented_snapshots_are_rejected() -> None:
    result, _, _ = render(
        "version: 1\nendpoint:\n  ip: 192.0.2.25\nsnapshots:\n  enabled: true\n"
    )
    assert result.returncode != 0
    assert "snapshots are not available yet" in result.stderr


if __name__ == "__main__":
    tests = [value for name, value in globals().items() if name.startswith("test_")]
    for test in tests:
        test()
        print(f"{test.__name__}=PASS")
    print("CLUSTER_CONFIG_RESULT=PASS")
