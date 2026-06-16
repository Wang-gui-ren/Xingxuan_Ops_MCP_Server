from __future__ import annotations

import json
import tempfile
from pathlib import Path

from mcp_ops_server.audit import AuditEvent, AuditLogger
from mcp_ops_server.guardrails import OperationContext, validate_intent
from mcp_ops_server.tool_groups.audit_tools import register_audit_tools


class FakeMCP:
    """用于 smoke 测试的最小 MCP 注册器，避免启动完整 AstrBot。"""

    def __init__(self) -> None:
        self.tools = {}

    def tool(self):
        def deco(fn):
            self.tools[fn.__name__] = fn
            return fn

        return deco


def print_case(name: str, payload: dict) -> None:
    print(f"\n=== {name} ===")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main() -> None:
    cases = {
        "critical_rm_rf": OperationContext(
            tool_name="request_delete_file",
            operation="delete_file",
            command="rm -rf /",
            path="/",
            params={"path": "/", "mode": "delete"},
            dry_run=True,
        ),
        "high_log_cleanup_dry_run": OperationContext(
            tool_name="request_log_cleanup",
            operation="log_cleanup",
            path="/var/log/nginx/access.log",
            params={"path": "/var/log/nginx/access.log", "mode": "archive"},
            dry_run=True,
        ),
        "high_restart_requires_approval": OperationContext(
            tool_name="request_restart_service",
            operation="restart_service",
            params={"service": "nginx"},
            dry_run=False,
        ),
        "high_restart_with_approval": OperationContext(
            tool_name="request_restart_service",
            operation="restart_service",
            params={"service": "nginx"},
            dry_run=False,
            approval_id="APPROVAL-smoke-001",
        ),
    }

    decisions = {name: validate_intent(context) for name, context in cases.items()}
    for name, decision in decisions.items():
        print_case(name, decision.to_dict())

    assert decisions["critical_rm_rf"].decision == "deny"
    assert decisions["critical_rm_rf"].risk_level == "critical"
    assert decisions["high_log_cleanup_dry_run"].decision == "require_approval"
    assert decisions["high_log_cleanup_dry_run"].allowed is True
    assert decisions["high_restart_requires_approval"].allowed is False
    assert decisions["high_restart_with_approval"].allowed is True

    for command in ("rm -rf /", "sudo rm -rf /", "rm -rf -- /", "rm -rf /*"):
        decision = validate_intent(
            OperationContext(
                tool_name="shell",
                operation="execute_command",
                command=command,
                dry_run=True,
            )
        )
        print_case(f"raw_command_{command}", decision.to_dict())
        assert decision.decision == "deny"
        assert decision.risk_level == "critical"

    with tempfile.TemporaryDirectory(prefix="tmp_mcp_audit_") as tmp:
        logger = AuditLogger(Path(tmp))
        logger.append(
            AuditEvent(
                event_type="guardrail_decision",
                tool_name="request_delete_file",
                risk_level=decisions["critical_rm_rf"].risk_level,
                decision=decisions["critical_rm_rf"].decision,
                params_summary={"password": "should-not-leak", "path": "/"},
                result_summary=decisions["critical_rm_rf"].to_dict(),
            )
        )
        events = logger.read_recent(limit=5)
        print_case("audit_events", {"events": events})
        assert events
        assert events[0]["params_summary"]["password"] == "***REDACTED***"

        mcp = FakeMCP()
        register_audit_tools(mcp, audit_logger=logger)
        result = mcp.tools["validate_operation_intent_tool"](
            tool_name="shell",
            operation="execute_command",
            command="rm -rf /",
            dry_run=True,
            user_intent="检查 command=rm -rf / 是否安全，不执行命令。",
            target="local",
            platform_hint="auto",
        )
        print_case("validate_operation_intent_tool_rm_rf", result)
        assert result["ok"] is False
        assert result["risk_level"] == "critical"
        assert result["data"]["decision"]["decision"] == "deny"


if __name__ == "__main__":
    main()
