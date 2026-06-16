from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mcp_ops_server.execution import ExecutionProxy


def print_case(name: str, payload: dict) -> None:
    print(f"\n=== {name} ===")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main() -> None:
    proxy = ExecutionProxy()

    with tempfile.TemporaryDirectory(prefix="tmp_mcp_smoke_") as tmp:
        tmp_path = Path(tmp)
        sample_file = tmp_path / "sample.log"
        sample_file.write_text("enabled=false\nold line\n", encoding="utf-8")
        original_program_data = os.environ.get("ProgramData")
        os.environ["ProgramData"] = str(tmp_path)
        quarantine_entry = tmp_path / "tmp_mcp" / "quarantine" / "sample-quarantine.log"
        quarantine_entry.parent.mkdir(parents=True, exist_ok=True)
        quarantine_entry.write_text("quarantined\n", encoding="utf-8")

        cases = {
            "create_file_dry_run": proxy.request_create_file(
                path=str(tmp_path / "new-file.json"),
                content="{}",
                overwrite_if_exists=False,
                create_parents=False,
                dry_run=True,
                reason="smoke test",
            ).model_dump(),
            "modify_file_dry_run": proxy.request_modify_file(
                path=str(sample_file),
                operation="replace_text",
                match="enabled=false",
                content="enabled=true",
                dry_run=True,
                reason="smoke test",
            ).model_dump(),
            "delete_file_dry_run": proxy.request_delete_file(
                path=str(sample_file),
                mode="quarantine",
                dry_run=True,
                reason="smoke test",
            ).model_dump(),
            "purge_quarantine_entry_dry_run": proxy.request_purge_quarantine_entry(
                path=str(quarantine_entry),
                dry_run=True,
                reason="smoke test",
            ).model_dump(),
            "restart_service_dry_run": proxy.request_restart_service(
                service="Spooler",
                platform_hint="windows",
                dry_run=True,
                reason="smoke test",
            ).model_dump(),
            "stop_process_dry_run": proxy.request_stop_process(
                pid=999999,
                dry_run=True,
                reason="smoke test expects missing pid",
            ).model_dump(),
            "change_permissions_dry_run": proxy.request_change_permissions(
                path=str(sample_file),
                mode="0640",
                platform_hint="linux",
                dry_run=True,
                reason="smoke test",
            ).model_dump(),
            "manage_package_dry_run": proxy.request_manage_package(
                package="lsof",
                action="install",
                platform_hint="linux",
                dry_run=True,
                reason="smoke test",
            ).model_dump(),
            "network_policy_dry_run": proxy.request_network_policy_change(
                action="allow",
                protocol="tcp",
                port=8080,
                platform_hint="linux",
                dry_run=True,
                reason="smoke test",
            ).model_dump(),
            "log_cleanup_dry_run": proxy.request_log_cleanup(
                path=str(sample_file),
                mode="archive",
                dry_run=True,
                reason="smoke test",
            ).model_dump(),
        }
        if original_program_data is None:
            os.environ.pop("ProgramData", None)
        else:
            os.environ["ProgramData"] = original_program_data

    for name, payload in cases.items():
        print_case(name, payload)

    failed = [
        name
        for name, payload in cases.items()
        if name != "stop_process_dry_run" and not payload.get("ok", False)
    ]
    if failed:
        raise SystemExit(f"Smoke test failed: {', '.join(failed)}")


if __name__ == "__main__":
    main()
