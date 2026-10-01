#!/usr/bin/env python3
"""Revoke one exact leaf certificate in EJBCA and export its signed CRL."""

import argparse
import importlib.util
import re
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
REASONS = {"key-compromise": 1, "superseded": 4, "cessation": 5, "privilege-withdrawn": 9}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--certificate", type=Path, required=True)
    parser.add_argument("--reason", choices=REASONS, default="key-compromise")
    parser.add_argument("--output-crl", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location("oculox_revocation", Path(__file__).with_name("pki-lifecycle.py"))
    lib = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = lib
    spec.loader.exec_module(lib)
    cert = args.certificate.resolve()
    text = lib.require_ok(lib.run(["openssl", "x509", "-in", str(cert), "-noout", "-text"]), "read certificate")
    if "CA:TRUE" in text:
        raise RuntimeError("CA revocation requires a separate disaster procedure")
    issuer = lib.require_ok(lib.run(["openssl", "x509", "-in", str(cert), "-noout", "-issuer", "-nameopt", "RFC2253"]), "read issuer").strip().removeprefix("issuer=")
    serial = lib.require_ok(lib.run(["openssl", "x509", "-in", str(cert), "-noout", "-serial"]), "read serial").strip().removeprefix("serial=")
    match = re.search(r"(?:^|,)CN=(Oculox (?:Web|Internal Services|OpenSearch) CA)(?:,|$)", issuer)
    if not match or not re.fullmatch(r"[0-9A-Fa-f]+", serial):
        raise RuntimeError("not an Oculox EJBCA leaf certificate")
    ca = match.group(1)
    if args.dry_run:
        print(f"Would revoke serial={serial} issuer={ca} reason={args.reason}")
        return
    if not args.output_crl or args.output_crl.exists():
        raise RuntimeError("supply a new --output-crl path")
    lib.ejbca("ra", "revokecert", "--dn", issuer, "-s", serial, "-r", str(REASONS[args.reason]))
    lib.ejbca("ca", "createcrl", ca)
    remote = "/tmp/oculox-crl-" + secrets.token_hex(8)
    try:
        lib.ejbca("ca", "getcrl", ca, remote, "-pem")
        args.output_crl.parent.mkdir(parents=True, exist_ok=True)
        lib.docker_cp_from(remote, args.output_crl)
        args.output_crl.chmod(0o644)
    finally:
        lib.docker_exec("rm", "-f", remote)
    print(f"Revoked serial={serial}; CRL exported to {args.output_crl}")
    print("Reload the CRL in consumers that support it; CA revocation alone does not terminate existing sessions.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
