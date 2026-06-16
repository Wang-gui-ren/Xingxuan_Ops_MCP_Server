from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mcp_ops_server.approvals import (  # noqa: E402
    ApprovalStore,
    clear_policy_cache,
    create_enterprise_identity_assertion,
    verify_approval_chain,
)
from mcp_ops_server.audit import AuditLogger  # noqa: E402
from mcp_ops_server.tool_groups import register_approval_tools  # noqa: E402


class FakeMCP:
    def __init__(self) -> None:
        self.tools: dict[str, Callable[..., dict[str, Any]]] = {}

    def tool(self):
        def deco(fn):
            self.tools[fn.__name__] = fn
            return fn

        return deco


def main() -> None:
    checks: list[dict[str, Any]] = []
    env_keys = [
        "TMP_MCP_APPROVAL_POLICY_FILE",
        "TMP_MCP_APPROVAL_IDENTITY_SECRET",
        "TMP_MCP_REQUIRE_APPROVAL_IDENTITY",
        "TMP_MCP_REQUIRE_APPROVAL_IDENTITY_SCOPE",
        "TMP_MCP_ENABLE_ENTERPRISE_APPROVAL_TOKEN_ISSUER",
        "TMP_MCP_ENTERPRISE_IDENTITY_ASSERTION_SECRET",
        "TMP_MCP_ENTERPRISE_IDENTITY_ALLOWED_ISSUERS",
        "TMP_MCP_ENTERPRISE_APPROVER_ROLE",
    ]
    old_env = {key: os.environ.get(key) for key in env_keys}
    with tempfile.TemporaryDirectory(prefix="tmp_mcp_approval_console_") as tmp:
        root = Path(tmp)
        policy_file = root / "policies.yaml"
        policy_file.write_text(_policy_text(), encoding="utf-8")
        os.environ["TMP_MCP_APPROVAL_POLICY_FILE"] = str(policy_file)
        os.environ["TMP_MCP_APPROVAL_IDENTITY_SECRET"] = "verify-approval-identity-secret"
        os.environ["TMP_MCP_REQUIRE_APPROVAL_IDENTITY"] = "true"
        os.environ["TMP_MCP_REQUIRE_APPROVAL_IDENTITY_SCOPE"] = "true"
        os.environ["TMP_MCP_ENABLE_ENTERPRISE_APPROVAL_TOKEN_ISSUER"] = "true"
        os.environ["TMP_MCP_ENTERPRISE_IDENTITY_ASSERTION_SECRET"] = "verify-enterprise-assertion-secret"
        os.environ["TMP_MCP_ENTERPRISE_IDENTITY_ALLOWED_ISSUERS"] = "verify-enterprise-idp"
        os.environ["TMP_MCP_ENTERPRISE_APPROVER_ROLE"] = "ops_approver"
        clear_policy_cache()
        try:
            mcp = FakeMCP()
            audit_logger = AuditLogger(root / "audit")
            approval_store = ApprovalStore(root / "approvals")
            register_approval_tools(mcp, approval_store=approval_store, audit_logger=audit_logger)

            request = mcp.tools["request_operation_approval_tool"](
                tool_name="request_modify_file",
                operation="modify_file",
                target="local",
                params=_approval_params(root / "console.conf"),
                plan={"action": "modify_file", "path": str(root / "console.conf")},
                risk_level="high",
                requester="requester-a",
                reason="approval console verification",
                trace_id="trace-approval-console",
                session_id="session-approval-console",
            )
            check(checks, request["ok"] is True, "approval request succeeds")
            approval = request["data"]["approval"]
            approval_id = request["data"]["approval_id"]

            console = mcp.tools["get_approval_console_bundle_tool"](approval_id=approval_id, include_html=True)
            check(checks, console["ok"] is True, "approval console bundle tool succeeds")
            bundle = console["data"]["console_bundle"]
            check(checks, bundle.get("schema_version") == "approval-console-bundle-v1", "console bundle schema is stable")
            check(checks, "星璇运维MCP Approval Console" in bundle.get("html", ""), "console bundle includes HTML shell")
            check(checks, "approval-console-state" in bundle.get("html", ""), "console HTML embeds page state")
            check(checks, bundle["state"]["identity_mode"]["enterprise_token_issuer_enabled"] is True, "console exposes enterprise issuer mode")
            check(checks, bundle["state"]["mcp_contract"]["issue_token_tool"] == "issue_enterprise_approval_token_tool", "console exposes token issue contract")

            missing_assertion = mcp.tools["issue_enterprise_approval_token_tool"](
                approval_id=approval_id,
                decision="grant",
                approver="approver-a",
                enterprise_assertion=None,
            )
            check(checks, missing_assertion["ok"] is False, "enterprise assertion is required")
            missing_errors = missing_assertion["data"]["enterprise_identity_verification"]["errors"]
            check(checks, "enterprise identity assertion required" in missing_errors, "missing assertion reports stable error")

            wrong_role_assertion = create_enterprise_identity_assertion(
                approval_id=approval_id,
                decision="grant",
                approver="approver-a",
                roles=["viewer"],
                issuer="verify-enterprise-idp",
                subject="idp-user-a",
            )
            wrong_role = mcp.tools["issue_enterprise_approval_token_tool"](
                approval_id=approval_id,
                decision="grant",
                approver="approver-a",
                enterprise_assertion=wrong_role_assertion,
            )
            check(checks, wrong_role["ok"] is False, "enterprise role is enforced")
            wrong_role_errors = wrong_role["data"]["enterprise_identity_verification"]["errors"]
            check(checks, "enterprise approver role missing" in wrong_role_errors, "wrong role reports stable error")

            assertion = create_enterprise_identity_assertion(
                approval_id=approval_id,
                decision="grant",
                approver="approver-a",
                roles=["ops_approver"],
                issuer="verify-enterprise-idp",
                subject="idp-user-a",
            )
            issued = mcp.tools["issue_enterprise_approval_token_tool"](
                approval_id=approval_id,
                decision="grant",
                approver="approver-a",
                enterprise_assertion=assertion,
                comment="verified enterprise approval",
            )
            check(checks, issued["ok"] is True, "enterprise assertion can issue approval token")
            token = issued["data"]["approval_token"]
            check(checks, token.get("version") == "xingxuan-mcp-approval-identity-v1", "approval token version is stable")
            check(checks, token.get("scope_hash") == approval["scope_hash"], "approval token is bound to scope hash")
            check(checks, token.get("record_event_hash") == approval["event_hash"], "approval token is bound to ledger event hash")
            check(checks, "signature" in token, "issued approval token contains signature")

            grant = mcp.tools["record_operation_approval_tool"](
                approval_id=approval_id,
                decision="grant",
                approver="approver-a",
                comment="console verified approval",
                approval_token=token,
            )
            check(checks, grant["ok"] is True, "issued token can record approval decision")
            check(checks, grant["data"]["approval"]["status"] == "granted", "approval becomes granted")
            check(checks, grant["data"]["identity_verification"]["verified"] is True, "recorded decision has verified identity")

            console_after = mcp.tools["get_approval_console_bundle_tool"](approval_id=approval_id, include_html=True)
            after_state = console_after["data"]["console_bundle"]["state"]
            check(checks, after_state["review_packet"]["status"] == "granted", "console returns latest granted status")
            check(
                checks,
                after_state["review_packet"]["identity"]["verified_identity_count"] >= 1,
                "console returns verified identity count",
            )

            event_types = {item.get("event_type") for item in audit_logger.read_recent(limit=50, trace_id="trace-approval-console")}
            check(checks, "approval_enterprise_identity_denied" in event_types, "enterprise denial is audited")
            check(checks, "approval_identity_token_issued" in event_types, "enterprise token issue is audited")
            check(checks, "approval_identity_verified" in event_types, "record identity verification is audited")

            chain = verify_approval_chain(approval_store.ledger_path())
            check(checks, chain.ok, "approval ledger hash chain remains valid")
        finally:
            for key, value in old_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
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
        "reason": "approval console verification",
    }


def _policy_text() -> str:
    return """
version: "approval-console-test"
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
rules:
  - id: CRITICAL_DENY
    match:
      risk_level: critical
    decision: deny_request
    reason: "critical risk cannot be approved"
"""


def check(checks: list[dict[str, Any]], condition: bool, name: str) -> None:
    checks.append({"name": name, "status": "PASS" if condition else "FAIL"})
    if not condition:
        raise AssertionError(name)


if __name__ == "__main__":
    main()
