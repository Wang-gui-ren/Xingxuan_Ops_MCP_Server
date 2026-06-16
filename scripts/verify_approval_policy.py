from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mcp_ops_server.approvals import (  # noqa: E402
    ApprovalStore,
    build_approval_scope_hash,
    clear_policy_cache,
    evaluate_approval_policy,
    load_approval_policy,
    verify_approval_chain,
)


def main() -> None:
    checks: list[dict[str, Any]] = []
    old_policy_file = os.environ.get("TMP_MCP_APPROVAL_POLICY_FILE")
    with tempfile.TemporaryDirectory(prefix="tmp_mcp_approval_policy_") as tmp:
        root = Path(tmp)
        policy_file = root / "policies.yaml"
        policy_file.write_text(_policy_text(), encoding="utf-8")
        os.environ["TMP_MCP_APPROVAL_POLICY_FILE"] = str(policy_file)
        clear_policy_cache()
        try:
            policy = load_approval_policy()
            check(checks, policy.loaded_from_config, "policy loads from temp config")
            check(checks, policy.source_path == str(policy_file), "policy records source path")

            decision = evaluate_approval_policy(
                tool_name="request_modify_file",
                operation="modify_file",
                target="local",
                risk_level="high",
                params={"path": str(root / "policy.conf")},
            )
            check(checks, decision.required_approvals == 2, "modify_file policy requires two approvals")
            check(checks, decision.ttl_minutes == 20, "policy compresses ttl")
            check(checks, "MODIFY_FILE_TWO_APPROVERS" in decision.matched_rule_ids, "policy records matched rule")
            check(checks, set(decision.allowed_approver_ids) == {"approver-a", "approver-b"}, "policy resolves allowed approvers")

            critical = evaluate_approval_policy(
                tool_name="shell",
                operation="execute_command",
                target="local",
                risk_level="critical",
                params={"command": "sudo rm -rf /"},
            )
            check(checks, critical.decision == "deny_request", "critical policy denies request")

            store = ApprovalStore(root / "approvals")
            params = _approval_params(root / "policy.conf")
            requested = store.request_approval(
                tool_name="request_modify_file",
                operation="modify_file",
                target="local",
                params=params,
                plan={"action": "modify_file", "path": params["path"]},
                risk_level="high",
                requester="requester-a",
                reason="approval policy verification",
                expires_in_minutes=120,
                trace_id="trace-policy",
                session_id="session-policy",
            )
            check(checks, requested.status == "requested", "policy request starts requested")
            check(checks, requested.schema_version == 3, "policy request uses schema version 3")
            check(checks, requested.required_approvals == 2, "request stores required approvals")
            check(checks, requested.granted_approvals == 0, "request stores zero granted approvals")
            check(checks, requested.policy_ttl_minutes == 20, "request stores policy ttl")
            check(checks, "MODIFY_FILE_TWO_APPROVERS" in requested.policy_rule_ids, "request stores policy rule ids")
            check(checks, _minutes_until(requested.expires_at) <= 21, "request expires_at is capped by policy ttl")

            partial = store.record_decision(
                approval_id=requested.approval_id,
                decision="grant",
                approver="approver-a",
                comment="first approval",
            )
            check(checks, partial.status == "partially_granted", "first grant leaves approval partially granted")
            check(checks, partial.granted_approvals == 1, "partial grant records one grant")
            check(checks, len(partial.approver_history) == 1, "partial grant records approver history")

            partial_validation = store.validate_approval(
                approval_id=requested.approval_id,
                tool_name="request_modify_file",
                operation="modify_file",
                target="local",
                params=params,
            )
            check(checks, not partial_validation.ok, "partially granted approval cannot execute")
            check(checks, "approval not fully granted" in partial_validation.errors, "partial validation has stable error")

            expect_raises(
                checks,
                "duplicate approver is rejected",
                lambda: store.record_decision(
                    approval_id=requested.approval_id,
                    decision="grant",
                    approver="approver-a",
                ),
                "duplicate approver",
            )
            expect_raises(
                checks,
                "untrusted approver is rejected",
                lambda: store.record_decision(
                    approval_id=requested.approval_id,
                    decision="grant",
                    approver="outsider",
                ),
                "approver not allowed",
            )

            granted = store.record_decision(
                approval_id=requested.approval_id,
                decision="grant",
                approver="approver-b",
                comment="second approval",
            )
            check(checks, granted.status == "granted", "second distinct grant approves request")
            check(checks, granted.granted_approvals == 2, "granted record stores two grants")
            check(checks, len(granted.approver_history) == 2, "granted record preserves approver history")

            granted_validation = store.validate_approval(
                approval_id=requested.approval_id,
                tool_name="request_modify_file",
                operation="modify_file",
                target="local",
                params=dict(params, approval_id=requested.approval_id),
            )
            check(checks, granted_validation.ok, "fully granted approval validates")

            scope_without_none = build_approval_scope_hash(
                "request_modify_file",
                "modify_file",
                "local",
                params,
            )
            scope_with_none = build_approval_scope_hash(
                "request_modify_file",
                "modify_file",
                "local",
                dict(params, optional_default=None),
            )
            check(checks, scope_with_none == scope_without_none, "scope hash ignores optional None defaults")

            scope_with_execution_context = build_approval_scope_hash(
                "request_modify_file",
                "modify_file",
                "local",
                dict(
                    params,
                    platform_hint="windows",
                    target="local",
                    dry_run=False,
                    reason="real execution retry",
                    session_id="session-inline",
                    trace_id="trace-inline",
                ),
            )
            check(
                checks,
                scope_with_execution_context == scope_without_none,
                "scope hash ignores execution-context approval drift",
            )

            renewed = store.renew_approval(
                approval_id=requested.approval_id,
                renewed_by="approver-a",
                expires_in_minutes=120,
                comment="renew once",
            )
            check(checks, renewed.renewal_count == 1, "renewal count increments once")
            check(checks, renewed.max_renewals == 1, "renewal keeps max renewal policy")
            expect_raises(
                checks,
                "second renewal is rejected",
                lambda: store.renew_approval(
                    approval_id=requested.approval_id,
                    renewed_by="approver-b",
                    expires_in_minutes=10,
                ),
                "max renewals exceeded",
            )

            self_request = store.request_approval(
                tool_name="request_modify_file",
                operation="modify_file",
                target="local",
                params=params,
                risk_level="high",
                requester="approver-a",
                expires_in_minutes=20,
            )
            expect_raises(
                checks,
                "self approval is rejected",
                lambda: store.record_decision(
                    approval_id=self_request.approval_id,
                    decision="grant",
                    approver="approver-a",
                ),
                "self approval denied",
            )

            expect_raises(
                checks,
                "critical approval request is denied",
                lambda: store.request_approval(
                    tool_name="shell",
                    operation="execute_command",
                    target="local",
                    params={"command": "sudo rm -rf /"},
                    risk_level="critical",
                    requester="requester-a",
                ),
                "approval request denied by policy",
            )

            chain = verify_approval_chain(store.ledger_path())
            check(checks, chain.ok, "approval policy records keep hash chain valid")
        finally:
            if old_policy_file is None:
                os.environ.pop("TMP_MCP_APPROVAL_POLICY_FILE", None)
            else:
                os.environ["TMP_MCP_APPROVAL_POLICY_FILE"] = old_policy_file
            clear_policy_cache()

    report = {
        "total": len(checks),
        "passed": sum(1 for item in checks if item["status"] == "PASS"),
        "failed": sum(1 for item in checks if item["status"] == "FAIL"),
        "checks": checks,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["failed"]:
        raise SystemExit(1)


def _approval_params(path: Path) -> dict[str, Any]:
    path.write_text("enabled=false\n", encoding="utf-8")
    return {
        "path": str(path),
        "operation": "replace_text",
        "content": "enabled=true",
        "match": "enabled=false",
        "backup": True,
        "target": "local",
        "platform_hint": "auto",
        "dry_run": False,
        "reason": "approval policy verification",
    }


def _minutes_until(value: str) -> float:
    parsed = datetime.fromisoformat(value).astimezone(timezone.utc)
    return (parsed - datetime.now(timezone.utc)).total_seconds() / 60


def _policy_text() -> str:
    return """
version: "test"
default:
  decision: allow_request
  ttl_minutes: 60
  max_renewals: 1
  required_approvals: 1
  require_distinct_approvers: true
  allow_self_approval: false
approvers:
  trusted_ids:
    - approver-a
    - approver-b
  roles:
    policy_admin:
      - approver-a
      - approver-b
rules:
  - id: CRITICAL_DENY
    match:
      risk_level: critical
    decision: deny_request
    reason: "critical 风险不能通过审批放行"
  - id: MODIFY_FILE_TWO_APPROVERS
    match:
      operation: modify_file
    ttl_minutes: 20
    required_approvals: 2
    max_renewals: 1
    approver_roles:
      - policy_admin
    reason: "策略验证要求双人审批"
"""


def check(checks: list[dict[str, Any]], condition: bool, name: str) -> None:
    checks.append({"name": name, "status": "PASS" if condition else "FAIL"})
    if not condition:
        raise AssertionError(name)


def expect_raises(checks: list[dict[str, Any]], name: str, action: Callable[[], Any], expected: str) -> None:
    try:
        action()
    except ValueError as exc:
        if expected in str(exc):
            checks.append({"name": name, "status": "PASS"})
            return
        checks.append({"name": name, "status": "FAIL", "error": str(exc)})
        raise
    checks.append({"name": name, "status": "FAIL"})
    raise AssertionError(name)


if __name__ == "__main__":
    main()
