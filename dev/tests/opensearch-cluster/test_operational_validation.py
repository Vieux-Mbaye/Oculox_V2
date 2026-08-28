#!/usr/bin/env python3

"""Static contracts for client and end-to-end validation commands."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def main() -> None:
    launcher = (ROOT / "oculox").read_text(encoding="utf-8")
    clients = (ROOT / "dev/tests/opensearch-cluster/validate-client-connectivity.py").read_text(
        encoding="utf-8"
    )
    ingestion = (ROOT / "dev/tests/opensearch-cluster/validate-ingestion-path.py").read_text(
        encoding="utf-8"
    )
    failover = (ROOT / "dev/tests/opensearch-cluster/summarize-ingestion-failover.py").read_text(
        encoding="utf-8"
    )
    dashboards = (ROOT / "dashboards/opensearch_dashboards.yml").read_text(encoding="utf-8")
    compose = (ROOT / "dev/compose/docker-compose.dev.yml").read_text(encoding="utf-8")

    assert "verify clients" in launcher
    assert "verify ingestion" in launcher
    assert "verify failover" in launcher
    for service in (
        "logstash-2", "arkime-live", "dashboards-helper", "pcap-monitor", "nginx-proxy"
    ):
        assert service in clients
    assert '"output.elasticsearch" not in config' in clients
    assert '"output.opensearch" not in config' in clients
    assert "certificateAuthorities:" in dashboards
    assert "/var/local/ca-trust/oculox-opensearch-ca.crt" in dashboards
    assert "SSL_CERT_FILE: /var/local/ca-trust/oculox-opensearch-ca.crt" in compose
    assert "REQUESTS_CA_BUNDLE: /var/local/ca-trust/oculox-opensearch-ca.crt" in compose
    roles = (ROOT / "dev/config/opensearch-cluster/security/roles.yml").read_text(
        encoding="utf-8"
    )
    assert "'indices:admin/template/get'" in roles
    assert "'indices:admin/index_template/get'" in roles
    assert "'cluster:admin/settings/update'" in roles
    assert "'malcolm_*'" in roles
    assert "'opensearch-ad-plugin-result-*'" in roles
    for action in ("baseline", "inject", "finalize"):
        assert f'add_parser("{action}")' in ingestion
    assert '"--allow-core"' in ingestion
    assert '"source_role": role()' in ingestion
    assert '"capinfos", "-c", "-M"' in ingestion
    for metric in (
        "packets", "zeek", "suricata", "logstash_delta", "pipeline_documents",
        "arkime_sessions", "indexing_rejections",
    ):
        assert metric in ingestion
    for node in ("opensearch-1", "opensearch-2", "opensearch-3"):
        assert node in failover
    assert "filebeat_all_published_events_acked" in failover
    assert "zero_unassigned_shards" in failover
    print("OPERATIONAL_VALIDATION_STATIC_RESULT=PASS")


if __name__ == "__main__":
    main()
