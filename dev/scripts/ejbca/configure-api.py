#!/usr/bin/env python3
"""Install an EJBCA-issued TLS certificate on WildFly and expose the API on Core."""

from __future__ import annotations

import argparse
import datetime as dt
import ipaddress
import os
import re
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ENV = ROOT / "dev/ejbca/generated/ejbca.env"
TLS = ROOT / "dev/ejbca/generated/server-tls"
BACKUPS = ROOT / "dev/ejbca/generated/backups/wildfly"
CONTAINER = "oculox-ejbca"
REMOTE_CONFIG = "/opt/keyfactor/wildfly-39.0.1.Final/standalone/configuration"
REMOTE_EXTERNAL_TLS = "/opt/keyfactor/secrets/external/tls/ks"
REMOTE_AGENT_CA = "/opt/keyfactor/secrets/external/tls/cas/oculox-internal-ca.crt"
COMPOSE = ROOT / "dev/ejbca/compose/docker-compose.ejbca.yml"


def checked(args: list[str], *, env: dict | None = None) -> str:
    result = subprocess.run(args, text=True, capture_output=True, env=env, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f"Command failed: {args[0]}")
    return result.stdout


def compose(*args: str) -> str:
    return checked(["docker", "compose", "--project-directory", str(ROOT),
                    "--env-file", str(ENV), "-f", str(COMPOSE), *args])


def env_set(key: str, value: str) -> None:
    if not ENV.is_file():
        raise FileNotFoundError(f"Run ./oculox pki-ca init: {ENV}")
    lines = ENV.read_text(encoding="utf-8").splitlines()
    new_line = f"{key}={value}"
    for index, line in enumerate(lines):
        if line.startswith(key + "="):
            lines[index] = new_line
            break
    else:
        lines.append(new_line)
    temporary = ENV.with_suffix(".new")
    temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    os.replace(temporary, ENV)


def env_get(key: str, default: str) -> str:
    if not ENV.is_file():
        return default
    for line in ENV.read_text(encoding="utf-8").splitlines():
        if line.startswith(key + "="):
            return line.split("=", 1)[1]
    return default


def public_host(value: str) -> str:
    try:
        ipaddress.ip_address(value)
        return value
    except ValueError:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{0,252}", value):
            raise ValueError("Invalid public hostname")
        return value


def keystore_password(xml_file: Path) -> str:
    tree = ET.parse(xml_file)
    for element in tree.iter():
        if element.tag.endswith("key-store") and element.attrib.get("name") == "httpsKS":
            for child in element:
                if child.tag.endswith("credential-reference"):
                    return child.attrib["clear-text"]
    raise RuntimeError("WildFly HTTPS keystore password not found")


def copy_from(remote: str, local: Path) -> None:
    checked(["docker", "cp", f"{CONTAINER}:{remote}", str(local)])


def copy_to(local: Path, remote: str) -> None:
    checked(["docker", "cp", str(local), f"{CONTAINER}:{remote}"])


def wait_ready(host: str, port: int, ca: Path) -> None:
    for _ in range(60):
        result = subprocess.run(["curl", "--silent", "--show-error", "--fail", "--max-time", "5",
                                 "--cacert", str(ca),
                                 f"https://{host}:{port}/ejbca/ejbca-rest-api/v1/certificate/status"],
                                capture_output=True, text=True, check=False)
        if result.returncode == 0:
            return
        time.sleep(3)
    raise RuntimeError("EJBCA API TLS validation failed after restart")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-host", required=True)
    parser.add_argument("--https-port", type=int, default=18443)
    parser.add_argument("--bind-address", help="local listener IP (required when public-host is DNS)")
    args = parser.parse_args()
    host = public_host(args.public_host)
    try:
        bind_address = str(ipaddress.ip_address(args.bind_address or host))
    except ValueError as exc:
        raise ValueError("For a DNS public-host, supply --bind-address <local-IP>") from exc
    if not 1 <= args.https_port <= 65535:
        raise ValueError("Invalid HTTPS port")
    previous_bind = env_get("OCULOX_EJBCA_BIND_ADDRESS", "127.0.0.1")
    previous_public_host = env_get("OCULOX_EJBCA_PUBLIC_HOST", "")
    previous_port = env_get("OCULOX_EJBCA_HTTPS_PORT", "18443")
    env_set("OCULOX_EJBCA_PUBLIC_HOST", host)
    checked([str(ROOT / "oculox"), "pki", "enroll", "--provider", "ejbca",
             "--service", "ejbca_api_server", "--install"])
    for name in ("cert.crt", "key.key", "ca.crt"):
        if not (TLS / name).is_file():
            raise FileNotFoundError(TLS / name)
    with tempfile.TemporaryDirectory(prefix="oculox-ejbca-api-") as directory:
        temporary = Path(directory)
        xml = temporary / "standalone.xml"
        copy_from(f"{REMOTE_CONFIG}/standalone.xml", xml)
        password = keystore_password(xml)
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = BACKUPS / stamp
        backup.mkdir(parents=True, mode=0o700)
        copy_from(f"{REMOTE_CONFIG}/keystore.p12", backup / "keystore.p12")
        bundle = temporary / "server.p12"
        environment = os.environ.copy()
        environment["OCULOX_PKCS12_PASSWORD"] = password
        checked(["openssl", "pkcs12", "-export", "-inkey", str(TLS / "key.key"),
                 "-in", str(TLS / "cert.crt"), "-certfile", str(TLS / "ca.crt"),
                 "-name", "https", "-out", str(bundle), "-passout", "env:OCULOX_PKCS12_PASSWORD"],
                env=environment)
        bundle.chmod(0o600)
        password_file = temporary / "server.storepasswd"
        password_file.write_text(password + "\n", encoding="ascii")
        password_file.chmod(0o600)
        previous_external = {}
        previous_agent_ca = None
        try:
            # The image's external secret path is a symlink to a separate volume.
            # Older deployments may need one restart to attach that volume.
            attached = subprocess.run(["docker", "exec", CONTAINER, "test", "-d", "/mnt/external/secrets"], check=False)
            if attached.returncode:
                compose("up", "-d", "--force-recreate", "ejbca")
            remote_ca = f"/tmp/oculox-agent-ca-{os.getpid()}.crt"
            try:
                checked(["docker", "exec", CONTAINER, "/opt/keyfactor/bin/ejbca.sh", "ca",
                         "getcacert", "Oculox Internal Services CA", remote_ca])
                agent_ca = temporary / "agent-ca.crt"
                copy_from(remote_ca, agent_ca)
            finally:
                checked(["docker", "exec", "-u", "0", CONTAINER, "rm", "-f", remote_ca])
            checked(["openssl", "verify", "-CAfile", str(TLS / "ca.crt"), str(agent_ca)])
            checked(["docker", "exec", "-u", "0", CONTAINER, "mkdir", "-p", REMOTE_EXTERNAL_TLS])
            checked(["docker", "exec", "-u", "0", CONTAINER, "mkdir", "-p",
                     str(Path(REMOTE_AGENT_CA).parent)])
            ca_exists = subprocess.run(["docker", "exec", CONTAINER, "test", "-f", REMOTE_AGENT_CA], check=False)
            if ca_exists.returncode == 0:
                previous_agent_ca = backup / "oculox-internal-ca.crt"
                copy_from(REMOTE_AGENT_CA, previous_agent_ca)
            copy_to(agent_ca, REMOTE_AGENT_CA)
            for filename in ("server.p12", "server.storepasswd"):
                remote = f"{REMOTE_EXTERNAL_TLS}/{filename}"
                exists = subprocess.run(["docker", "exec", CONTAINER, "test", "-f", remote], check=False)
                if exists.returncode == 0:
                    saved = backup / filename
                    copy_from(remote, saved)
                    saved.chmod(0o600)
                    previous_external[filename] = saved
            copy_to(bundle, f"{REMOTE_EXTERNAL_TLS}/server.p12")
            copy_to(password_file, f"{REMOTE_EXTERNAL_TLS}/server.storepasswd")
            checked(["docker", "exec", "-u", "0", CONTAINER, "chown", "10001:0",
                     f"{REMOTE_EXTERNAL_TLS}/server.p12", f"{REMOTE_EXTERNAL_TLS}/server.storepasswd"])
            env_set("OCULOX_EJBCA_BIND_ADDRESS", bind_address)
            env_set("OCULOX_EJBCA_HTTPS_PORT", str(args.https_port))
            compose("up", "-d", "--force-recreate", "ejbca")
            wait_ready(host, args.https_port, TLS / "ca.crt")
        except Exception:
            if previous_agent_ca is not None:
                copy_to(previous_agent_ca, REMOTE_AGENT_CA)
            else:
                checked(["docker", "exec", "-u", "0", CONTAINER, "rm", "-f", REMOTE_AGENT_CA])
            for filename in ("server.p12", "server.storepasswd"):
                remote = f"{REMOTE_EXTERNAL_TLS}/{filename}"
                if filename in previous_external:
                    copy_to(previous_external[filename], remote)
                else:
                    checked(["docker", "exec", "-u", "0", CONTAINER, "rm", "-f", remote])
            env_set("OCULOX_EJBCA_BIND_ADDRESS", previous_bind)
            env_set("OCULOX_EJBCA_PUBLIC_HOST", previous_public_host)
            env_set("OCULOX_EJBCA_HTTPS_PORT", previous_port)
            compose("up", "-d", "--force-recreate", "ejbca")
            raise
        print(f"EJBCA API ready at https://{host}:{args.https_port}; keystore backup: {backup}")


if __name__ == "__main__":
    main()
