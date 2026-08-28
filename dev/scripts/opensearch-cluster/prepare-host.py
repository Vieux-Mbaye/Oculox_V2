#!/usr/bin/env python3

"""Prepare a Linux host for the dedicated Oculox OpenSearch cluster."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_DIR))

from scripts.installer.core.install_context import InstallContext
from scripts.installer.platforms import get_platform_installer
from scripts.malcolm_common import get_platform_name
from scripts.malcolm_constants import OrchestrationFramework


def run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--operator", required=True)
    parser.add_argument("--dependencies-only", action="store_true")
    args = parser.parse_args()

    if os.geteuid() != 0:
        raise SystemExit("La préparation de l'hôte doit être exécutée avec sudo")
    if get_platform_name() != "linux":
        raise SystemExit("Le cluster OpenSearch dédié nécessite un hôte Linux")

    installer = get_platform_installer(OrchestrationFramework.DOCKER_COMPOSE, ui=None)
    context = InstallContext()
    context.initialize_for_platform("linux")
    context.set_docker_extra_users([args.operator])

    if not installer.install_dependencies():
        raise SystemExit("Échec de l'installation des dépendances système")
    if hasattr(installer, "install_package") and not installer.install_package(
        ["python3-bcrypt", "python3-yaml"]
    ):
        raise SystemExit("Échec de l'installation des dépendances Python du cluster")
    if args.dependencies_only:
        print("Dépendances de configuration du cluster installées.")
        return
    if not installer.is_docker_installed(runtime_bin="docker"):
        if not installer.install_docker(context, runtime_bin="docker"):
            raise SystemExit("Échec de l'installation de Docker")
    compose = subprocess.run(
        ["docker", "compose", "version"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if compose.returncode != 0:
        installer.install_docker_compose(context, runtime_bin="docker")
        compose = subprocess.run(
            ["docker", "compose", "version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    if compose.returncode != 0:
        raise SystemExit("Docker Compose n'est pas disponible")

    run(["sysctl", "-w", "vm.max_map_count=524288"])
    sysctl_file = Path("/etc/sysctl.d/99-oculox-opensearch.conf")
    sysctl_file.write_text("vm.max_map_count=524288\n", encoding="ascii")
    run(["systemctl", "enable", "--now", "docker"])
    run(["usermod", "-aG", "docker", args.operator])
    print("Hôte OpenSearch préparé; Docker et les paramètres noyau sont disponibles.")


if __name__ == "__main__":
    main()
