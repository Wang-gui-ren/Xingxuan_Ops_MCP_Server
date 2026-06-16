from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
PARSER_DIR = ROOT / "integrations" / "astrbot_filesystem_command"

for candidate in (SRC, PARSER_DIR):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from intent_parser import parse_intent  # type: ignore  # noqa: E402
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
    with tempfile.TemporaryDirectory(prefix="tmp_mcp_ops_bridge_") as tmp:
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

        log_file = root / "logs" / "app.log"
        log_file.parent.mkdir(parents=True, exist_ok=True)
        log_file.write_text("bridge log cleanup verification\n", encoding="utf-8")

        cases = [
            {
                "name": "bridge_create_file_windows",
                "message": "在 G:\\完整mcp 中建立一个文件 111.json",
                "tool_name": "request_create_file",
                "expect_action": "create_file",
                "expect_platform_hint": "windows",
                "arg_checks": {
                    "dry_run": True,
                    "overwrite_if_exists": False,
                    "create_parents": False,
                    "content": "",
                    "path": "G:\\完整mcp\\111.json",
                },
            },
            {
                "name": "bridge_create_directory_windows",
                "message": "在 C:\\tmp 这个文件夹新建一个空文件夹：名字叫 test1",
                "tool_name": "request_create_directory",
                "expect_action": "create_directory",
                "expect_platform_hint": "windows",
                "arg_checks": {"dry_run": True, "create_parents": True},
            },
            {
                "name": "bridge_restart_service_windows",
                "message": "重启 Spooler 服务",
                "tool_name": "request_restart_service",
                "expect_action": "restart_service",
                "expect_platform_hint": "windows",
                "arg_checks": {"dry_run": True, "service": "Spooler"},
            },
            {
                "name": "bridge_network_policy_allow",
                "message": "开放 tcp 8080 端口",
                "tool_name": "request_network_policy_change",
                "expect_action": "network_policy_change",
                "expect_platform_hint": "auto",
                "arg_checks": {"dry_run": True, "action": "allow", "protocol": "tcp", "port": 8080},
            },
            {
                "name": "bridge_log_cleanup_windows",
                "message": f"隔离 {log_file}",
                "tool_name": "request_log_cleanup",
                "expect_action": "delete_file",
                "expect_platform_hint": "windows",
                "arg_checks": {"dry_run": True, "mode": "quarantine", "path": str(log_file)},
            },
        ]

        for index, case in enumerate(cases, start=1):
            session_id = f"bridge-session-{index}"
            trace_id = f"bridge-trace-{index}"
            _run_case(
                checks,
                mcp=mcp,
                audit_logger=audit_logger,
                message=case["message"],
                expected_tool_name=case["tool_name"],
                expected_action=case["expect_action"],
                expected_platform_hint=case["expect_platform_hint"],
                expected_args=case["arg_checks"],
                session_id=session_id,
                trace_id=trace_id,
                case_name=case["name"],
            )

        complex_intent = parse_intent("帮我看看 nginx 为什么不可用")
        check(checks, complex_intent is None, "complex_question_not_matched_by_bridge")

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


def _run_case(
    checks: list[dict[str, Any]],
    *,
    mcp: FakeMCP,
    audit_logger: AuditLogger,
    message: str,
    expected_tool_name: str,
    expected_action: str,
    expected_platform_hint: str,
    expected_args: dict[str, Any],
    session_id: str,
    trace_id: str,
    case_name: str,
) -> None:
    intent = parse_intent(message)
    check(checks, intent is not None, f"{case_name}: intent parsed")
    if intent is None:
        return

    check(checks, intent.tool_name == expected_tool_name, f"{case_name}: expected tool selected")
    for key, value in expected_args.items():
        check(checks, intent.arguments.get(key) == value, f"{case_name}: argument {key} matched")
    check(checks, intent.arguments.get("platform_hint") == expected_platform_hint, f"{case_name}: platform_hint matched")

    tool = mcp.tools.get(intent.tool_name)
    check(checks, callable(tool), f"{case_name}: tool registered in MCP")
    if not callable(tool):
        return

    call_args = dict(intent.arguments)
    call_args["session_id"] = session_id
    call_args["trace_id"] = trace_id
    result = tool(**call_args)

    _require_human_report(result)
    check(checks, result.get("ok") is True, f"{case_name}: dry-run result ok")
    check(checks, result.get("risk_level") == "high", f"{case_name}: dry-run risk high")

    data = result.get("data", {})
    check(checks, data.get("dry_run") is True, f"{case_name}: data.dry_run true")
    check(checks, data.get("status") == "planned", f"{case_name}: planned status")
    check(checks, data.get("action") == expected_action, f"{case_name}: action recorded")
    check(checks, data.get("trace_id") == trace_id, f"{case_name}: trace_id preserved")
    check(checks, data.get("session_id") == session_id, f"{case_name}: session_id preserved")

    approval_request = data.get("approval_request")
    check(checks, isinstance(approval_request, dict), f"{case_name}: approval_request exists")
    if isinstance(approval_request, dict):
        check(checks, approval_request.get("tool_name") == expected_tool_name, f"{case_name}: approval_request tool name matched")
        check(checks, approval_request.get("trace_id") == trace_id, f"{case_name}: approval_request trace_id matched")

    execute_after = data.get("execute_after_approval")
    check(checks, isinstance(execute_after, dict), f"{case_name}: execute_after_approval exists")
    if isinstance(execute_after, dict):
        params = execute_after.get("params")
        check(checks, isinstance(params, dict), f"{case_name}: execute_after params exists")
        if isinstance(params, dict):
            check(checks, params.get("dry_run") is False, f"{case_name}: execute_after dry_run false")
            check(checks, isinstance(params.get("approval_id"), str) and bool(params.get("approval_id")), f"{case_name}: execute_after approval placeholder exists")

    scope_hash = data.get("approval_scope_hash")
    check(checks, isinstance(scope_hash, str) and scope_hash.startswith("sha256:"), f"{case_name}: approval_scope_hash exists")

    report = data.get("human_report")
    if isinstance(report, dict):
        check(checks, report.get("trace_id") == trace_id, f"{case_name}: human_report trace_id matched")

    audit_events = _get_audit_events(audit_logger, trace_id=trace_id)
    event_types = {event.get("event_type") for event in audit_events if isinstance(event, dict)}
    check(checks, "guardrail_decision" in event_types, f"{case_name}: audit includes guardrail_decision")
    check(checks, "tool_result" in event_types, f"{case_name}: audit includes tool_result")


def _get_audit_events(audit_logger: AuditLogger, *, trace_id: str) -> list[dict[str, Any]]:
    events = audit_logger.read_recent(limit=20, trace_id=trace_id)
    output: list[dict[str, Any]] = []
    for item in events:
        if isinstance(item, AuditEvent):
            output.append(item.to_dict())
        elif isinstance(item, dict):
            output.append(item)
    return output


def _require_human_report(result: dict[str, Any]) -> None:
    data = result.get("data")
    if not isinstance(data, dict):
        raise AssertionError("missing data payload")
    report = data.get("human_report")
    if not isinstance(report, dict):
        raise AssertionError("missing human_report")


def check(checks: list[dict[str, Any]], condition: bool, name: str) -> None:
    checks.append({"name": name, "status": "PASS" if condition else "FAIL"})


if __name__ == "__main__":
    main()
