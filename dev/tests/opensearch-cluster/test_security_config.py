#!/usr/bin/env python3

from pathlib import Path
import re
import subprocess
import sys

import bcrypt
import yaml


PROJECT_DIR = Path(__file__).resolve().parents[3]
SOURCE_DIR = PROJECT_DIR / "dev/config/opensearch-cluster/security"
GENERATED_DIR = PROJECT_DIR / "dev/generated/opensearch-cluster/security"

EXPECTED_ACCOUNTS = {
    "oculox_platform_admin": "oculox_platform_admin",
    "oculox_logstash": "oculox_logstash_writer",
    "oculox_arkime": "oculox_arkime_service",
    "oculox_dashboards": "oculox_dashboards_server",
    "oculox_dashboards_helper": "oculox_dashboards_helper",
    "oculox_api": "oculox_api_reader",
    "oculox_snapshot": "oculox_snapshot_operator",
}


def load_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as stream:
        value = yaml.safe_load(stream)
    if not isinstance(value, dict):
        raise AssertionError(f"YAML invalide ou vide: {path}")
    return value


def main() -> int:
    internal_users = load_yaml(GENERATED_DIR / "config/internal_users.yml")
    roles = load_yaml(SOURCE_DIR / "roles.yml")
    mappings = load_yaml(SOURCE_DIR / "roles_mapping.yml")
    security_config = load_yaml(SOURCE_DIR / "config.yml")

    actual_accounts = {key for key in internal_users if key != "_meta"}
    assert actual_accounts == set(EXPECTED_ACCOUNTS)
    assert "malcolm_internal" not in internal_users

    passwords = {}
    for line in (GENERATED_DIR / "accounts.env").read_text(encoding="utf-8").splitlines():
        key, value = line.split("=", 1)
        passwords[key] = value
    assert len(passwords) == len(EXPECTED_ACCOUNTS)
    assert len(set(passwords.values())) == len(passwords)

    hashes = set()
    for username, backend_role in EXPECTED_ACCOUNTS.items():
        account = internal_users[username]
        assert account["backend_roles"] == [backend_role]
        password_hash = account["hash"]
        assert re.fullmatch(r"\$2[ayb]\$12\$.{53}", password_hash)
        assert password_hash not in hashes
        hashes.add(password_hash)
        password = passwords[f"{username.upper()}_PASSWORD"]
        assert len(password) >= 40
        assert bcrypt.checkpw(password.encode(), password_hash.encode())

    for role in (
        "oculox_logstash_writer",
        "oculox_arkime_service",
        "oculox_dashboards_helper",
        "oculox_api_reader",
    ):
        assert role in roles
        assert role in mappings

    logstash_patterns = roles["oculox_logstash_writer"]["index_permissions"][0]["index_patterns"]
    assert set(logstash_patterns) == {"arkime_sessions3-*", "malcolm_beats_*"}
    assert "*" not in logstash_patterns

    api_actions = roles["oculox_api_reader"]["index_permissions"][0]["allowed_actions"]
    assert "read" in api_actions
    assert not any("write" in action or action == "indices_all" for action in api_actions)

    assert mappings["all_access"]["backend_roles"] == ["oculox_platform_admin"]
    assert "security_rest_api_full_access" not in mappings
    assert mappings["kibana_server"]["backend_roles"] == ["oculox_dashboards_server"]
    assert mappings["manage_snapshots"]["backend_roles"] == ["oculox_snapshot_operator"]

    dynamic = security_config["config"]["dynamic"]
    assert dynamic["http"]["anonymous_auth_enabled"] is False
    assert set(dynamic["authc"]) == {"basic_internal_auth_domain"}
    assert dynamic["kibana"]["server_username"] == "oculox_dashboards"

    git_root = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=PROJECT_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if git_root.returncode == 0:
        tracked = subprocess.run(
            ["git", "ls-files", "dev/generated/opensearch-cluster/security"],
            cwd=PROJECT_DIR,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        assert tracked.strip() == ""

    print("internal_accounts=7/7 PASS")
    print("unique_passwords=7/7 PASS")
    print("bcrypt_hashes=7/7 PASS")
    print("malcolm_internal=ABSENT PASS")
    print("least_privilege_role_boundaries=PASS")
    print("anonymous_authentication=DISABLED PASS")
    print(
        "generated_security_git_tracking=NONE PASS"
        if git_root.returncode == 0
        else "generated_security_git_tracking=NOT_APPLICABLE_DEPLOYED_TREE PASS"
    )
    print("SECURITY_CONFIG_RESULT=PASS")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, KeyError, OSError, ValueError, yaml.YAMLError) as error:
        print(f"SECURITY_CONFIG_RESULT=FAIL: {error}", file=sys.stderr)
        raise SystemExit(1)
