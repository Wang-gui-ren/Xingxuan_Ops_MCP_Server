from __future__ import annotations

import json
import tempfile
from pathlib import Path

from mcp_ops_server.collectors import (
    check_http_endpoint,
    check_network_connectivity,
    collect_network_connections,
    diagnose_disk_full,
    diagnose_high_cpu,
    diagnose_port_conflict,
    get_file_stat,
    read_log_excerpt,
    resolve_dns,
    run_troubleshooting_pipeline,
)


def print_case(name: str, payload: dict) -> None:
    print(f"\n=== {name} ===")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="tmp_mcp_diag_") as tmp:
        tmp_path = Path(tmp)
        log_file = tmp_path / "app.log"
        log_file.write_text("info boot\nerror failed to connect\ninfo retry\n", encoding="utf-8")

        cases = {
            "dns_localhost": resolve_dns("localhost"),
            "ping_loopback": check_network_connectivity("127.0.0.1", count=1),
            "http_loopback_closed": check_http_endpoint("http://127.0.0.1:1", timeout_seconds=1),
            "file_stat": get_file_stat(str(log_file), include_hash=True),
            "log_excerpt": read_log_excerpt(str(log_file), lines=10, keyword="error"),
            "network_connections": {"connections": collect_network_connections(limit=5)},
            "diagnose_high_cpu": diagnose_high_cpu(limit=3),
            "diagnose_disk_full": diagnose_disk_full(root_path=str(tmp_path), min_size_mb=1, limit=5),
            "diagnose_port_conflict": diagnose_port_conflict(port=1),
            "pipeline_disk_full": run_troubleshooting_pipeline(
                scenario="disk_full",
                root_path=str(tmp_path),
                min_size_mb=1,
                limit=5,
            ),
        }

    for name, payload in cases.items():
        print_case(name, payload)

    required_keys = {
        "dns_localhost": "resolved",
        "ping_loopback": "reachable",
        "file_stat": "exists",
        "log_excerpt": "ok",
        "diagnose_high_cpu": "steps",
        "diagnose_disk_full": "steps",
        "pipeline_disk_full": "steps",
    }
    failed = [
        name
        for name, key in required_keys.items()
        if key not in cases[name]
    ]
    if failed:
        raise SystemExit(f"Diagnostics smoke test failed: {', '.join(failed)}")


if __name__ == "__main__":
    main()
