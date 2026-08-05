#!/usr/bin/env python3

"""Apply the selected Oculox deployment role without rewriting unrelated settings."""

import argparse
import re
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[2]
GENERATED_DIR = PROJECT_DIR / "dev" / "generated"
VALID_VALUE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")


def update_env(path: Path, key: str, value: str) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"Configuration officielle absente : {path}")
    lines = path.read_text(encoding="utf-8").splitlines()
    replacement = f"{key}={value}"
    found = False
    result: list[str] = []
    for line in lines:
        if line.startswith(f"{key}="):
            result.append(replacement)
            found = True
        else:
            result.append(line)
    if not found:
        result.append(replacement)
    path.write_text("\n".join(result) + "\n", encoding="utf-8")
    path.chmod(0o600)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", choices=("principal", "hedgehog"), required=True)
    parser.add_argument("--server-name")
    parser.add_argument("--principal-host")
    parser.add_argument("--collector-name")
    args = parser.parse_args()

    values = [value for value in (args.server_name, args.principal_host, args.collector_name) if value]
    if any(not VALID_VALUE.fullmatch(value) for value in values):
        raise SystemExit("Un nom ou une adresse de déploiement est invalide")
    if args.role == "principal" and not args.server_name:
        raise SystemExit("--server-name est obligatoire pour le rôle principal")
    if args.role == "hedgehog" and not (args.principal_host and args.collector_name):
        raise SystemExit("--principal-host et --collector-name sont obligatoires pour Hedgehog")

    update_env(PROJECT_DIR / "config" / "process.env", "MALCOLM_PROFILE", "malcolm" if args.role == "principal" else "hedgehog")
    update_env(PROJECT_DIR / "config" / "beats-common.env", "BEATS_SSL", "true")

    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    state = {
        "OCULOX_ROLE": args.role,
        "OCULOX_SERVER_NAME": args.server_name or "",
        "OCULOX_PRINCIPAL_HOST": args.principal_host or "",
        "OCULOX_COLLECTOR_NAME": args.collector_name or "",
    }
    state_path = GENERATED_DIR / "deployment.env"
    state_path.write_text("".join(f"{key}={value}\n" for key, value in state.items()), encoding="utf-8")
    state_path.chmod(0o600)
    print(f"Rôle Oculox configuré : {args.role}")


if __name__ == "__main__":
    main()
