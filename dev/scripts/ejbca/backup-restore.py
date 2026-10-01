#!/usr/bin/env python3
"""Encrypted EJBCA backup, archive verification and explicit disaster restore."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import ipaddress
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
GENERATED = ROOT / "dev/ejbca/generated"
ENV = GENERATED / "ejbca.env"
COMPOSE = ROOT / "dev/ejbca/compose/docker-compose.ejbca.yml"
DB = "oculox-ejbca-db"
CA = "oculox-ejbca"
PUBLIC = ("admin", "server-tls", "agent")
EXTERNAL = "/opt/keyfactor/secrets/external/tls"


def run(*argv: str, stdin=None) -> str:
    process = subprocess.run(argv, stdin=stdin, capture_output=True, text=True, check=False)
    if process.returncode:
        raise RuntimeError(process.stderr.strip() or process.stdout.strip() or f"failed: {argv[0]}")
    return process.stdout


def compose(*args: str) -> str:
    return run("docker", "compose", "--project-directory", str(ROOT), "--env-file", str(ENV),
               "-f", str(COMPOSE), *args)


def passphrase(path: Path) -> Path:
    path = path.resolve()
    if not path.is_file() or len(path.read_bytes().strip()) < 20:
        raise RuntimeError("passphrase file missing or shorter than 20 bytes")
    if path.stat().st_mode & 0o077:
        raise RuntimeError("passphrase file permissions must be 0600")
    return path


def gpg(action: str, archive: Path, data: Path, secret: Path) -> None:
    args = ["gpg", "--batch", "--yes", "--pinentry-mode", "loopback",
            "--passphrase-file", str(secret)]
    if action == "encrypt":
        args += ["--symmetric", "--cipher-algo", "AES256", "--s2k-mode", "3",
                 "--s2k-count", "65011712", "--output", str(archive), str(data)]
    else:
        args += ["--decrypt", "--output", str(data), str(archive)]
    run(*args)


def docker_copy(source: str, destination: Path) -> None:
    run("docker", "cp", f"{CA}:{source}", str(destination))


def backup(args: argparse.Namespace) -> None:
    secret = passphrase(args.passphrase_file)
    archive = args.output.resolve()
    if archive.exists():
        raise RuntimeError("backup output already exists")
    archive.parent.mkdir(parents=True, exist_ok=True)
    compose("ps", "--services", "--status", "running")
    with tempfile.TemporaryDirectory(prefix="oculox-ejbca-backup-") as directory:
        temp = Path(directory)
        temp.chmod(0o700)
        dump = temp / "ejbca.sql"
        with dump.open("wb") as output:
            process = subprocess.run(["docker", "exec", DB, "sh", "-c",
                'MYSQL_PWD="$MYSQL_PASSWORD" exec mariadb-dump --single-transaction --routines --events --hex-blob -u "$MYSQL_USER" "$MYSQL_DATABASE"'],
                stdout=output, stderr=subprocess.PIPE, check=False)
        if process.returncode or dump.stat().st_size < 1000:
            raise RuntimeError("MariaDB dump failed: " + process.stderr.decode("utf-8", "replace")[:300])
        copied = temp / "external"
        copied.mkdir()
        for filename in ("ks/server.p12", "ks/server.storepasswd", "cas/oculox-internal-ca.crt"):
            destination = copied / filename
            destination.parent.mkdir(parents=True, exist_ok=True)
            docker_copy(f"{EXTERNAL}/{filename}", destination)
        metadata = temp / "backup.json"
        images = {}
        for service, name in (("ejbca", CA), ("ejbca-db", DB)):
            image_id = run("docker", "inspect", "-f", "{{.Image}}", name).strip()
            digests = json.loads(run("docker", "image", "inspect", image_id, "--format", "{{json .RepoDigests}}"))
            images[service] = digests[0] if digests else image_id
        metadata.write_text(json.dumps({"format": 1, "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                                       "images": images}), encoding="utf-8")
        plain = temp / "ejbca.tar.gz"
        with tarfile.open(plain, "w:gz") as tar:
            tar.add(dump, "ejbca.sql")
            tar.add(ENV, "runtime/ejbca.env")
            for name in PUBLIC:
                path = GENERATED / name
                if path.is_dir():
                    tar.add(path, f"runtime/{name}")
            tar.add(copied, "external")
            tar.add(metadata, "backup.json")
        gpg("encrypt", archive, plain, secret)
        archive.chmod(0o600)
    print(f"Encrypted EJBCA backup: {archive}")


def extract_checked(archive: Path, secret: Path, output: Path) -> None:
    plain = output / "ejbca.tar.gz"
    gpg("decrypt", archive, plain, secret)
    allowed = {"ejbca.sql", "runtime/ejbca.env",
               "external/ks/server.p12", "external/ks/server.storepasswd",
               "external/cas/oculox-internal-ca.crt"}
    found = set()
    with tarfile.open(plain, "r:gz") as tar:
        for member in tar:
            path = Path(member.name)
            if path.is_absolute() or ".." in path.parts or member.issym() or member.islnk():
                raise RuntimeError("unsafe path in backup archive")
            if member.isdir():
                continue
            if not member.isfile() or not (member.name in allowed or member.name == "backup.json" or
                    member.name.startswith("runtime/admin/") or
                    member.name.startswith("runtime/server-tls/") or
                    member.name.startswith("runtime/agent/")):
                raise RuntimeError(f"unexpected archive member: {member.name}")
            source = tar.extractfile(member)
            assert source
            target = output / path
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("wb") as destination:
                shutil.copyfileobj(source, destination)
            target.chmod(0o600)
            found.add(member.name)
    missing = allowed - found
    if missing:
        raise RuntimeError(f"incomplete EJBCA backup: {sorted(missing)}")
    if (output / "ejbca.sql").stat().st_size < 1000:
        raise RuntimeError("empty SQL dump")


def check(args: argparse.Namespace) -> None:
    secret = passphrase(args.passphrase_file)
    with tempfile.TemporaryDirectory(prefix="oculox-ejbca-check-") as directory:
        output = Path(directory)
        output.chmod(0o700)
        extract_checked(args.archive.resolve(), secret, output)
        print("EJBCA backup integrity and expected content: PASS")


def restore(args: argparse.Namespace) -> None:
    if args.confirm != "REPLACE-EJBCA-DATABASE":
        raise RuntimeError("restore requires --confirm REPLACE-EJBCA-DATABASE")
    secret = passphrase(args.passphrase_file)
    with tempfile.TemporaryDirectory(prefix="oculox-ejbca-restore-") as directory:
        output = Path(directory)
        output.chmod(0o700)
        extract_checked(args.archive.resolve(), secret, output)
        if getattr(args, "fresh", False):
            restore_fresh(output, args.bind_address)
            return
        restored_env = read_env(output / "runtime/ejbca.env")
        current_env = read_env(ENV)
        for key in ("EJBCA_DATABASE_NAME", "EJBCA_DATABASE_USER", "EJBCA_DATABASE_PASSWORD", "EJBCA_DATABASE_ROOT_PASSWORD"):
            if restored_env.get(key) != current_env.get(key):
                raise RuntimeError("Database credentials differ; restore on a fresh Core or use the original runtime env first")
        recovery = GENERATED / "backups" / ("before-restore-" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".gpg")
        recovery.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        backup(argparse.Namespace(output=recovery, passphrase_file=secret))
        # Stop only the CA; Oculox data-plane services remain running.
        compose("stop", "ejbca")
        try:
            run("docker", "exec", DB, "sh", "-c",
                'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mariadb -u root -e "$1"', "restore",
                reset_database_sql(restored_env.get("EJBCA_DATABASE_NAME", "ejbca")))
            with (output / "ejbca.sql").open("rb") as dump:
                run("docker", "exec", "-i", DB, "sh", "-c",
                    'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mariadb -u root "$MYSQL_DATABASE"', stdin=dump)
            shutil.copy2(output / "runtime/ejbca.env", ENV)
            ENV.chmod(0o600)
            for name in PUBLIC:
                source = output / "runtime" / name
                if source.is_dir():
                    shutil.copytree(source, GENERATED / name, dirs_exist_ok=True)
            image = run("docker", "inspect", "-f", "{{.Image}}", CA).strip()
            restore_external_secrets(output / "external", image)
            compose("up", "-d", "--wait", "--wait-timeout", "600", "ejbca")
        except Exception:
            print(f"Restore failed; EJBCA remains stopped. Recovery backup: {recovery}", file=sys.stderr)
            raise
    print("EJBCA restored; validate CA, profiles and TLS before issuing new certificates")


def read_env(path: Path) -> dict[str, str]:
    return dict(line.split("=", 1) for line in path.read_text(encoding="utf-8").splitlines()
                if line and not line.startswith("#") and "=" in line)


def reset_database_sql(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_]+", name):
        raise RuntimeError("Unsafe database identifier in restoration environment")
    return f"DROP DATABASE IF EXISTS `{name}`; CREATE DATABASE `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"


def restore_external_secrets(source: Path, image: str) -> None:
    run("docker", "run", "--rm", "--network", "none", "--user", "0", "--mount",
        f"type=bind,source={source},target=/source,readonly", "--mount",
        "type=volume,source=oculox-ejbca-external-secrets,target=/restore", image,
        "sh", "-c", "mkdir -p /restore/tls && cp -pR /source/. /restore/tls/ && "
        "chown -R 10001:0 /restore/tls && chmod 600 /restore/tls/ks/server.p12 /restore/tls/ks/server.storepasswd")


def restore_fresh(output: Path, bind_address: str | None = None) -> None:
    for name in (CA, DB):
        if subprocess.run(["docker", "inspect", name], capture_output=True).returncode == 0:
            raise RuntimeError("--fresh requires a Core without EJBCA containers")
    for name in ("oculox-ejbca-db-data", "oculox-ejbca-app-data", "oculox-ejbca-external-secrets"):
        if subprocess.run(["docker", "volume", "inspect", name], capture_output=True).returncode == 0:
            raise RuntimeError("--fresh refuses to overwrite existing EJBCA volumes")
    ENV.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    shutil.copy2(output / "runtime/ejbca.env", ENV)
    ENV.chmod(0o600)
    values = read_env(ENV)
    if bind_address:
        values["OCULOX_EJBCA_BIND_ADDRESS"] = str(ipaddress.ip_address(bind_address))
    if (output / "backup.json").is_file():
        images = json.loads((output / "backup.json").read_text())["images"]
        values.update(OCULOX_EJBCA_IMAGE=images["ejbca"], OCULOX_EJBCA_DB_IMAGE=images["ejbca-db"])
    ENV.write_text("".join(f"{key}={value}\n" for key, value in values.items()), encoding="utf-8")
    ENV.chmod(0o600)
    compose("up", "-d", "--wait", "--wait-timeout", "180", "ejbca-db")
    for _ in range(90):
        probe = subprocess.run(["docker", "exec", DB, "sh", "-c",
            'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mariadb -u root "$MYSQL_DATABASE" -N -e "SELECT 1"'], capture_output=True)
        if probe.returncode == 0:
            break
        time.sleep(2)
    else:
        raise RuntimeError("Restoration database not ready")
    with (output / "ejbca.sql").open("rb") as dump:
        run("docker", "exec", "-i", DB, "sh", "-c",
            'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mariadb -u root "$MYSQL_DATABASE"', stdin=dump)
    compose("create", "ejbca")
    values = read_env(ENV)
    restore_external_secrets(output / "external", values["OCULOX_EJBCA_IMAGE"])
    for name in PUBLIC:
        source = output / "runtime" / name
        if source.is_dir():
            shutil.copytree(source, GENERATED / name, dirs_exist_ok=True)
    compose("up", "-d", "--wait", "--wait-timeout", "600", "ejbca")
    print("Fresh EJBCA restore complete; preserve the old CA identity and update network bindings before enrollment")


def restore_test(args: argparse.Namespace) -> None:
    """Boot the archived database and CA with isolated names, volumes and no ports."""
    secret = passphrase(args.passphrase_file)
    with tempfile.TemporaryDirectory(prefix="oculox-ejbca-restore-test-") as directory:
        output = Path(directory)
        output.chmod(0o700)
        extract_checked(args.archive.resolve(), secret, output)
        project = "oculox-restore-test-" + output.name.rsplit("-", 1)[-1]
        config = json.loads(run("docker", "compose", "--project-directory", str(ROOT),
                            "--env-file", str(output / "runtime/ejbca.env"), "-f", str(COMPOSE),
                            "config", "--format", "json"))
        config["name"] = project
        for volume in config.get("volumes", {}).values():
            volume.pop("name", None)
        for network in config.get("networks", {}).values():
            network.pop("name", None)
        images = json.loads((output / "backup.json").read_text())["images"] if (output / "backup.json").is_file() else {}
        for service, settings in config["services"].items():
            settings.pop("container_name", None)
            settings["ports"] = []
            settings["restart"] = "no"
            if service in images:
                settings["image"] = images[service]
        config["services"]["ejbca"]["volumes"] = [volume for volume in config["services"]["ejbca"]["volumes"]
                if volume.get("target") != "/mnt/external/secrets"]
        config["services"]["ejbca"]["volumes"].append({"type": "bind", "source": str(output / "external"),
                                                       "target": "/mnt/external/secrets/tls"})
        # Docker's CA UID must read the restored secret directory.
        run("docker", "run", "--rm", "--network", "none", "--user", "0",
            "--mount", f"type=bind,source={output / 'external'},target=/restore", config["services"]["ejbca"]["image"],
            "chown", "-R", "10001:0", "/restore")
        path = output / "compose.yml"
        path.write_text(yaml.safe_dump(config), encoding="utf-8")
        path.chmod(0o600)

        def isolated(*argv):
            return run("docker", "compose", "-p", project, "-f", str(path), *argv)

        try:
            isolated("up", "-d", "ejbca-db")
            for _ in range(90):
                result = subprocess.run(["docker", "compose", "-p", project, "-f", str(path), "exec", "-T", "ejbca-db",
                    "sh", "-c", 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mariadb -u root "$MYSQL_DATABASE" -N -e "SELECT 1"'],
                    capture_output=True, check=False)
                if result.returncode == 0:
                    break
                time.sleep(2)
            else:
                raise RuntimeError("Isolated MariaDB did not become ready")
            with (output / "ejbca.sql").open("rb") as dump:
                run("docker", "compose", "-p", project, "-f", str(path), "exec", "-T", "ejbca-db", "sh", "-c",
                    'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mariadb -u root "$MYSQL_DATABASE"', stdin=dump)
            isolated("up", "-d", "ejbca")
            for _ in range(180):
                cid = isolated("ps", "-q", "ejbca").strip()
                status = run("docker", "inspect", "-f", "{{.State.Health.Status}}", cid).strip()
                if status == "healthy":
                    break
                time.sleep(3)
            else:
                raise RuntimeError("Restored EJBCA did not become healthy")
            cas = isolated("exec", "-T", "ejbca", "/opt/keyfactor/bin/ejbca.sh", "ca", "listcas")
            for name in ("Oculox Root CA", "Oculox Web CA", "Oculox Internal Services CA", "Oculox OpenSearch CA"):
                if "CA Name: " + name not in cas:
                    raise RuntimeError(f"Restored CA missing: {name}")
            isolated("exec", "-T", "ejbca", "/opt/keyfactor/bin/ejbca.sh", "ca", "getcacert", "Oculox Root CA", "/tmp/restored-root.crt")
            cid = isolated("ps", "-q", "ejbca").strip()
            run("docker", "cp", f"{cid}:/tmp/restored-root.crt", str(output / "restored-root.crt"))
            run("openssl", "verify", "-CAfile", str(output / "restored-root.crt"),
                "-untrusted", str(output / "runtime/server-tls/ca.crt"), str(output / "runtime/server-tls/cert.crt"))
            host = read_env(output / "runtime/ejbca.env").get("OCULOX_EJBCA_PUBLIC_HOST")
            if not host:
                raise RuntimeError("Archive lacks the public HTTPS hostname required for restoration verification")
            isolated("exec", "-T", "ejbca", "curl", "--noproxy", "*", "--fail", "--silent", "--show-error",
                     "--connect-to", f"{host}:8443:127.0.0.1:8443", "--cacert", "/tmp/restored-root.crt",
                     f"https://{host}:8443/ejbca/ejbca-rest-api/v1/certificate/status")
            # A new CRL proves the restored signing token can use its CA key.
            isolated("exec", "-T", "ejbca", "/opt/keyfactor/bin/ejbca.sh", "ca", "createcrl", "Oculox OpenSearch CA")
            print("RESTORE_TEST=PASS: isolated database, four CAs, TLS chain and CA signing key")
        finally:
            isolated("down", "--volumes", "--remove-orphans")
            run("docker", "run", "--rm", "--network", "none", "--user", "0",
                "--mount", f"type=bind,source={output / 'external'},target=/restore", config["services"]["ejbca"]["image"],
                "chown", "-R", f"{os.getuid()}:{os.getgid()}", "/restore")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("backup")
    b.add_argument("--output", type=Path, required=True)
    b.add_argument("--passphrase-file", type=Path, required=True)
    c = sub.add_parser("backup-check")
    c.add_argument("--archive", type=Path, required=True)
    c.add_argument("--passphrase-file", type=Path, required=True)
    r = sub.add_parser("restore")
    r.add_argument("--archive", type=Path, required=True)
    r.add_argument("--passphrase-file", type=Path, required=True)
    r.add_argument("--confirm", required=True)
    r.add_argument("--fresh", action="store_true", help="restore on a Core with no existing EJBCA containers or volumes")
    r.add_argument("--bind-address", help="local listener IP for a fresh disaster restore")
    test = sub.add_parser("restore-test")
    test.add_argument("--archive", type=Path, required=True)
    test.add_argument("--passphrase-file", type=Path, required=True)
    args = parser.parse_args()
    {"backup": backup, "backup-check": check, "restore": restore, "restore-test": restore_test}[args.command](args)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
