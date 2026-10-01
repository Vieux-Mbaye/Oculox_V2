#!/usr/bin/env python3
"""Prepare and operate Oculox host telemetry forwarders.

The upstream Malcolm service files assume the repository is checked out as
``~/Malcolm`` and send Fluent Bit events to localhost:5045. Oculox reserves
5045 for the second Logstash Beats endpoint, so this script installs patched
user services that target the local Filebeat TCP input on 5055 by default.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


SERVICE_NAMES = (
    "aide-malcolm.service",
    "auditlog-malcolm.service",
    "cpu-malcolm.service",
    "df-malcolm.service",
    "disk-malcolm.service",
    "kmsg-malcolm.service",
    "mem-malcolm.service",
    "network-malcolm.service",
    "systemd-malcolm.service",
    "thermal-malcolm.service",
)


def run(command: list[str], *, best_effort: bool = False) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if result.returncode and not best_effort:
        sys.stdout.write(result.stdout)
        raise SystemExit(result.returncode)
    return result


def project_dir_from_args(value: str | None) -> Path:
    if value:
        return Path(value).expanduser().resolve()
    return Path(__file__).resolve().parents[2]


def service_source_dir(project_dir: Path) -> Path:
    return project_dir / "malcolm-iso/config/includes.chroot/etc/skel/.config/systemd/user"


def service_dest_dir(value: str | None = None) -> Path:
    if value:
        return Path(value).expanduser().resolve()
    return Path.home() / ".config/systemd/user"


def fluent_bit_available() -> bool:
    return bool(shutil.which("fluent-bit")) or Path("/opt/fluent-bit/bin/fluent-bit").exists()


def systemd_user_available() -> bool:
    if not shutil.which("systemctl"):
        return False
    return run(["systemctl", "--user", "show-environment"], best_effort=True).returncode == 0


def patch_service(name: str, content: str, project_dir: Path, tcp_port: int) -> str:
    rendered = (
        content.replace("%h/Malcolm", str(project_dir))
        .replace(f"{project_dir}/filebeat/certs", f"{project_dir}/dev/generated/pki")
        .replace("tcp://localhost:5045", f"tcp://localhost:{tcp_port}")
    )
    if name == "kmsg-malcolm.service":
        rendered = rendered.replace(
            "ExecStart=/opt/fluent-bit/bin/fluent-bit ",
            "ExecStart=sudo /opt/fluent-bit/bin/fluent-bit ",
        )
    return rendered


def configure_services(project_dir: Path, tcp_port: int, dest_dir: Path) -> None:
    src_dir = service_source_dir(project_dir)
    if not src_dir.is_dir():
        raise SystemExit(f"Répertoire de services introuvable : {src_dir}")
    pki_dir = project_dir / "dev/generated/pki"
    for cert_name in ("ca.crt", "client.crt", "client.key"):
        if not (pki_dir / cert_name).is_file():
            raise SystemExit(
                f"Certificat Filebeat manquant : {pki_dir / cert_name}. "
                "Lancez d'abord ./oculox prepare ou ./oculox start."
            )

    dest_dir.mkdir(parents=True, exist_ok=True)
    (Path.home() / ".local/share/fluent-bit").mkdir(parents=True, exist_ok=True)
    for name in SERVICE_NAMES:
        source = src_dir / name
        if not source.is_file():
            raise SystemExit(f"Service Malcolm introuvable : {source}")
        rendered = patch_service(name, source.read_text(encoding="utf-8"), project_dir, tcp_port)
        destination = dest_dir / name
        destination.write_text(rendered, encoding="utf-8")
        destination.chmod(0o644)

    if systemd_user_available():
        run(["systemctl", "--user", "daemon-reload"], best_effort=True)

    print(f"Services de télémétrie installés dans {dest_dir}")
    print(f"Destination Fluent Bit : tcp://localhost:{tcp_port}")


def service_action(action: str, *, best_effort: bool) -> int:
    if not systemd_user_available():
        print("systemd utilisateur indisponible : services hôte non démarrés.")
        return 0 if best_effort else 1

    if action == "start" and not fluent_bit_available():
        print("Fluent Bit est absent : installez fluent-bit avant le démarrage des services hôte.")
        return 0 if best_effort else 1

    exit_code = 0
    for name in SERVICE_NAMES:
        command = ["systemctl", "--user"]
        if action == "start":
            command.extend(["enable", "--now", name])
        elif action == "stop":
            command.extend(["disable", "--now", name])
        elif action == "status":
            command.extend(["is-active", name])
        else:
            raise ValueError(action)

        result = run(command, best_effort=True)
        status = result.stdout.strip() or ("ok" if result.returncode == 0 else "failed")
        print(f"{name}: {status}")
        if result.returncode:
            exit_code = result.returncode

    return 0 if best_effort else exit_code


def verify(project_dir: Path, tcp_port: int, dest_dir: Path) -> int:
    expected = f"tcp://localhost:{tcp_port}"
    missing: list[str] = []
    wrong_port: list[str] = []
    wrong_path: list[str] = []
    wrong_pki: list[str] = []

    for name in SERVICE_NAMES:
        service = dest_dir / name
        if not service.is_file():
            missing.append(name)
            continue
        content = service.read_text(encoding="utf-8")
        if expected not in content:
            wrong_port.append(name)
        if str(project_dir) not in content:
            wrong_path.append(name)
        if f"{project_dir}/dev/generated/pki" not in content:
            wrong_pki.append(name)

    if missing or wrong_port or wrong_path or wrong_pki:
        if missing:
            print("Services absents : " + ", ".join(missing))
        if wrong_port:
            print("Services avec mauvaise destination TCP : " + ", ".join(wrong_port))
        if wrong_path:
            print("Services avec mauvais chemin de dépôt : " + ", ".join(wrong_path))
        if wrong_pki:
            print("Services avec mauvais chemin PKI Filebeat : " + ", ".join(wrong_pki))
        return 1

    print("Configuration des services hôte valide.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Configure Oculox host telemetry forwarders")
    parser.add_argument("action", choices=("configure", "start", "stop", "status", "verify"))
    parser.add_argument("--project-dir")
    parser.add_argument("--service-dir")
    parser.add_argument("--tcp-port", type=int, default=int(os.environ.get("OCULOX_HOST_TELEMETRY_PORT", "5055")))
    parser.add_argument("--best-effort", action="store_true")
    args = parser.parse_args()

    project_dir = project_dir_from_args(args.project_dir)
    dest_dir = service_dest_dir(args.service_dir)
    if args.action == "configure":
        configure_services(project_dir, args.tcp_port, dest_dir)
        return verify(project_dir, args.tcp_port, dest_dir)
    if args.action == "verify":
        return verify(project_dir, args.tcp_port, dest_dir)
    return service_action(args.action, best_effort=args.best_effort)


if __name__ == "__main__":
    raise SystemExit(main())
