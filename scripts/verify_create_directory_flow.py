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

from mcp_ops_server.approvals import ApprovalStore  # noqa: E402
from mcp_ops_server.audit import AuditEvent, AuditLogger  # noqa: E402
from mcp_ops_server.execution import ExecutionPolicy, ExecutionProxy  # noqa: E402
from mcp_ops_server.tool_groups import (  # noqa: E402
    register_approval_tools,
    register_audit_tools,
    register_execution_tools,
)


class FakeMCP:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self):
        def deco(fn):
            self.tools[fn.__name__] = fn
            return fn

        return deco


def main() -> None:
    checks: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="tmp_mcp_create_dir_") as tmp:
        root = Path(tmp)
        audit_logger = AuditLogger(root / "audit")
        approval_store = ApprovalStore(root / "approvals")
        execution_policy = ExecutionPolicy()
        proxy = ExecutionProxy()
        mcp = FakeMCP()
        register_execution_tools(
            mcp,
            proxy=proxy,
            audit_logger=audit_logger,
            approval_store=approval_store,
            execution_policy=execution_policy,
        )
        register_approval_tools(mcp, approval_store=approval_store, audit_logger=audit_logger)
        register_audit_tools(mcp, audit_logger=audit_logger)

        target_dir = root / "plans" / "demo-dir"
        dry_run = mcp.tools["request_create_directory"](
            path=str(target_dir),
            create_parents=True,
            dry_run=True,
            reason="verify create directory flow",
            session_id="session-create-dir",
            trace_id="trace-create-dir",
        )
        _require_human_report(dry_run)
        check(checks, dry_run.get("ok") is True, "dry-run plan succeeds")
        dry_data = dry_run.get("data", {})
        check(checks, dry_data.get("action") == "create_directory", "dry-run action recorded")
        check(checks, dry_data.get("status") == "planned", "dry-run status is planned")
        check(checks, isinstance(dry_data.get("least_privilege"), dict), "dry-run least_privilege exists")
        check(checks, dry_data.get("trace_id") == "trace-create-dir", "dry-run trace_id preserved")
        check(checks, target_dir.exists() is False, "dry-run does not create directory")

        approval_request = dry_data.get("approval_request")
        check(checks, isinstance(approval_request, dict), "dry-run includes approval_request")
        check(checks, isinstance(dry_data.get("approval_scope_hash"), str) and dry_data["approval_scope_hash"].startswith("sha256:"), "approval scope hash exists")
        check(checks, isinstance(dry_data.get("execute_after_approval"), dict), "execute_after_approval exists")

        request_payload = dict(approval_request or {})
        request_payload["requester"] = "verify-script"
        request_payload["expires_in_minutes"] = 30
        approval_request_result = mcp.tools["request_operation_approval_tool"](**request_payload)
        _require_human_report(approval_request_result)
        approval_id = approval_request_result["data"].get("approval_id")
        check(checks, isinstance(approval_id, str) and approval_id.startswith("appr_"), "approval request returns approval_id")

        grant_result = mcp.tools["record_operation_approval_tool"](
            approval_id=approval_id,
            decision="grant",
            approver="verify-admin",
            comment="sandbox create directory verification",
        )
        _require_human_report(grant_result)
        check(checks, grant_result["data"]["approval"]["status"] == "granted", "approval grant succeeds")

        execute_after = dry_data.get("execute_after_approval") or {}
        execute_params = dict(execute_after.get("params") or {})
        execute_params["approval_id"] = approval_id
        execute_result = mcp.tools["request_create_directory"](**execute_params)
        _require_human_report(execute_result)
        exec_data = execute_result.get("data", {})
        check(checks, execute_result.get("ok") is True, "real execution succeeds")
        check(checks, exec_data.get("status") == "executed", "real execution status is executed")
        check(checks, exec_data.get("directory_created") is True, "directory_created is true")
        check(checks, exec_data.get("target_exists") is True, "target_exists is true")
        post_checks = exec_data.get("post_checks") if isinstance(exec_data.get("post_checks"), dict) else {}
        check(checks, isinstance(post_checks, dict) and post_checks.get("ok") is True, "post_checks ok")
        checks_list = post_checks.get("checks") if isinstance(post_checks, dict) else []
        check(checks, _has_check(checks_list, "directory_exists_after_create"), "post_checks include directory_exists_after_create")
        check(checks, _has_check(checks_list, "directory_is_directory"), "post_checks include directory_is_directory")
        check(checks, isinstance(exec_data.get("rollback_hint"), list) and bool(exec_data["rollback_hint"]), "rollback_hint exists")
        check(checks, target_dir.exists() and target_dir.is_dir(), "directory exists on disk after execution")

        approval_validation = exec_data.get("approval_validation")
        execution_validation = exec_data.get("execution_validation")
        check(checks, isinstance(approval_validation, dict) and approval_validation.get("ok") is True, "approval validation passes")
        check(checks, isinstance(execution_validation, dict) and execution_validation.get("ok") is True, "execution validation passes")

        remote_result = mcp.tools["request_create_directory"](
            path=str(target_dir / "remote-dir"),
            target="linux-prod-01",
            platform_hint="linux",
            create_parents=True,
            dry_run=True,
            reason="verify remote rejection",
        )
        check(checks, remote_result.get("ok") is True, "remote create directory returns reference plan")
        remote_data = remote_result.get("data", {})
        remote_execution = remote_data.get("remote_execution", {}) if isinstance(remote_data.get("remote_execution"), dict) else {}
        check(checks, remote_data.get("status") == "planned", "remote reference status is planned")
        check(checks, remote_execution.get("mode") == "reference_only", "remote reference mode is explicit")
        check(checks, remote_execution.get("transport") == "ssh", "remote reference transport captured")

        existing_result = mcp.tools["request_create_directory"](
            path=str(target_dir),
            create_parents=True,
            dry_run=False,
            approval_id=approval_id,
            reason="verify existing directory rejection",
        )
        check(checks, existing_result.get("ok") is False, "existing directory execution is rejected")

        audit_events = mcp.tools["get_audit_events_tool"](limit=20, trace_id="trace-create-dir")
        events = audit_events.get("data", {}).get("events", [])
        event_types = {event.get("event_type") for event in events if isinstance(event, dict)}
        check(checks, "guardrail_decision" in event_types, "audit contains guardrail_decision")
        check(checks, "tool_result" in event_types, "audit contains tool_result")
        check(checks, "approval_requested" in event_types, "audit contains approval_requested")
        check(checks, "approval_granted" in event_types, "audit contains approval_granted")

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


def _has_check(items: Any, name: str) -> bool:
    if not isinstance(items, list):
        return False
    return any(isinstance(item, dict) and item.get("name") == name and item.get("ok") is True for item in items)


def _require_human_report(result: dict[str, Any]) -> None:
    data = result.get("data")
    if not isinstance(data, dict):
        raise AssertionError("missing data payload")
    report = data.get("human_report")
    if not isinstance(report, dict):
        raise AssertionError("missing human_report")


if __name__ == "__main__":
    main()
