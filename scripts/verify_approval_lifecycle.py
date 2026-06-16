from __future__ import annotations

import json
import sys
import tempfile
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mcp_ops_server.approvals import ApprovalStore  # noqa: E402


def main() -> None:
    checks: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="tmp_mcp_approval_lifecycle_") as tmp:
        root = Path(tmp)
        store = ApprovalStore(root / "approvals")
        params = _approval_params(root / "approval_lifecycle.conf")

        request = store.request_approval(
            tool_name="request_modify_file",
            operation="modify_file",
            target="local",
            params=params,
            plan={"action": "modify_file", "path": params["path"]},
            risk_level="high",
            requester="verify-script",
            reason="approval lifecycle verification",
            expires_in_minutes=30,
            trace_id="trace-lifecycle",
            session_id="session-lifecycle",
        )
        check(checks, request.status == "requested", "request creates requested approval")
        check(checks, request.schema_version == 3, "request uses schema version 3")
        check(checks, request.last_action == "request", "request records last_action")
        check(checks, request.required_approvals == 1, "request records required approvals")
        check(checks, request.granted_approvals == 0, "request starts with zero granted approvals")

        pending_validation = store.validate_approval(
            approval_id=request.approval_id,
            tool_name="request_modify_file",
            operation="modify_file",
            target="local",
            params=params,
        )
        check(checks, not pending_validation.ok, "requested approval cannot execute")
        check(checks, "approval not granted" in pending_validation.errors, "requested approval has stable error")

        granted = store.record_decision(
            approval_id=request.approval_id,
            decision="grant",
            approver="verify-admin",
            comment="grant for lifecycle verification",
        )
        check(checks, granted.status == "granted", "grant changes status")
        check(checks, granted.scope_hash == request.scope_hash, "grant keeps scope_hash")
        check(checks, granted.granted_approvals == 1, "grant records granted approval count")
        check(checks, len(granted.approver_history) == 1, "grant records approver history")

        grant_validation = store.validate_approval(
            approval_id=request.approval_id,
            tool_name="request_modify_file",
            operation="modify_file",
            target="local",
            params=dict(params, approval_id=request.approval_id),
        )
        check(checks, grant_validation.ok, "granted approval validates")

        renewed = store.renew_approval(
            approval_id=request.approval_id,
            renewed_by="verify-admin",
            expires_in_minutes=45,
            comment="extend lifecycle verification window",
        )
        check(checks, renewed.status == "granted", "renew keeps granted status")
        check(checks, renewed.renewal_count == 1, "renew increments renewal_count")
        check(checks, renewed.scope_hash == granted.scope_hash, "renew keeps scope_hash")
        check(checks, _parse_iso(renewed.expires_at) > _parse_iso(granted.expires_at), "renew extends expires_at")
        check(checks, renewed.last_action == "renew", "renew records last_action")

        revoked = store.revoke_approval(
            approval_id=request.approval_id,
            revoked_by="verify-admin",
            comment="revoke after renew verification",
        )
        check(checks, revoked.status == "revoked", "revoke changes status")
        check(checks, revoked.revoked_by == "verify-admin", "revoke records operator")
        check(checks, revoked.last_action == "revoke", "revoke records last_action")

        revoked_validation = store.validate_approval(
            approval_id=request.approval_id,
            tool_name="request_modify_file",
            operation="modify_file",
            target="local",
            params=params,
        )
        check(checks, not revoked_validation.ok, "revoked approval cannot execute")
        check(checks, "approval revoked" in revoked_validation.errors, "revoked approval has stable error")
        expect_raises(checks, "revoked approval cannot renew", lambda: store.renew_approval(
            approval_id=request.approval_id,
            renewed_by="verify-admin",
            expires_in_minutes=10,
        ))
        expect_raises(checks, "revoked approval cannot be decided again", lambda: store.record_decision(
            approval_id=request.approval_id,
            decision="grant",
            approver="verify-admin",
        ))

        rejected = store.request_approval(
            tool_name="request_modify_file",
            operation="modify_file",
            target="local",
            params=params,
            risk_level="high",
            requester="verify-script",
        )
        rejected = store.record_decision(
            approval_id=rejected.approval_id,
            decision="reject",
            approver="verify-admin",
            comment="reject path verification",
        )
        check(checks, rejected.status == "rejected", "reject changes status")
        expect_raises(checks, "rejected approval cannot renew", lambda: store.renew_approval(
            approval_id=rejected.approval_id,
            renewed_by="verify-admin",
            expires_in_minutes=10,
        ))

        expired = store.request_approval(
            tool_name="request_modify_file",
            operation="modify_file",
            target="local",
            params=params,
            risk_level="high",
            requester="verify-script",
        )
        expired_past = replace(
            expired,
            expires_at=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        store._append(expired_past)

        candidates = store.mark_expired_approvals(limit=10, dry_run=True)
        check(checks, any(item.approval_id == expired.approval_id for item in candidates), "cleanup dry-run finds expired approval")
        check(checks, store.get_latest(expired.approval_id).status == "requested", "cleanup dry-run does not mutate ledger")

        expired_validation = store.validate_approval(
            approval_id=expired.approval_id,
            tool_name="request_modify_file",
            operation="modify_file",
            target="local",
            params=params,
        )
        check(checks, not expired_validation.ok, "timestamp-expired approval cannot execute")
        check(checks, "approval expired" in expired_validation.errors, "timestamp-expired approval has stable error")

        committed = store.mark_expired_approvals(limit=10, dry_run=False)
        check(checks, any(item.approval_id == expired.approval_id for item in committed), "cleanup commit returns expired approval")
        latest_expired = store.get_latest(expired.approval_id)
        check(checks, latest_expired is not None and latest_expired.status == "expired", "cleanup commit marks expired status")
        check(checks, latest_expired is not None and latest_expired.last_action == "expire", "cleanup commit records last_action")
        expect_raises(checks, "expired approval cannot renew", lambda: store.renew_approval(
            approval_id=expired.approval_id,
            renewed_by="verify-admin",
            expires_in_minutes=10,
        ))

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
        "reason": "approval lifecycle verification",
    }


def _parse_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def check(checks: list[dict[str, Any]], condition: bool, name: str) -> None:
    checks.append({"name": name, "status": "PASS" if condition else "FAIL"})
    if not condition:
        raise AssertionError(name)


def expect_raises(checks: list[dict[str, Any]], name: str, action) -> None:
    try:
        action()
    except ValueError:
        checks.append({"name": name, "status": "PASS"})
        return
    checks.append({"name": name, "status": "FAIL"})
    raise AssertionError(name)


if __name__ == "__main__":
    main()
