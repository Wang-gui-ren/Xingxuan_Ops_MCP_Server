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

from mcp_ops_server.approvals import ApprovalStore, verify_approval_chain  # noqa: E402
from mcp_ops_server.audit.logger import GENESIS_HASH  # noqa: E402


def main() -> None:
    if len(sys.argv) > 1:
        result = verify_approval_chain(Path(sys.argv[1]))
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        raise SystemExit(0 if result.ok else 1)

    checks: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="tmp_mcp_approval_chain_") as tmp:
        root = Path(tmp)
        store = ApprovalStore(root / "approvals")
        params = _approval_params(root / "approval_chain.conf")

        requested = store.request_approval(
            tool_name="request_modify_file",
            operation="modify_file",
            target="local",
            params=params,
            plan={"action": "modify_file", "path": params["path"]},
            risk_level="high",
            requester="verify-script",
            reason="approval chain verification",
            expires_in_minutes=30,
            trace_id="trace-approval-chain",
            session_id="session-approval-chain",
        )
        granted = store.record_decision(
            approval_id=requested.approval_id,
            decision="grant",
            approver="verify-admin",
            comment="grant before chain checks",
        )
        renewed = store.renew_approval(
            approval_id=requested.approval_id,
            renewed_by="verify-admin",
            expires_in_minutes=10,
            comment="renew before chain checks",
        )
        revoked = store.revoke_approval(
            approval_id=requested.approval_id,
            revoked_by="verify-admin",
            comment="revoke after chain checks",
        )

        approval_file = store.ledger_path()
        lines = approval_file.read_text(encoding="utf-8").splitlines()
        records = [json.loads(line) for line in lines]
        check(checks, len(records) == 4, "ledger contains request, grant, renew, and revoke records")
        check(checks, all(record.get("prev_hash") and record.get("event_hash") for record in records), "all records have hash fields")
        check(checks, records[0]["prev_hash"] == GENESIS_HASH, "first record starts at genesis hash")
        check(
            checks,
            all(current["prev_hash"] == previous["event_hash"] for previous, current in zip(records, records[1:])),
            "records are linked by previous event hash",
        )
        check(checks, requested.event_hash == records[0]["event_hash"], "returned request record matches persisted hash")
        check(checks, granted.prev_hash == requested.event_hash, "grant links to request")
        check(checks, renewed.prev_hash == granted.event_hash, "renew links to grant")
        check(checks, revoked.prev_hash == renewed.event_hash, "revoke links to renew")

        valid_result = verify_approval_chain(approval_file)
        check(checks, valid_result.ok, "valid approval ledger verifies")
        check(checks, valid_result.checked_records == 4, "valid verifier checks all records")

        tampered_file = root / "tampered-approvals.jsonl"
        tampered_lines = list(lines)
        tampered_record = json.loads(tampered_lines[1])
        tampered_record["comment"] = "tampered comment"
        tampered_lines[1] = json.dumps(tampered_record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        tampered_file.write_text("\n".join(tampered_lines) + "\n", encoding="utf-8")
        tampered_result = verify_approval_chain(tampered_file)
        check(checks, not tampered_result.ok, "tampered payload fails verification")
        check(checks, tampered_result.first_bad_line == 2, "tamper is detected at modified line")

        deleted_file = root / "deleted-approvals.jsonl"
        deleted_file.write_text("\n".join([lines[0], *lines[2:]]) + "\n", encoding="utf-8")
        deleted_result = verify_approval_chain(deleted_file)
        check(checks, not deleted_result.ok, "deleted middle record breaks verification")
        check(checks, deleted_result.first_bad_line == 2, "deleted record is detected by next prev_hash")

        legacy_file = root / "legacy-approvals.jsonl"
        legacy_record = dict(records[0])
        legacy_record.pop("prev_hash", None)
        legacy_record.pop("event_hash", None)
        legacy_file.write_text(json.dumps(legacy_record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
        legacy_result = verify_approval_chain(legacy_file)
        check(checks, not legacy_result.ok, "legacy record without hash fields fails verification")
        check(checks, legacy_result.first_bad_line == 1, "legacy failure points at first line")

    report = {
        "total": len(checks),
        "passed": sum(1 for item in checks if item["status"] == "PASS"),
        "failed": sum(1 for item in checks if item["status"] == "FAIL"),
        "checks": checks,
        "valid": valid_result.to_dict(),
        "tampered": tampered_result.to_dict(),
        "deleted": deleted_result.to_dict(),
        "legacy": legacy_result.to_dict(),
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
        "reason": "approval chain verification",
    }


def check(checks: list[dict[str, Any]], condition: bool, name: str) -> None:
    checks.append({"name": name, "status": "PASS" if condition else "FAIL"})
    if not condition:
        raise AssertionError(name)


if __name__ == "__main__":
    main()
