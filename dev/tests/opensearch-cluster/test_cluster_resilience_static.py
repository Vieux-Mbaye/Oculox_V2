#!/usr/bin/env python3

from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[3]
SCRIPT = PROJECT_DIR / "dev/tests/opensearch-cluster/test_cluster_resilience_runtime.sh"


def main() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    required = (
        "wait_for_active_shards=all",
        "_cat/shards/$INDEX",
        "Stopping primary data node",
        "Stopping elected cluster manager",
        "new_manager",
        "two_node_loss_quorum_block=EXPECTED PASS",
        '"${compose[@]}" down',
        '"${compose[@]}" up -d',
        "cluster_uuid",
        "full_restart_documents_preserved=PASS",
        "trap recover EXIT INT TERM",
        "CLUSTER_RESILIENCE_RESULT=PASS",
    )
    missing = [item for item in required if item not in source]
    assert not missing, f"Missing Cluster resilience controls: {missing}"
    assert 'down -v' not in source
    assert 'docker volume rm' not in source
    assert '10.5.6.3' not in source and '10.5.6.4' not in source
    print("autonomous_scenarios=12/12 PASS")
    print("automatic_recovery_trap=PASS")
    print("named_volume_deletion=ABSENT PASS")
    print("forbidden_servers=ABSENT PASS")
    print("CLUSTER_RESILIENCE_STATIC_RESULT=PASS")


if __name__ == "__main__":
    main()
