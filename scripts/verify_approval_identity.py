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

from mcp_ops_server.approvals import (  # noqa: E402
    ApprovalStore,
    clear_policy_cache,
    create_approval_decision_token,
    verify_approval_chain,
    verify_approval_decision_token,
)


def main() -> None:
    checks: list[dict[str, Any]] = []
    old_env = {
        "TMP_MCP_APPROVAL_POLICY_FILE": os.environ.get("TMP_MCP_APPROVAL_POLICY_FILE"),
        "TMP_MCP_APPROVAL_IDENTITY_SECRET": os.environ.get("TMP_MCP_APPROVAL_IDENTITY_SECRET"),
        "TMP_MCP_REQUIRE_APPROVAL_IDENTITY": os.environ.get("TMP_MCP_REQUIRE_APPROVAL_IDENTITY"),
        "TMP_MCP_REQUIRE_APPROVAL_IDENTITY_SCOPE": os.environ.get("TMP_MCP_REQUIRE_APPROVAL_IDENTITY_SCOPE"),
    }
    with tempfile.TemporaryDirectory(prefix="tmp_mcp_approval_identity_") as tmp:
        root = Path(tmp)
        policy_file = root / "policies.yaml"
        policy_file.write_text(_policy_text(), encoding="utf-8")
        os.environ["TMP_MCP_APPROVAL_POLICY_FILE"] = str(policy_file)
        os.environ["TMP_MCP_APPROVAL_IDENTITY_SECRET"] = "verify-approval-identity-secret"
        os.environ["TMP_MCP_REQUIRE_APPROVAL_IDENTITY"] = "true"
        os.environ["TMP_MCP_REQUIRE_APPROVAL_IDENTITY_SCOPE"] = "true"
        clear_policy_cache()
        try:
            store = ApprovalStore(root / "approvals")
            params = _approval_params(root / "identity.conf")
            requested = store.request_approval(
                tool_name="request_modify_file",
                operation="modify_file",
                target="local",
                params=params,
                plan={"action": "modify_file", "path": params["path"]},
                risk_level="high",
                requester="requester-a",
                reason="approval identity verification",
                trace_id="trace-approval-identity",
                session_id="session-approval-identity",
            )

            missing = verify_approval_decision_token(
                None,
                approval_id=requested.approval_id,
                decision="grant",
                approver="approver-a",
                approval_record=requested.to_dict(),
            )
            check(checks, not missing.ok, "required identity token is enforced")
            check(checks, "approval identity token required" in missing.errors, "missing token reports stable error")

            token = create_approval_decision_token(
                approval_id=requested.approval_id,
                decision="grant",
                approver="approver-a",
                issuer="verify-script",
                key_id="verify-key",
                scope_hash=requested.scope_hash,
                record_event_hash=requested.event_hash,
            )
            verified = verify_approval_decision_token(
                token,
                approval_id=requested.approval_id,
                decision="grant",
                approver="approver-a",
                approval_record=requested.to_dict(),
            )
            check(checks, verified.ok, "signed approval identity token verifies")
            check(checks, verified.verified, "identity verification marks token verified")
            check(checks, verified.claims.get("issuer") == "verify-script", "identity claims preserve issuer")

            wrong_approver = verify_approval_decision_token(
                token,
                approval_id=requested.approval_id,
                decision="grant",
                approver="approver-b",
                approval_record=requested.to_dict(),
            )
            check(checks, not wrong_approver.ok, "token cannot be reused by another approver")
            check(checks, "approver mismatch" in wrong_approver.errors, "wrong approver reports stable error")

            wrong_scope = create_approval_decision_token(
                approval_id=requested.approval_id,
                decision="grant",
                approver="approver-a",
                scope_hash="sha256:wrong-scope",
                record_event_hash=requested.event_hash,
            )
            wrong_scope_result = verify_approval_decision_token(
                wrong_scope,
                approval_id=requested.approval_id,
                decision="grant",
                approver="approver-a",
                approval_record=requested.to_dict(),
            )
            check(checks, not wrong_scope_result.ok, "identity token is bound to approval scope")
            check(checks, "scope_hash mismatch" in wrong_scope_result.errors, "wrong scope reports stable error")

            tampered = dict(token)
            tampered["decision"] = "reject"
            tampered_result = verify_approval_decision_token(
                tampered,
                approval_id=requested.approval_id,
                decision="reject",
                approver="approver-a",
                approval_record=requested.to_dict(),
            )
            check(checks, not tampered_result.ok, "tampered identity token is rejected")
            check(checks, "approval identity signature mismatch" in tampered_result.errors, "tamper reports signature mismatch")

            granted = store.record_decision(
                approval_id=requested.approval_id,
                decision="grant",
                approver="approver-a",
                comment="signed external approval",
                identity_claims=verified.to_history_identity(),
            )
            check(checks, granted.status == "granted", "verified identity can be recorded as approval decision")
            identity = granted.approver_history[-1].get("identity")
            check(checks, isinstance(identity, dict) and identity.get("verified") is True, "approver history stores verified identity")
            check(checks, identity.get("token_id") == verified.claims.get("token_id"), "approver history stores token id")

            chain = verify_approval_chain(store.ledger_path())
            check(checks, chain.ok, "identity-enhanced approval records keep hash chain valid")
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
        "reason": "approval identity verification",
    }


def _policy_text() -> str:
    return """
version: "identity-test"
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
    reason: "critical 风险不能通过审批放行"
"""


def check(checks: list[dict[str, Any]], condition: bool, name: str) -> None:
    checks.append({"name": name, "status": "PASS" if condition else "FAIL"})
    if not condition:
        raise AssertionError(name)


if __name__ == "__main__":
    main()
