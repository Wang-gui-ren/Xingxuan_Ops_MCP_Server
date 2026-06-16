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

from mcp_ops_server.approvals import ApprovalStore, clear_policy_cache  # noqa: E402
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
    old_env = {
        "TMP_MCP_APPROVAL_POLICY_FILE": os.environ.get("TMP_MCP_APPROVAL_POLICY_FILE"),
        "TMP_MCP_REQUIRE_APPROVAL_IDENTITY": os.environ.get("TMP_MCP_REQUIRE_APPROVAL_IDENTITY"),
    }
    with tempfile.TemporaryDirectory(prefix="tmp_mcp_approval_review_") as tmp:
        root = Path(tmp)
        policy_file = root / "policies.yaml"
        policy_file.write_text(_policy_text(), encoding="utf-8")
        os.environ["TMP_MCP_APPROVAL_POLICY_FILE"] = str(policy_file)
        os.environ.pop("TMP_MCP_REQUIRE_APPROVAL_IDENTITY", None)
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
                params={"path": str(root / "review.conf"), "operation": "replace_text", "dry_run": False},
                plan={"action": "modify_file", "path": str(root / "review.conf")},
                risk_level="high",
                requester="review-requester",
                reason="approval review packet verification",
                trace_id="trace-approval-review-packet",
                session_id="session-approval-review-packet",
            )
            check(checks, request["ok"] is True, "approval request succeeds")
            approval_id = request["data"]["approval_id"]

            grant = mcp.tools["record_operation_approval_tool"](
                approval_id=approval_id,
                decision="grant",
                approver="verify-admin",
                comment="review packet grant",
            )
            check(checks, grant["ok"] is True, "approval grant succeeds")

            review = mcp.tools["get_approval_review_packet_tool"](approval_id=approval_id, audit_limit=20)
            check(checks, review["ok"] is True, "review packet tool succeeds")
            check(checks, review["data"].get("human_report") is not None, "review packet includes human report")
            check(checks, review["data"].get("approval", {}).get("status") == "granted", "review packet returns latest status")
            check(checks, review["data"].get("ledger_history_count", 0) >= 2, "review packet includes ledger history")

            ledger_statuses = {item.get("status") for item in review["data"].get("ledger_history", [])}
            check(checks, {"requested", "granted"}.issubset(ledger_statuses), "ledger history includes request and grant")

            event_types = {item.get("event_type") for item in review["data"].get("audit_events", [])}
            check(checks, {"approval_requested", "approval_granted"}.issubset(event_types), "review packet includes trace audit events")

            timeline = review["data"].get("timeline", [])
            sources = {item.get("source") for item in timeline}
            check(checks, {"approval_ledger", "audit"}.issubset(sources), "timeline combines ledger and audit sources")

            packet = review["data"].get("review_packet", {})
            check(checks, packet.get("schema_version") == "approval-review-packet-v1", "review packet schema is stable")
            check(checks, packet.get("policy", {}).get("granted_approvals") == 1, "review packet exposes policy grant count")
            check(checks, str(packet.get("lineage", {}).get("event_hash", "")).startswith("sha256:"), "review packet exposes ledger event hash")
            check(checks, packet.get("audit", {}).get("event_count", 0) >= 2, "review packet exposes audit count")
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


def _policy_text() -> str:
    return """
version: "review-packet-test"
default:
  decision: allow_request
  ttl_minutes: 60
  max_renewals: 1
  required_approvals: 1
  require_distinct_approvers: true
  allow_self_approval: false
approvers:
  trusted_ids:
    - verify-admin
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
