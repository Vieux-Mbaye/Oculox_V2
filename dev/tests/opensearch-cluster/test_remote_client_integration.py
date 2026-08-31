#!/usr/bin/env python3

"""Static and fixture-based checks for remote OpenSearch clients."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import yaml


PROJECT_DIR = Path(__file__).resolve().parents[3]
RENDERER = PROJECT_DIR / "dev/scripts/render-remote-opensearch-compose.py"
BUILDER = PROJECT_DIR / "dev/scripts/opensearch-cluster/create-client-bundle.py"
IMPORTER = PROJECT_DIR / "dev/scripts/configure-remote-opensearch.py"
LAUNCHER = PROJECT_DIR / "oculox"
NGINX_ENTRYPOINT = PROJECT_DIR / "nginx/scripts/docker_entrypoint.sh"
NGINX_DASHBOARDS_REWRITE = PROJECT_DIR / "nginx/nginx_dashboards_rewrite_dashboards.conf"
NGINX_DASHBOARDS_REMOTE_BASIC_REWRITE = PROJECT_DIR / "nginx/nginx_dashboards_rewrite_remote_basic.conf"
NGINX_DASHBOARDS_REMOTE_SERVER = PROJECT_DIR / "nginx/nginx_dashboards_remote_server.conf"
COMPOSE_OVERRIDE = PROJECT_DIR / "dev/compose/docker-compose.dev.yml"
DASHBOARDS_CONFIG = PROJECT_DIR / "dashboards/opensearch_dashboards.yml"
TARGET = "/var/local/curlrc/.opensearch.primary.curlrc"


def run_renderer(work: Path, mode: str, verify: str, url: str, include_opensearch: bool = True) -> dict:
    services = {
        "opensearch": {"image": "example/opensearch", "profiles": ["malcolm"]},
        "logstash": {
            "image": "example/logstash",
            "depends_on": {"opensearch": {"condition": "service_started"}},
            "volumes": [{"type": "bind", "source": "/old", "target": TARGET, "read_only": True}],
        },
        "logstash-2": {
            "image": "example/logstash",
            "depends_on": ["opensearch"],
            "volumes": [f"/old:{TARGET}:ro"],
        },
        "arkime": {"image": "example/arkime", "volumes": []},
        "arkime-live": {"image": "example/arkime", "volumes": []},
        "dashboards": {"image": "example/dashboards", "volumes": []},
        "dashboards-helper": {"image": "example/helper", "volumes": []},
        "api": {"image": "example/api", "volumes": []},
        "pcap-monitor": {"image": "example/pcap", "volumes": []},
        "nginx-proxy": {"image": "example/nginx", "ports": ["443:443"]},
    }
    if not include_opensearch:
        services.pop("opensearch")
        for service in services.values():
            service.pop("depends_on", None)
    source = work / "compose.yml"
    output = work / "rendered.yml"
    env = work / "opensearch.env"
    clients = work / "clients"
    clients.mkdir()
    source.write_text(yaml.safe_dump({"services": services}), encoding="utf-8")
    env.write_text(
        f"OPENSEARCH_PRIMARY={mode}\nOPENSEARCH_URL={url}\n"
        f"OPENSEARCH_SSL_CERTIFICATE_VERIFICATION={verify}\n",
        encoding="utf-8",
    )
    for client in ("logstash", "arkime", "dashboards", "dashboards-helper", "api"):
        (clients / f"{client}.curlrc").write_text('user = "test:secret"\n', encoding="utf-8")
    subprocess.run(
        [
            str(RENDERER),
            "--input",
            str(source),
            "--output",
            str(output),
            "--opensearch-env",
            str(env),
            "--clients-dir",
            str(clients),
        ],
        check=True,
    )
    return yaml.safe_load(output.read_text(encoding="utf-8"))


def primary_source(service: dict) -> str:
    for volume in service.get("volumes", []):
        if isinstance(volume, dict) and volume.get("target") == TARGET:
            return str(volume.get("source"))
    raise AssertionError("primary curlrc mount absent")


def main() -> None:
    for path in (RENDERER, BUILDER, IMPORTER, LAUNCHER, NGINX_ENTRYPOINT, COMPOSE_OVERRIDE, DASHBOARDS_CONFIG):
        assert path.is_file(), path

    with tempfile.TemporaryDirectory() as tmp:
        remote = run_renderer(Path(tmp), "opensearch-remote", "true", "https://192.0.2.10:9200")
    services = remote["services"]
    assert services["opensearch"]["profiles"] == ["oculox-opensearch-local-disabled"]
    assert "opensearch" not in services["logstash"].get("depends_on", {})
    assert "opensearch" not in services["logstash-2"].get("depends_on", [])
    assert primary_source(services["logstash"]).endswith("/logstash.curlrc")
    assert primary_source(services["logstash-2"]).endswith("/logstash.curlrc")
    assert primary_source(services["arkime"]).endswith("/arkime.curlrc")
    assert primary_source(services["arkime-live"]).endswith("/arkime.curlrc")
    assert primary_source(services["dashboards"]).endswith("/dashboards.curlrc")
    assert primary_source(services["dashboards-helper"]).endswith("/dashboards-helper.curlrc")
    assert primary_source(services["api"]).endswith("/api.curlrc")
    assert primary_source(services["pcap-monitor"]).endswith("/api.curlrc")

    with tempfile.TemporaryDirectory() as tmp:
        hedgehog = run_renderer(
            Path(tmp), "opensearch-remote", "true", "https://192.0.2.10:9200", include_opensearch=False
        )
    assert "opensearch" not in hedgehog["services"]
    assert primary_source(hedgehog["services"]["arkime"]).endswith("/arkime.curlrc")
    assert any(str(port).endswith(":5601:5601/tcp") for port in hedgehog["services"]["nginx-proxy"]["ports"])

    with tempfile.TemporaryDirectory() as tmp:
        local = run_renderer(Path(tmp), "opensearch-local", "false", "https://opensearch:9200")
    assert local["services"]["opensearch"]["profiles"] == ["malcolm"]
    assert "opensearch" in local["services"]["logstash"]["depends_on"]
    assert local["services"]["nginx-proxy"]["ports"] == ["443:443"]

    launcher = LAUNCHER.read_text(encoding="utf-8")
    assert "render-remote-opensearch-compose.py" in launcher
    assert "configure-opensearch-remote" in launcher
    assert "--opensearch-bundle" in launcher
    assert "manage-cluster.sh" in launcher
    importer = IMPORTER.read_text(encoding="utf-8")
    assert '"OPENSEARCH_SSL_CERTIFICATE_VERIFICATION": "true"' in importer
    assert "insecure" in importer
    nginx_entrypoint = NGINX_ENTRYPOINT.read_text(encoding="utf-8")
    assert '"${OPENSEARCH_PRIMARY}" == "opensearch-remote"' in nginx_entrypoint
    assert 'ln -sf "$NGINX_DASHBOARDS_UPSTREAM_CONF" "$NGINX_DASHBOARDS_UPSTREAM_LINK"' in nginx_entrypoint
    dashboards_rewrite = NGINX_DASHBOARDS_REWRITE.read_text(encoding="utf-8")
    assert "include /etc/nginx/nginx_auth_rt.conf;" in dashboards_rewrite
    remote_basic_rewrite = NGINX_DASHBOARDS_REMOTE_BASIC_REWRITE.read_text(encoding="utf-8")
    assert "return 302 https://$host:5601$request_uri;" in remote_basic_rewrite
    remote_server = NGINX_DASHBOARDS_REMOTE_SERVER.read_text(encoding="utf-8")
    assert "listen 5601 ssl;" in remote_server
    assert 'proxy_set_header Authorization $http_authorization;' in remote_server
    assert 'proxy_set_header Authorization "";' not in remote_server
    dashboards_config = yaml.safe_load(DASHBOARDS_CONFIG.read_text(encoding="utf-8"))
    assert dashboards_config["opensearch_security"]["auth"]["type"] == "basicauth"
    assert "multiple_auth_enabled" not in dashboards_config["opensearch_security"]["auth"]
    assert "proxycache" not in dashboards_config["opensearch_security"]
    assert 'NGINX_DASHBOARDS_REMOTE_BASIC_REWRITE_CONF' in nginx_entrypoint
    compose_override = COMPOSE_OVERRIDE.read_text(encoding="utf-8")
    assert "./nginx/scripts/docker_entrypoint.sh:/usr/local/bin/docker_entrypoint.sh:ro" in compose_override
    assert "./nginx/nginx_dashboards_rewrite_dashboards.conf:/etc/nginx/nginx_dashboards_rewrite_dashboards.conf:ro" in compose_override
    assert "./nginx/nginx_dashboards_rewrite_remote_basic.conf:/etc/nginx/nginx_dashboards_rewrite_remote_basic.conf:ro" in compose_override
    assert "./nginx/nginx_dashboards_remote_server.conf:/etc/nginx/conf.d/02_oculox_dashboards_remote.conf:ro" in compose_override

    print("REMOTE_CLIENT_INTEGRATION_RESULT=PASS")


if __name__ == "__main__":
    main()
