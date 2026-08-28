#!/usr/bin/env python3

"""Render service credentials and disable local OpenSearch in remote mode."""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml


CREDENTIAL_CLIENT = {
    "logstash": "logstash",
    "logstash-2": "logstash",
    "arkime": "arkime",
    "arkime-live": "arkime",
    "dashboards": "dashboards",
    "dashboards-helper": "dashboards-helper",
    "api": "api",
    "pcap-monitor": "api",
}
TARGET = "/var/local/curlrc/.opensearch.primary.curlrc"


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return values


def volume_target(volume: object) -> str:
    if isinstance(volume, dict):
        return str(volume.get("target", ""))
    if isinstance(volume, str):
        parts = volume.split(":")
        return parts[1] if len(parts) > 1 else ""
    return ""


def port_target(port: object) -> int | None:
    if isinstance(port, dict):
        try:
            return int(port.get("target"))
        except (TypeError, ValueError):
            return None
    if isinstance(port, str):
        value = port.split("/")[0].rsplit(":", 1)[-1]
        try:
            return int(value)
        except ValueError:
            return None
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--opensearch-env", type=Path, required=True)
    parser.add_argument("--clients-dir", type=Path, required=True)
    args = parser.parse_args()

    data = yaml.safe_load(args.input.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("services"), dict):
        raise SystemExit("Compose source invalide")

    env = read_env(args.opensearch_env)
    if env.get("OPENSEARCH_PRIMARY") == "opensearch-remote":
        if env.get("OPENSEARCH_SSL_CERTIFICATE_VERIFICATION", "").lower() != "true":
            raise SystemExit("Le mode distant exige OPENSEARCH_SSL_CERTIFICATE_VERIFICATION=true")
        if not env.get("OPENSEARCH_URL", "").startswith("https://"):
            raise SystemExit("Le mode distant exige une OPENSEARCH_URL HTTPS")

        services = data["services"]
        if "opensearch" in services:
            services["opensearch"]["profiles"] = ["oculox-opensearch-local-disabled"]

        if "nginx-proxy" not in services:
            raise SystemExit("Service nginx-proxy absent du Compose")
        nginx_ports = services["nginx-proxy"].setdefault("ports", [])
        if not any(port_target(port) == 5601 for port in nginx_ports):
            nginx_ports.append("${OCULOX_DASHBOARDS_BIND_IP:-0.0.0.0}:5601:5601/tcp")

        for service in services.values():
            depends_on = service.get("depends_on")
            if isinstance(depends_on, dict):
                depends_on.pop("opensearch", None)
            elif isinstance(depends_on, list):
                service["depends_on"] = [name for name in depends_on if name != "opensearch"]

        for service_name, client in CREDENTIAL_CLIENT.items():
            if service_name not in services:
                continue
            credential = (args.clients_dir / f"{client}.curlrc").resolve()
            if not credential.is_file():
                raise SystemExit(f"Identifiants clients OpenSearch absents : {credential}")
            volumes = services[service_name].setdefault("volumes", [])
            volumes[:] = [volume for volume in volumes if volume_target(volume) != TARGET]
            volumes.append(
                {
                    "type": "bind",
                    "source": str(credential),
                    "target": TARGET,
                    "read_only": True,
                    "bind": {"create_host_path": False},
                }
            )

    args.output.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


if __name__ == "__main__":
    main()
