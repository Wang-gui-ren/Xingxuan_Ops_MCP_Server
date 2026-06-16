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

from mcp_ops_server.approvals import ApprovalStore, create_approval_anchor, verify_approval_anchor  # noqa: E402
from mcp_ops_server.approvals.anchor import anchor_file_path, default_anchor_dir  # noqa: E402


def main() -> None:
    if len(sys.argv) > 1:
        result = verify_approval_anchor(Path(sys.argv[1]))
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        raise SystemExit(0 if result.ok else 1)

    checks: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="tmp_mcp_approval_anchor_") as tmp:
        root = Path(tmp)
        store = ApprovalStore(root / "approvals")
        params = _approval_params(root / "approval_anchor.conf")

        requested = store.request_approval(
            tool_name="request_modify_file",
            operation="modify_file",
            target="local",
            params=params,
            plan={"action": "modify_file", "path": params["path"]},
            risk_level="high",
            requester="verify-script",
            reason="approval anchor verification",
            expires_in_minutes=30,
            trace_id="trace-approval-anchor",
            session_id="session-approval-anchor",
        )
        granted = store.record_decision(
            approval_id=requested.approval_id,
            decision="grant",
            approver="verify-admin",
            comment="grant before anchor checks",
        )
        approval_file = store.ledger_path()

        anchor = create_approval_anchor(approval_file, secret="test-secret", signer="verify-script")
        anchor_path = anchor_file_path(default_anchor_dir(approval_file.parent))
        check(checks, anchor.anchor_id, "anchor id is generated")
        check(checks, anchor.checked_records == 2, "anchor covers request and grant records")
        check(checks, anchor.head_hash == granted.event_hash, "anchor head hash matches latest approval event")
        check(checks, anchor.file_sha256.startswith("sha256:"), "anchor stores approval file sha256")
        check(checks, anchor.signature_algorithm == "hmac-sha256", "anchor uses hmac-sha256 when secret is provided")
        check(checks, bool(anchor.signature), "anchor includes hmac signature")
        check(checks, anchor_path.exists(), "anchor jsonl file is written")

        ok = verify_approval_anchor(approval_file, secret="test-secret")
        check(checks, ok.ok, "valid approval anchor verifies")
        check(checks, ok.signature_ok is True, "valid approval anchor signature verifies")
        check(checks, ok.anchored_head_hash == ok.head_hash, "verified head hash matches anchor")

        missing_secret = verify_approval_anchor(approval_file, secret="")
        check(checks, not missing_secret.ok, "signed anchor requires a secret")
        check(checks, "signature secret missing" in missing_secret.errors, "missing secret is reported")

        wrong_secret = verify_approval_anchor(approval_file, secret="wrong-secret")
        check(checks, not wrong_secret.ok, "wrong hmac secret fails")
        check(checks, "anchor signature mismatch" in wrong_secret.errors, "wrong hmac secret is reported")

        store.revoke_approval(
            approval_id=requested.approval_id,
            revoked_by="verify-admin",
            comment="new record after anchor must break anchor verification",
        )
        changed = verify_approval_anchor(approval_file, secret="test-secret")
        check(checks, not changed.ok, "new approval ledger record after anchor fails verification")
        check(checks, "head_hash mismatch" in changed.errors, "changed head hash is reported")
        check(checks, "file_sha256 mismatch" in changed.errors, "changed file hash is reported")

    report = {
        "total": len(checks),
        "passed": sum(1 for item in checks if item["status"] == "PASS"),
        "failed": sum(1 for item in checks if item["status"] == "FAIL"),
        "checks": checks,
        "anchor": anchor.to_dict(),
        "valid": ok.to_dict(),
        "missing_secret": missing_secret.to_dict(),
        "wrong_secret": wrong_secret.to_dict(),
        "changed": changed.to_dict(),
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
        "reason": "approval anchor verification",
    }


def check(checks: list[dict[str, Any]], condition: Any, name: str) -> None:
    passed = bool(condition)
    checks.append({"name": name, "status": "PASS" if passed else "FAIL"})
    if not passed:
        raise AssertionError(name)


if __name__ == "__main__":
    main()
