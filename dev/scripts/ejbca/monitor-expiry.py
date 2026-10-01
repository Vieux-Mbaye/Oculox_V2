#!/usr/bin/env python3
"""Report active certificate expiry and optionally install a systemd timer."""

import argparse
import importlib.util
import json
import os
import pwd
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def check() -> int:
    spec = importlib.util.spec_from_file_location("oculox_expiry_audit", ROOT / "dev/scripts/pki-audit.py")
    audit = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = audit
    spec.loader.exec_module(audit)
    _, certificates = audit.audit_all(audit.DEFAULT_MANIFEST)
    alerts = [item for item in certificates if item.status in {"WARN", "FAIL"}]
    for item in alerts:
        print(f"PKI_ALERT status={item.status} certificate={item.name} expires_in_days={item.expires_in_days}", file=sys.stderr)
    if not alerts:
        print(f"PKI_MONITOR=PASS active_entries={len(certificates)}")
    return 1 if alerts else 0


def install(render_only: bool) -> None:
    generated = ROOT / "dev/generated/pki-monitor"
    generated.mkdir(parents=True, exist_ok=True, mode=0o700)
    operator = pwd.getpwuid(os.getuid()).pw_name
    service = f"""[Unit]
Description=Oculox active PKI expiry monitor

[Service]
Type=oneshot
User={operator}
WorkingDirectory={str(ROOT).replace('%', '%%')}
Environment=PYTHONDONTWRITEBYTECODE=1
ExecStart=/usr/bin/python3 {json.dumps(str(Path(__file__).resolve()))} check
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=read-only
PrivateTmp=true
"""
    timer = """[Unit]
Description=Check Oculox certificate expiry every day

[Timer]
OnCalendar=daily
Persistent=true
RandomizedDelaySec=10m

[Install]
WantedBy=timers.target
"""
    for name, content in (("oculox-pki-expiry.service", service), ("oculox-pki-expiry.timer", timer)):
        path = generated / name
        path.write_text(content, encoding="utf-8")
        path.chmod(0o644)
    if render_only:
        print(f"PKI_MONITOR_UNITS={generated}")
        return
    subprocess.run(["sudo", "install", "-m", "0644", str(generated / "oculox-pki-expiry.service"),
                    str(generated / "oculox-pki-expiry.timer"), "/etc/systemd/system/"], check=True)
    subprocess.run(["sudo", "systemctl", "daemon-reload"], check=True)
    subprocess.run(["sudo", "systemctl", "enable", "--now", "oculox-pki-expiry.timer"], check=True)
    print("PKI_MONITOR_TIMER=ENABLED; warnings produce a failed unit and PKI_ALERT in the journal")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "install"))
    parser.add_argument("--render-only", action="store_true")
    args = parser.parse_args()
    if args.command == "check":
        return check()
    install(args.render_only)
    return 0


if __name__ == "__main__":
    sys.exit(main())
