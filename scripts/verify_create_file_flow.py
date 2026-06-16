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
    with tempfile.TemporaryDirectory(prefix="tmp_mcp_create_file_") as tmp:
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

        target_file = root / "plans" / "demo.json"
        dry_run = mcp.tools["request_create_file"](
            path=str(target_file),
            content="{}",
            overwrite_if_exists=False,
            create_parents=True,
            dry_run=True,
            reason="verify create file flow",
            session_id="session-create-file",
            trace_id="trace-create-file",
        )
        _require_human_report(dry_run)
        check(checks, dry_run.get("ok") is True, "dry-run plan succeeds")
        dry_data = dry_run.get("data", {})
        check(checks, dry_data.get("action") == "create_file", "dry-run action recorded")
        check(checks, dry_data.get("status") == "planned", "dry-run status is planned")
        check(checks, isinstance(dry_data.get("least_privilege"), dict), "dry-run least_privilege exists")
        check(checks, dry_data.get("trace_id") == "trace-create-file", "dry-run trace_id preserved")
        check(checks, target_file.exists() is False, "dry-run does not create file")

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
            comment="sandbox create file verification",
        )
        _require_human_report(grant_result)
        check(checks, grant_result["data"]["approval"]["status"] == "granted", "approval grant succeeds")

        execute_after = dry_data.get("execute_after_approval") or {}
        execute_params = dict(execute_after.get("params") or {})
        execute_params["approval_id"] = approval_id
        execute_result = mcp.tools["request_create_file"](**execute_params)
        _require_human_report(execute_result)
        exec_data = execute_result.get("data", {})
        check(checks, execute_result.get("ok") is True, "real execution succeeds")
        check(checks, exec_data.get("status") == "executed", "real execution status is executed")
        check(checks, exec_data.get("created_file") is True, "created_file is true")
        check(checks, exec_data.get("target_exists") is True, "target_exists is true")
        check(checks, exec_data.get("pre_hash") in {None, ""}, "new file pre_hash is empty")
        check(checks, isinstance(exec_data.get("post_hash"), str) and exec_data["post_hash"].startswith("sha256:"), "post_hash exists")
        post_checks = exec_data.get("post_checks") if isinstance(exec_data.get("post_checks"), dict) else {}
        check(checks, isinstance(post_checks, dict) and post_checks.get("ok") is True, "post_checks ok")
        checks_list = post_checks.get("checks") if isinstance(post_checks, dict) else []
        check(checks, _has_check(checks_list, "file_exists_after_create"), "post_checks include file_exists_after_create")
        check(checks, _has_check(checks_list, "file_is_regular_after_create"), "post_checks include file_is_regular_after_create")
        check(checks, _has_check(checks_list, "file_content_matches_requested"), "post_checks include file_content_matches_requested")
        check(checks, isinstance(exec_data.get("rollback_hint"), list) and bool(exec_data["rollback_hint"]), "rollback_hint exists")
        check(checks, target_file.exists() and target_file.is_file(), "file exists on disk after execution")
        check(checks, target_file.read_text(encoding="utf-8") == "{}", "file content matches expected content")

        approval_validation = exec_data.get("approval_validation")
        execution_validation = exec_data.get("execution_validation")
        check(checks, isinstance(approval_validation, dict) and approval_validation.get("ok") is True, "approval validation passes")
        check(checks, isinstance(execution_validation, dict) and execution_validation.get("ok") is True, "execution validation passes")

        existing_result = mcp.tools["request_create_file"](
            path=str(target_file),
            content='{"updated":true}',
            overwrite_if_exists=False,
            create_parents=False,
            dry_run=False,
            approval_id=approval_id,
            reason="verify existing file rejection",
        )
        check(checks, existing_result.get("ok") is False, "existing file without overwrite is rejected")

        overwrite_dry_run = mcp.tools["request_create_file"](
            path=str(target_file),
            content='{"updated":true}',
            overwrite_if_exists=True,
            create_parents=False,
            dry_run=True,
            reason="verify overwrite create file flow",
            session_id="session-create-file-overwrite",
            trace_id="trace-create-file-overwrite",
        )
        overwrite_request = dict((overwrite_dry_run.get("data") or {}).get("approval_request") or {})
        overwrite_request["requester"] = "verify-script"
        overwrite_request["expires_in_minutes"] = 30
        overwrite_approval = mcp.tools["request_operation_approval_tool"](**overwrite_request)
        overwrite_approval_id = overwrite_approval["data"].get("approval_id")
        mcp.tools["record_operation_approval_tool"](
            approval_id=overwrite_approval_id,
            decision="grant",
            approver="verify-admin",
            comment="sandbox overwrite verification",
        )
        overwrite_params = dict(((overwrite_dry_run.get("data") or {}).get("execute_after_approval") or {}).get("params") or {})
        overwrite_params["approval_id"] = overwrite_approval_id
        overwrite_result = mcp.tools["request_create_file"](**overwrite_params)
        _require_human_report(overwrite_result)
        overwrite_data = overwrite_result.get("data", {})
        check(checks, overwrite_result.get("ok") is True, "overwrite execution succeeds")
        check(checks, isinstance(overwrite_data.get("pre_hash"), str) and overwrite_data["pre_hash"].startswith("sha256:"), "overwrite pre_hash exists")
        check(checks, isinstance(overwrite_data.get("post_hash"), str) and overwrite_data["post_hash"].startswith("sha256:"), "overwrite post_hash exists")
        check(checks, isinstance(overwrite_data.get("backup_path"), str) and bool(overwrite_data["backup_path"]), "overwrite backup path exists")
        check(checks, target_file.read_text(encoding="utf-8") == '{"updated":true}', "overwrite content applied")

        missing_parent_file = root / "missing" / "parent" / "demo.json"
        missing_parent_result = mcp.tools["request_create_file"](
            path=str(missing_parent_file),
            content="{}",
            overwrite_if_exists=False,
            create_parents=False,
            dry_run=False,
            approval_id=approval_id,
            reason="verify missing parent rejection",
        )
        check(checks, missing_parent_result.get("ok") is False, "missing parent without create_parents is rejected")

        create_parents_dry_run = mcp.tools["request_create_file"](
            path=str(missing_parent_file),
            content="{}",
            overwrite_if_exists=False,
            create_parents=True,
            dry_run=True,
            reason="verify create parents create file flow",
            session_id="session-create-file-parents",
            trace_id="trace-create-file-parents",
        )
        create_parents_request = dict((create_parents_dry_run.get("data") or {}).get("approval_request") or {})
        create_parents_request["requester"] = "verify-script"
        create_parents_request["expires_in_minutes"] = 30
        create_parents_approval = mcp.tools["request_operation_approval_tool"](**create_parents_request)
        create_parents_approval_id = create_parents_approval["data"].get("approval_id")
        mcp.tools["record_operation_approval_tool"](
            approval_id=create_parents_approval_id,
            decision="grant",
            approver="verify-admin",
            comment="sandbox parent creation verification",
        )
        create_parents_params = dict(((create_parents_dry_run.get("data") or {}).get("execute_after_approval") or {}).get("params") or {})
        create_parents_params["approval_id"] = create_parents_approval_id
        create_parents_result = mcp.tools["request_create_file"](**create_parents_params)
        check(checks, create_parents_result.get("ok") is True, "create_parents execution succeeds")
        check(checks, missing_parent_file.exists(), "create_parents created nested file")

        remote_result = mcp.tools["request_create_file"](
            path=str(root / "remote" / "demo.json"),
            content="{}",
            target="linux-prod-01",
            platform_hint="linux",
            overwrite_if_exists=False,
            create_parents=False,
            dry_run=True,
            reason="verify remote create-file reference",
        )
        check(checks, remote_result.get("ok") is True, "remote create file returns reference plan")
        remote_data = remote_result.get("data", {})
        remote_execution = remote_data.get("remote_execution", {}) if isinstance(remote_data.get("remote_execution"), dict) else {}
        check(checks, remote_data.get("status") == "planned", "remote reference status is planned")
        check(checks, remote_execution.get("mode") == "reference_only", "remote reference mode is explicit")
        check(checks, remote_execution.get("transport") == "ssh", "remote reference transport captured")

        protected_path = "C:\\Windows\\System32\\blocked.txt" if sys.platform.startswith("win") else "/etc/blocked.conf"
        protected_result = mcp.tools["request_create_file"](
            path=protected_path,
            content="blocked",
            overwrite_if_exists=False,
            create_parents=False,
            dry_run=True,
            reason="verify protected path rejection",
        )
        check(checks, protected_result.get("ok") is False, "protected path create-file is rejected")

        audit_events = mcp.tools["get_audit_events_tool"](limit=40, trace_id="trace-create-file")
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
