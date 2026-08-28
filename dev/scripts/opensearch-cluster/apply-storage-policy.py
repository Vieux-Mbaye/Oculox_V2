#!/usr/bin/env python3

"""Apply the replica, ISM and disk policy without replacing mappings."""

from __future__ import annotations

import argparse
import base64
import copy
import json
import os
import ssl
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parents[2]
STORAGE_POLICY_DIR = PROJECT_DIR / "dev/config/opensearch-cluster/storage-policy"

POLICIES = {
    "arkime_sessions": STORAGE_POLICY_DIR / "arkime-sessions-policy.json",
    "arkime_history": STORAGE_POLICY_DIR / "arkime-history-policy.json",
    "oculox_malcolm_beats": STORAGE_POLICY_DIR / "malcolm-beats-policy.json",
}

POLICY_PATTERNS = {
    "arkime_sessions": "arkime_sessions3-",
    "arkime_history": "arkime_history_v",
    "oculox_malcolm_beats": "malcolm_beats_",
}

KNOWN_TEMPLATES = (
    "malcolm_template",
    "malcolm_beats_template",
    "arkime_stats_template",
    "arkime_sessions3_ecs_template",
    "arkime_sessions3_template",
    "arkime_history_v1_template",
)

ARKIME_ALIASES = (
    "arkime_configs",
    "arkime_dstats",
    "arkime_fields",
    "arkime_files",
    "arkime_hunts",
    "arkime_lookups",
    "arkime_notifiers",
    "arkime_parliament",
    "arkime_queries",
    "arkime_sequence",
    "arkime_shareables",
    "arkime_stats",
    "arkime_users",
    "arkime_views",
)

ARKIME_DOCVALUE_FIELDS_LIMIT = 200
ARKIME_PRIMARY_SHARDS = 1
INDEX_REPLICAS = 1
ARKIME_TEMPLATE_NAMES = {
    "malcolm_template",
    "arkime_sessions3_ecs_template",
    "arkime_sessions3_template",
}
ARKIME_COMPATIBILITY_FIELDS = (
    "cert.issuerOU",
    "dhcp.classId",
    "dhcp.ja4d6",
    "dhcp.requestASN",
    "dhcp.requestGEO",
    "dhcp.requestIp",
    "dhcp.requestRIR",
    "dns.answers.class",
    "dns.answers.cname",
    "dns.answers.https",
    "dns.answers.ip",
    "dns.answers.name",
    "dns.answers.nsec",
    "dns.answers.txt",
    "dns.answers.type",
    "dns.headerFlags",
    "dns.queryHost",
    "log.origin.file.line",
    "nbns.ASN",
    "nbns.GEO",
    "nbns.RIR",
    "nbns.host",
    "nbns.ip",
    "nbns.name",
    "nbns.queryHost",
    "nbns.queryType",
    "ntp.mode",
    "ntp.refId",
    "ntp.stratum",
    "packetRange",
    "tls.ja3",
    "tls.ja3s",
)


class ApiError(RuntimeError):
    def __init__(self, method: str, path: str, status: int, body: str):
        super().__init__(f"{method} {path} returned HTTP {status}: {body[:500]}")
        self.status = status
        self.body = body


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


class OpenSearchApi:
    def __init__(self, endpoint: str, ca_file: Path, username: str, password: str):
        self.endpoint = endpoint.rstrip("/")
        self.context = ssl.create_default_context(cafile=str(ca_file))
        token = base64.b64encode(f"{username}:{password}".encode()).decode()
        self.headers = {"Authorization": f"Basic {token}"}

    def request(
        self,
        method: str,
        path: str,
        payload: Any | None = None,
        *,
        allow_status: tuple[int, ...] = (),
        timeout: int = 60,
    ) -> tuple[int, Any]:
        data = None
        headers = dict(self.headers)
        if payload is not None:
            data = json.dumps(payload, separators=(",", ":")).encode()
            headers["Content-Type"] = "application/json"
        request = Request(
            f"{self.endpoint}{path}", data=data, headers=headers, method=method
        )
        try:
            with urlopen(request, context=self.context, timeout=timeout) as response:
                body = response.read().decode()
                return response.status, json.loads(body) if body else {}
        except HTTPError as error:
            body = error.read().decode(errors="replace")
            if error.code in allow_status:
                try:
                    return error.code, json.loads(body) if body else {}
                except json.JSONDecodeError:
                    return error.code, body
            raise ApiError(method, path, error.code, body) from error
        except URLError as error:
            raise RuntimeError(f"Unable to reach {self.endpoint}: {error}") from error


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    path.chmod(0o600)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def env_int(env: dict[str, str], name: str, default: int) -> int:
    value = int(env.get(name, default))
    if value < 1:
        raise ValueError(f"{name} must be positive")
    return value


def env_bool(env: dict[str, str], name: str, default: bool) -> bool:
    raw = env.get(name, "true" if default else "false").lower()
    if raw not in {"true", "false"}:
        raise ValueError(f"{name} must be true or false")
    return raw == "true"


def configure_policy(
    source: dict[str, Any],
    *,
    enabled: bool,
    replicas: int,
    optimize_days: int | None,
    delete_enabled: bool,
    delete_days: int,
) -> dict[str, Any]:
    payload = copy.deepcopy(source)
    policy = payload["policy"]
    states = policy["states"]
    state_by_name = {state["name"]: state for state in states}

    for state in states:
        for action in state.get("actions", []):
            if "replica_count" in action:
                action["replica_count"]["number_of_replicas"] = replicas

    if not enabled:
        policy["states"] = [
            {
                "name": "hot",
                "actions": [
                    {"replica_count": {"number_of_replicas": replicas}}
                ],
                "transitions": [],
            }
        ]
        policy["default_state"] = "hot"
        policy["description"] = "Oculox lifecycle disabled; replica protection only"
        return payload

    hot = state_by_name.get("hot")
    warm = state_by_name.get("warm")
    if hot is not None and warm is not None and optimize_days is not None:
        for transition in hot.get("transitions", []):
            if transition.get("state_name") == "warm":
                transition.setdefault("conditions", {})["min_index_age"] = f"{optimize_days}d"

    if delete_enabled:
        transition_state = warm or hot
        if transition_state is not None:
            transitions = transition_state.setdefault("transitions", [])
            delete_transition = next(
                (item for item in transitions if item.get("state_name") == "delete"), None
            )
            if delete_transition is None:
                transitions.append(
                    {
                        "state_name": "delete",
                        "conditions": {"min_index_age": f"{delete_days}d"},
                    }
                )
            else:
                delete_transition.setdefault("conditions", {})[
                    "min_index_age"
                ] = f"{delete_days}d"
    else:
        for state in states:
            state["transitions"] = [
                item
                for item in state.get("transitions", [])
                if item.get("state_name") != "delete"
            ]
        policy["states"] = [state for state in states if state["name"] != "delete"]
    return payload


def configured_policies(env: dict[str, str]) -> dict[str, dict[str, Any]]:
    replicas = env_int(env, "OPENSEARCH_REPLICAS", 1)
    definitions = {
        "arkime_sessions": {
            "enabled": env_bool(env, "OPENSEARCH_POLICY_ARKIME_SESSIONS_ENABLED", True),
            "optimize_days": env_int(
                env, "OPENSEARCH_POLICY_ARKIME_SESSIONS_OPTIMIZE_DAYS", 30
            ),
            "delete_enabled": env_bool(
                env, "OPENSEARCH_POLICY_ARKIME_SESSIONS_DELETE_ENABLED", False
            ),
            "delete_days": env_int(
                env, "OPENSEARCH_POLICY_ARKIME_SESSIONS_DELETE_DAYS", 90
            ),
        },
        "arkime_history": {
            "enabled": env_bool(env, "OPENSEARCH_POLICY_ARKIME_HISTORY_ENABLED", True),
            "optimize_days": None,
            "delete_enabled": env_bool(
                env, "OPENSEARCH_POLICY_ARKIME_HISTORY_DELETE_ENABLED", False
            ),
            "delete_days": env_int(
                env, "OPENSEARCH_POLICY_ARKIME_HISTORY_DELETE_DAYS", 91
            ),
        },
        "oculox_malcolm_beats": {
            "enabled": env_bool(env, "OPENSEARCH_POLICY_BEATS_ENABLED", True),
            "optimize_days": env_int(env, "OPENSEARCH_POLICY_BEATS_OPTIMIZE_DAYS", 30),
            "delete_enabled": env_bool(
                env, "OPENSEARCH_POLICY_BEATS_DELETE_ENABLED", False
            ),
            "delete_days": env_int(env, "OPENSEARCH_POLICY_BEATS_DELETE_DAYS", 90),
        },
    }
    return {
        policy_id: configure_policy(
            load_json(POLICIES[policy_id]), replicas=replicas, **settings
        )
        for policy_id, settings in definitions.items()
    }


def configured_cluster_settings(env: dict[str, str]) -> dict[str, Any]:
    payload = load_json(STORAGE_POLICY_DIR / "cluster-settings.json")
    persistent = payload["persistent"]
    persistent["cluster.default_number_of_replicas"] = str(
        env_int(env, "OPENSEARCH_REPLICAS", 1)
    )
    persistent["cluster.routing.allocation.disk.watermark.low"] = (
        f"{env_int(env, 'OPENSEARCH_WATERMARK_LOW', 75)}%"
    )
    persistent["cluster.routing.allocation.disk.watermark.high"] = (
        f"{env_int(env, 'OPENSEARCH_WATERMARK_HIGH', 85)}%"
    )
    persistent["cluster.routing.allocation.disk.watermark.flood_stage"] = (
        f"{env_int(env, 'OPENSEARCH_WATERMARK_FLOOD_STAGE', 90)}%"
    )
    return payload


def backup_state(api: OpenSearchApi, backup_dir: Path) -> None:
    backup_dir.mkdir(parents=True, exist_ok=False)
    backup_dir.chmod(0o700)
    resources = {
        "cluster-settings.json": "/_cluster/settings?include_defaults=true&flat_settings=true",
        "index-settings.json": "/_all/_settings?expand_wildcards=all",
        "composable-templates.json": "/_index_template",
        "legacy-templates.json": "/_template",
        "aliases.json": "/_aliases?expand_wildcards=all",
        "ism-policies.json": "/_plugins/_ism/policies?size=1000",
    }
    for filename, path in resources.items():
        status, payload = api.request("GET", path, allow_status=(404,))
        write_json(backup_dir / filename, {"http_status": status, "response": payload})


def upsert_policy(api: OpenSearchApi, policy_id: str, payload: dict[str, Any]) -> None:
    status, current = api.request(
        "GET", f"/_plugins/_ism/policies/{quote(policy_id)}", allow_status=(404,)
    )
    path = f"/_plugins/_ism/policies/{quote(policy_id)}"
    if status == 200:
        query = urlencode(
            {
                "if_seq_no": current["_seq_no"],
                "if_primary_term": current["_primary_term"],
            }
        )
        path = f"{path}?{query}"
    api.request("PUT", path, payload)
    print(f"policy={policy_id} status={'updated' if status == 200 else 'created'}")


def set_resilience_settings(settings: dict[str, Any]) -> None:
    index_settings = settings.get("index")
    if isinstance(index_settings, dict):
        index_settings["number_of_replicas"] = str(INDEX_REPLICAS)
        allocation = index_settings.get("routing", {}).get("allocation", {})
        if "total_shards_per_node" in allocation:
            allocation["total_shards_per_node"] = "-1"
        settings.pop("index.number_of_replicas", None)
        settings.pop("index.routing.allocation.total_shards_per_node", None)
        return
    settings["index.number_of_replicas"] = str(INDEX_REPLICAS)
    settings.pop("number_of_replicas", None)
    if "index.routing.allocation.total_shards_per_node" in settings:
        settings["index.routing.allocation.total_shards_per_node"] = "-1"


def set_arkime_search_limits(settings: dict[str, Any]) -> None:
    index_settings = settings.get("index")
    if isinstance(index_settings, dict):
        index_settings["number_of_shards"] = str(ARKIME_PRIMARY_SHARDS)
        index_settings["max_docvalue_fields_search"] = str(ARKIME_DOCVALUE_FIELDS_LIMIT)
        settings.pop("index.number_of_shards", None)
        settings.pop("index.max_docvalue_fields_search", None)
        return
    settings["index.number_of_shards"] = str(ARKIME_PRIMARY_SHARDS)
    settings["index.max_docvalue_fields_search"] = str(ARKIME_DOCVALUE_FIELDS_LIMIT)
    settings.pop("number_of_shards", None)
    settings.pop("max_docvalue_fields_search", None)


def reconcile_template(api: OpenSearchApi, name: str) -> str:
    status, response = api.request(
        "GET", f"/_index_template/{quote(name)}", allow_status=(404,)
    )
    if status == 200 and response.get("index_templates"):
        body = copy.deepcopy(response["index_templates"][0]["index_template"])
        settings = body.setdefault("template", {}).setdefault("settings", {})
        set_resilience_settings(settings)
        if name in ARKIME_TEMPLATE_NAMES:
            set_arkime_search_limits(settings)
        api.request("PUT", f"/_index_template/{quote(name)}", body)
        return "composable-updated"

    status, response = api.request("GET", f"/_template/{quote(name)}", allow_status=(404,))
    if status == 200 and name in response:
        source = response[name]
        allowed = ("order", "version", "index_patterns", "settings", "mappings", "aliases")
        body = {key: copy.deepcopy(source[key]) for key in allowed if key in source}
        settings = body.setdefault("settings", {})
        set_resilience_settings(settings)
        if name in ARKIME_TEMPLATE_NAMES:
            set_arkime_search_limits(settings)
        api.request("PUT", f"/_template/{quote(name)}", body)
        return "legacy-updated"
    return "pending-oculox-bootstrap"


def index_settings(api: OpenSearchApi) -> dict[str, Any]:
    _, response = api.request("GET", "/_all/_settings?expand_wildcards=all")
    return response


def ensure_index_replicas(api: OpenSearchApi, settings: dict[str, Any]) -> list[str]:
    changed: list[str] = []
    for index, source in sorted(settings.items()):
        replicas = int(source.get("settings", {}).get("index", {}).get("number_of_replicas", 1))
        if replicas >= INDEX_REPLICAS:
            continue
        api.request(
            "PUT",
            f"/{quote(index, safe='._-')}/_settings",
            {"index": {"number_of_replicas": INDEX_REPLICAS}},
        )
        changed.append(index)
    return changed


def remove_index_shard_caps(api: OpenSearchApi, settings: dict[str, Any]) -> list[str]:
    changed: list[str] = []
    for index, source in sorted(settings.items()):
        allocation = source.get("settings", {}).get("index", {}).get("routing", {}).get(
            "allocation", {}
        )
        value = int(allocation.get("total_shards_per_node", -1))
        if value == -1:
            continue
        api.request(
            "PUT",
            f"/{quote(index, safe='._-')}/_settings",
            {"index": {"routing.allocation.total_shards_per_node": -1}},
        )
        changed.append(index)
    return changed


def ensure_arkime_search_limits(
    api: OpenSearchApi, settings: dict[str, Any]
) -> list[str]:
    changed: list[str] = []
    for index, source in sorted(settings.items()):
        if not index.startswith("arkime_sessions3-"):
            continue
        value = int(
            source.get("settings", {})
            .get("index", {})
            .get("max_docvalue_fields_search", 100)
        )
        if value >= ARKIME_DOCVALUE_FIELDS_LIMIT:
            continue
        api.request(
            "PUT",
            f"/{quote(index, safe='._-')}/_settings",
            {
                "index": {
                    "max_docvalue_fields_search": ARKIME_DOCVALUE_FIELDS_LIMIT
                }
            },
        )
        changed.append(index)
    return changed


def find_mapping_conflicts(field_caps: dict[str, Any]) -> dict[str, list[str]]:
    conflicts: dict[str, list[str]] = {}
    for field, definitions in field_caps.get("fields", {}).items():
        types = sorted(type_name for type_name in definitions if type_name != "unmapped")
        if len(types) > 1:
            conflicts[field] = types
    return conflicts


def arkime_mapping_conflicts(api: OpenSearchApi) -> dict[str, list[str]]:
    fields = quote(",".join(ARKIME_COMPATIBILITY_FIELDS), safe=".,_-")
    _, response = api.request(
        "GET",
        f"/arkime_sessions3-*/_field_caps?fields={fields}&include_unmapped=true",
    )
    return find_mapping_conflicts(response)


def managed_policy(api: OpenSearchApi, index: str) -> str | None:
    status, response = api.request(
        "GET", f"/_plugins/_ism/explain/{quote(index, safe='._-')}", allow_status=(404,)
    )
    if status != 200:
        return None
    item = response.get(index, {})
    return item.get("policy_id") or item.get("policy", {}).get("policy_id")


def attach_policies(api: OpenSearchApi, settings: dict[str, Any]) -> list[str]:
    results: list[str] = []
    for policy_id, prefix in POLICY_PATTERNS.items():
        for index in sorted(name for name in settings if name.startswith(prefix)):
            current = managed_policy(api, index)
            if current == policy_id:
                results.append(f"{index}:{policy_id}:unchanged")
                continue
            endpoint = "change_policy" if current else "add"
            api.request(
                "POST",
                f"/_plugins/_ism/{endpoint}/{quote(index, safe='._-')}",
                {"policy_id": policy_id},
            )
            results.append(f"{index}:{policy_id}:{endpoint}")
    return results


def ensure_malcolm_aliases(api: OpenSearchApi, settings: dict[str, Any]) -> list[str]:
    actions = []
    for index in settings:
        if index.startswith("arkime_sessions3-"):
            actions.append({"add": {"index": index, "alias": "malcolm_network"}})
        elif index.startswith("malcolm_beats_"):
            actions.append({"add": {"index": index, "alias": "malcolm_other"}})
    if actions:
        api.request("POST", "/_aliases", {"actions": actions})
    return [action["add"]["index"] for action in actions]


def alias_state(api: OpenSearchApi, alias: str) -> str:
    status, response = api.request("GET", f"/_alias/{quote(alias)}", allow_status=(404,))
    if status == 404:
        return "pending-oculox-bootstrap"
    return f"present:{len(response)}-index(es)"


def wait_for_green(api: OpenSearchApi) -> dict[str, Any]:
    _, health = api.request(
        "GET", "/_cluster/health?wait_for_status=green&timeout=180s", timeout=190
    )
    if health.get("status") != "green" or health.get("timed_out"):
        raise RuntimeError(f"Cluster did not return to green: {health}")
    return health


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--env-file",
        type=Path,
        default=PROJECT_DIR / "dev/config/opensearch-cluster/cluster.env.example",
    )
    parser.add_argument(
        "--accounts-env",
        type=Path,
        default=PROJECT_DIR / "dev/generated/opensearch-cluster/security/accounts.env",
    )
    parser.add_argument(
        "--ca-file",
        type=Path,
        default=PROJECT_DIR
        / "dev/generated/opensearch-cluster/pki/client-trust/oculox-opensearch-ca.crt",
    )
    parser.add_argument("--endpoint")
    parser.add_argument("--backup-root", type=Path)
    return parser.parse_args()


def main() -> int:
    global ARKIME_DOCVALUE_FIELDS_LIMIT, ARKIME_PRIMARY_SHARDS, INDEX_REPLICAS
    args = parse_args()
    env = {**read_env(args.env_file), **read_env(args.accounts_env), **os.environ}
    ARKIME_DOCVALUE_FIELDS_LIMIT = env_int(
        env, "OPENSEARCH_MAX_DOCVALUE_FIELDS_SEARCH", 200
    )
    ARKIME_PRIMARY_SHARDS = env_int(env, "OPENSEARCH_PRIMARY_SHARDS", 1)
    INDEX_REPLICAS = env_int(env, "OPENSEARCH_REPLICAS", 1)
    endpoint = args.endpoint or env.get("OPENSEARCH_CLUSTER_ENDPOINT")
    password = env.get("OCULOX_PLATFORM_ADMIN_PASSWORD")
    if not endpoint:
        raise RuntimeError("OPENSEARCH_CLUSTER_ENDPOINT is not configured")
    if not password:
        raise RuntimeError("OCULOX_PLATFORM_ADMIN_PASSWORD is not configured")
    if not args.ca_file.is_file():
        raise RuntimeError(f"CA file not found: {args.ca_file}")
    for policy_file in POLICIES.values():
        load_json(policy_file)

    api = OpenSearchApi(endpoint, args.ca_file, "oculox_platform_admin", password)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    backup_root = args.backup_root or (
        PROJECT_DIR / "dev/generated/opensearch-cluster/storage-policy/backups"
    )
    backup_dir = backup_root / timestamp

    _, health = api.request("GET", "/_cluster/health")
    expected_cluster_name = env.get("OPENSEARCH_CLUSTER_NAME", "oculox-opensearch")
    if health.get("cluster_name") != expected_cluster_name:
        raise RuntimeError(f"Unexpected cluster identity: {health.get('cluster_name')}")
    if int(health.get("number_of_nodes", 0)) != 3:
        raise RuntimeError(f"Storage policy requires all three nodes, got: {health}")

    backup_state(api, backup_dir)
    print(f"backup={backup_dir}")

    api.request("PUT", "/_cluster/settings", configured_cluster_settings(env))
    print("cluster_settings=applied")

    for policy_id, policy_payload in configured_policies(env).items():
        upsert_policy(api, policy_id, policy_payload)

    template_results = {name: reconcile_template(api, name) for name in KNOWN_TEMPLATES}
    for name, status in template_results.items():
        print(f"template={name} status={status}")

    before = index_settings(api)
    changed_indices = ensure_index_replicas(api, before)
    uncapped_indices = remove_index_shard_caps(api, before)
    arkime_search_limits_changed = ensure_arkime_search_limits(api, before)
    current = index_settings(api)
    policy_results = attach_policies(api, current)
    alias_indices = ensure_malcolm_aliases(api, current)
    mapping_conflicts = arkime_mapping_conflicts(api)
    if mapping_conflicts:
        raise RuntimeError(
            "Arkime mapping conflicts require reindexing: "
            + json.dumps(mapping_conflicts, sort_keys=True)
        )

    aliases = {alias: alias_state(api, alias) for alias in ARKIME_ALIASES}
    aliases["malcolm_network"] = alias_state(api, "malcolm_network")
    aliases["malcolm_other"] = alias_state(api, "malcolm_other")

    health = wait_for_green(api)
    summary = {
        "applied_at": datetime.now(timezone.utc).isoformat(),
        "cluster_name": health["cluster_name"],
        "cluster_status": health["status"],
        "nodes": health["number_of_nodes"],
        "backup": str(backup_dir),
        "primary_shards_decision": ARKIME_PRIMARY_SHARDS,
        "replicas": INDEX_REPLICAS,
        "replica_indices_changed": changed_indices,
        "shard_caps_removed": uncapped_indices,
        "arkime_search_limits_changed": arkime_search_limits_changed,
        "arkime_mapping_conflicts": mapping_conflicts,
        "template_results": template_results,
        "policy_assignments": policy_results,
        "malcolm_alias_indices": alias_indices,
        "alias_results": aliases,
    }
    write_json(backup_dir.parent / "last-apply-summary.json", summary)
    print(f"replica_indices_changed={len(changed_indices)}")
    print(f"shard_caps_removed={len(uncapped_indices)}")
    print(f"arkime_search_limits_changed={len(arkime_search_limits_changed)}")
    print(f"policy_assignments={len(policy_results)}")
    print(f"cluster={health['status']} nodes={health['number_of_nodes']}")
    print("STORAGE_POLICY_APPLY_RESULT=PASS")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ApiError, RuntimeError, KeyError, ValueError, json.JSONDecodeError) as error:
        print(f"STORAGE_POLICY_APPLY_RESULT=FAIL: {error}", file=sys.stderr)
        sys.exit(1)
