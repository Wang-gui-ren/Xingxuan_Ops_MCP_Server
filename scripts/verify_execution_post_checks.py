from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mcp_ops_server.execution import ExecutionProxy  # noqa: E402


def main() -> None:
    checks: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="tmp_mcp_post_checks_") as temp_dir:
        sample_file = Path(temp_dir) / "app.conf"
        sample_file.write_text("enabled=false\n", encoding="utf-8")

        proxy = ExecutionProxy()
        result = proxy.request_modify_file(
            path=str(sample_file),
            operation="replace_text",
            content="enabled=true",
            match="enabled=false",
            backup=True,
            dry_run=False,
            reason="verify post checks on sandbox file",
        ).model_dump()

        data = result.get("data", {})
        post_checks = data.get("post_checks") if isinstance(data, dict) else {}
        checks_list = post_checks.get("checks") if isinstance(post_checks, dict) else []

        check(checks, result.get("ok") is True, "sandbox modify_file execution succeeds")
        check(checks, data.get("status") == "executed", "execution status is recorded")
        check(checks, isinstance(data.get("pre_hash"), str) and data["pre_hash"].startswith("sha256:"), "pre hash is recorded")
        check(checks, isinstance(data.get("post_hash"), str) and data["post_hash"].startswith("sha256:"), "post hash is recorded")
        check(checks, data.get("pre_hash") != data.get("post_hash"), "file hash changes after write")
        check(checks, isinstance(post_checks, dict) and post_checks.get("ok") is True, "post checks are successful")
        check(checks, _has_check(checks_list, "file_hash_changed"), "post checks include file_hash_changed")
        check(checks, _has_check(checks_list, "backup_created"), "post checks include backup_created")
        check(checks, isinstance(data.get("rollback_hint"), list) and bool(data["rollback_hint"]), "rollback hint is returned")
        check(checks, "enabled=true" in sample_file.read_text(encoding="utf-8"), "sandbox file content changed")

        overwrite_file = Path(temp_dir) / "overwrite.conf"
        overwrite_file.write_text("alpha=1\nbeta=2\n", encoding="utf-8")
        overwrite_result = proxy.request_modify_file(
            path=str(overwrite_file),
            operation="overwrite",
            content="gamma=3\n",
            backup=True,
            dry_run=False,
            reason="verify overwrite support",
        ).model_dump()
        overwrite_data = overwrite_result.get("data", {})
        overwrite_post_checks = overwrite_data.get("post_checks") if isinstance(overwrite_data, dict) else {}
        check(checks, overwrite_result.get("ok") is True, "sandbox overwrite execution succeeds")
        check(checks, overwrite_data.get("status") == "executed", "overwrite execution status is recorded")
        check(checks, isinstance(overwrite_data.get("pre_hash"), str) and overwrite_data["pre_hash"].startswith("sha256:"), "overwrite pre hash is recorded")
        check(checks, isinstance(overwrite_data.get("post_hash"), str) and overwrite_data["post_hash"].startswith("sha256:"), "overwrite post hash is recorded")
        check(checks, isinstance(overwrite_post_checks, dict) and overwrite_post_checks.get("ok") is True, "overwrite post checks are successful")
        check(checks, "gamma=3" in overwrite_file.read_text(encoding="utf-8"), "overwrite file content changed")

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


def _has_check(items: Any, name: str) -> bool:
    if not isinstance(items, list):
        return False
    return any(isinstance(item, dict) and item.get("name") == name and item.get("ok") is True for item in items)


def check(checks: list[dict[str, Any]], condition: bool, name: str) -> None:
    checks.append({"name": name, "status": "PASS" if condition else "FAIL"})


if __name__ == "__main__":
    main()
