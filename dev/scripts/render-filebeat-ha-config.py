#!/usr/bin/env python3

"""Generate Filebeat configurations for one or more Logstash endpoints."""

import argparse

from pathlib import Path

import yaml


PROJECT_DIR = Path(__file__).resolve().parents[2]
SOURCE_DIR = PROJECT_DIR / "filebeat"
OUTPUT_DIR = PROJECT_DIR / "dev" / "generated" / "filebeat"
SINGLE_OUTPUT_DIR = PROJECT_DIR / "dev" / "generated" / "filebeat-single"

CONFIGURATIONS = {
    "filebeat-logs.yml": "/usr/share/filebeat-logs/filebeat-logs.yml",
    "filebeat-nginx.yml": "/usr/share/filebeat-nginx/filebeat-nginx.yml",
    "filebeat-syslog-tcp.yml": "/usr/share/filebeat-syslog-tcp/filebeat-syslog-tcp.yml",
    "filebeat-syslog-udp.yml": "/usr/share/filebeat-syslog-udp/filebeat-syslog-udp.yml",
    "filebeat-tcp.yml": "/usr/share/filebeat-tcp/filebeat-tcp.yml",
}

LOGSTASH_OUTPUT_COMMON = {
    "ssl.enabled": True,
    "ssl.certificate_authorities": ["/certs/ca.crt"],
    "ssl.certificate": "/certs/client.crt",
    "ssl.key": "/certs/client.key",
    "ssl.supported_protocols": ["TLSv1.2", "TLSv1.3"],
    "ssl.verification_mode": "full",
}


def output_configuration(hosts: list[str]) -> dict:
    configuration = LOGSTASH_OUTPUT_COMMON.copy()
    configuration["hosts"] = hosts
    configuration["loadbalance"] = len(hosts) > 1
    return configuration


def render(source_name: str, output_dir: Path, hosts: list[str]) -> None:
    source_path = SOURCE_DIR / source_name
    output_path = output_dir / source_name

    with source_path.open("r", encoding="utf-8") as source_file:
        configuration = yaml.safe_load(source_file)

    if "output.logstash" not in configuration:
        raise RuntimeError(f"{source_path} ne contient pas output.logstash")

    configuration["output.logstash"] = output_configuration(hosts)
    # Le conteneur exécute plusieurs processus Filebeat. Un seul endpoint HTTP
    # est donc activé, sur le processus principal qui lit les journaux réseau.
    if source_name == "filebeat-logs.yml":
        configuration["http.enabled"] = True
        configuration["http.host"] = "127.0.0.1"
        configuration["http.port"] = 5066
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8") as output_file:
        output_file.write("# Fichier genere. Ne pas modifier directement.\n")
        output_file.write(f"# Source: {source_path.relative_to(PROJECT_DIR)}\n")
        yaml.safe_dump(
            configuration,
            output_file,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
            width=1000,
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Génère les sorties Filebeat TLS vers un ou plusieurs Logstash."
    )
    parser.add_argument(
        "--host",
        action="append",
        dest="hosts",
        help="Destination Logstash sous la forme nom:port (répétable).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Répertoire de sortie. Obligatoire lorsque --host est utilisé.",
    )
    return parser.parse_args()


def render_all(output_dir: Path, hosts: list[str]) -> None:
    if not hosts or any(":" not in host for host in hosts):
        raise ValueError("Chaque destination doit être écrite sous la forme nom:port")
    for source_name in CONFIGURATIONS:
        render(source_name, output_dir, hosts)
        print(f"Genere: {output_dir / source_name}")


def main() -> None:
    args = parse_args()
    if args.hosts:
        if args.output_dir is None:
            raise SystemExit("--output-dir est obligatoire avec --host")
        render_all(args.output_dir.resolve(), args.hosts)
        return
    if args.output_dir is not None:
        raise SystemExit("--output-dir nécessite au moins une option --host")

    # Comportement historique utilisé par les tests locaux simple/double.
    render_all(OUTPUT_DIR, ["logstash:5044", "logstash-2:5044"])
    render_all(SINGLE_OUTPUT_DIR, ["logstash:5044"])


if __name__ == "__main__":
    main()
