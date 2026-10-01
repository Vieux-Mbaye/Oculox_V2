#!/usr/bin/env python3
"""Package current tracked sources and reviewed dev additions without runtime secrets."""

import argparse
import hashlib
import io
import json
import re
import subprocess
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXCLUDED = {".git", ".aws", ".codex", ".agents", "generated", "__pycache__", "results"}


def sources():
    result = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
                            cwd=ROOT, capture_output=True, check=True)
    for name in sorted(set(result.stdout.decode().split("\0")) - {""}):
        path = Path(name)
        if EXCLUDED.intersection(path.parts) or "contexte_session" in path.name:
            continue
        if path.parts[0] in {"suricata-logs", "pcap", "zeek-logs", "filescan-logs"} and path.name != ".gitignore":
            continue
        if path.suffix in {".key", ".p12", ".pfx", ".pem", ".gpg"} or path.name.endswith(".curlrc"):
            continue
        source = ROOT / path
        if not source.is_file():
            continue
        if source.is_symlink() and not source.resolve().is_relative_to(ROOT):
            raise RuntimeError(f"External symlink cannot be delivered: {name}")
        if re.search(rb"^-----BEGIN (?:RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----\r?$", source.read_bytes(), re.M):
            raise RuntimeError(f"Private key in source: {name}")
        yield name, source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() or output.is_relative_to(ROOT):
        raise RuntimeError("Use a new archive path outside the source tree")
    manifest = {}
    with tarfile.open(output, "w:gz") as archive:
        for name, source in sources():
            archive.add(source, arcname="Oculox/" + name, recursive=False)
            manifest[name] = hashlib.sha256(source.read_bytes()).hexdigest()
        payload = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
        info = tarfile.TarInfo("Oculox/INSTALLATION_SOURCE_MANIFEST.json")
        info.size, info.mode = len(payload), 0o644
        archive.addfile(info, io.BytesIO(payload))
    print(f"SOURCE_DELIVERY={output} files={len(manifest)} sha256={hashlib.sha256(output.read_bytes()).hexdigest()}")


if __name__ == "__main__":
    main()
