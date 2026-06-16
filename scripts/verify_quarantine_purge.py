from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mcp_ops_server.execution import ExecutionPolicy, ExecutionProxy  # noqa: E402


def main() -> None:
    checks: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="tmp_mcp_quarantine_purge_") as temp_dir:
        temp_root = Path(temp_dir)
        program_data = temp_root / "ProgramData"
        os.environ["ProgramData"] = str(program_data)

        proxy = ExecutionProxy()
        policy = ExecutionPolicy()

        source_file = temp_root / "sample.log"
        source_file.write_text("purge me\n", encoding="utf-8")

        quarantine_result = proxy.request_delete_file(
            path=str(source_file),
            mode="quarantine",
            dry_run=False,
            reason="prepare quarantine entry for purge verification",
        ).model_dump()
        quarantine_data = quarantine_result.get("data", {})
        quarantined_path = Path(str(quarantine_data.get("result_path") or ""))

        check(checks, quarantine_result.get("ok") is True, "quarantine execution succeeds")
        check(checks, quarantined_path.exists(), "quarantine result path exists")

        dry_run_result = proxy.request_purge_quarantine_entry(
            path=str(quarantined_path),
            dry_run=True,
            reason="verify purge dry-run",
        ).model_dump()
        dry_data = dry_run_result.get("data", {})
        check(checks, dry_run_result.get("ok") is True, "purge dry-run succeeds")
        check(checks, dry_data.get("status") == "planned", "purge dry-run status is planned")
        check(checks, dry_data.get("plan", {}).get("quarantine_root"), "purge dry-run records quarantine root")

        policy_validation = policy.validate(
            tool_name="request_purge_quarantine_entry",
            operation="purge_quarantine_entry",
            target="local",
            platform_hint="windows",
            params={"path": str(quarantined_path), "recursive": False, "platform_hint": "windows"},
            dry_run=False,
            approval_validation={"ok": True, "errors": []},
        )
        check(checks, policy_validation.ok is True, "execution policy allows real purge inside quarantine root")

        execute_result = proxy.request_purge_quarantine_entry(
            path=str(quarantined_path),
            dry_run=False,
            reason="verify purge execution",
        ).model_dump()
        execute_data = execute_result.get("data", {})
        post_checks = execute_data.get("post_checks") if isinstance(execute_data, dict) else {}
        check(checks, execute_result.get("ok") is True, "purge execution succeeds")
        check(checks, not quarantined_path.exists(), "quarantine entry is removed after purge")
        check(checks, isinstance(post_checks, dict) and post_checks.get("ok") is True, "purge post checks are successful")

        outside_file = temp_root / "outside.log"
        outside_file.write_text("nope\n", encoding="utf-8")
        denied_policy = policy.validate(
            tool_name="request_purge_quarantine_entry",
            operation="purge_quarantine_entry",
            target="local",
            platform_hint="windows",
            params={"path": str(outside_file), "recursive": False, "platform_hint": "windows"},
            dry_run=False,
            approval_validation={"ok": True, "errors": []},
        )
        check(checks, denied_policy.ok is False, "execution policy rejects purge outside quarantine root")
        check(
            checks,
            any("path_not_in_quarantine_root" in error for error in denied_policy.errors),
            "outside path reports quarantine root error",
        )

    failed = [item for item in checks if item["status"] != "PASS"]
    payload = {
        "total": len(checks),
        "passed": len(checks) - len(failed),
        "failed": len(failed),
        "checks": checks,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if failed:
        raise SystemExit(1)


def check(checks: list[dict[str, Any]], condition: bool, name: str) -> None:
    checks.append({"name": name, "status": "PASS" if condition else "FAIL"})


if __name__ == "__main__":
    main()
