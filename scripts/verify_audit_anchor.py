from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mcp_ops_server.audit import AuditEvent, AuditLogger, create_audit_anchor, verify_audit_anchor  # noqa: E402


def main() -> None:
    if len(sys.argv) > 1:
        result = verify_audit_anchor(Path(sys.argv[1]))
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        raise SystemExit(0 if result.ok else 1)

    with tempfile.TemporaryDirectory(prefix="tmp_mcp_audit_anchor_") as tmp:
        audit_dir = Path(tmp) / "audit"
        logger = AuditLogger(audit_dir)
        for index in range(3):
            logger.append(
                AuditEvent(
                    event_type="tool_result",
                    tool_name="verify_audit_anchor",
                    risk_level="low",
                    decision="allow",
                    params_summary={"index": index, "secret": "should-not-leak"},
                    result_summary={"summary": f"event {index}"},
                )
            )

        audit_file = next(audit_dir.glob("audit-*.jsonl"))
        anchor = create_audit_anchor(audit_file, secret="test-secret", signer="verify-script")
        print(json.dumps(anchor.to_dict(), ensure_ascii=False, indent=2))
        assert anchor.signature_algorithm == "hmac-sha256", anchor.to_dict()
        assert anchor.signature, anchor.to_dict()

        ok = verify_audit_anchor(audit_file, secret="test-secret")
        print(json.dumps(ok.to_dict(), ensure_ascii=False, indent=2))
        assert ok.ok, ok.to_dict()
        assert ok.signature_ok is True, ok.to_dict()

        logger.append(
            AuditEvent(
                event_type="tool_result",
                tool_name="verify_audit_anchor",
                risk_level="low",
                decision="allow",
                params_summary={"index": "after-anchor"},
                result_summary={"summary": "new event after anchor"},
            )
        )
        changed = verify_audit_anchor(audit_file, secret="test-secret")
        print(json.dumps(changed.to_dict(), ensure_ascii=False, indent=2))
        assert not changed.ok, changed.to_dict()
        assert "head_hash mismatch" in changed.errors, changed.to_dict()

        wrong_secret = verify_audit_anchor(audit_file, secret="wrong-secret")
        print(json.dumps(wrong_secret.to_dict(), ensure_ascii=False, indent=2))
        assert not wrong_secret.ok, wrong_secret.to_dict()
        assert "anchor signature mismatch" in wrong_secret.errors, wrong_secret.to_dict()


if __name__ == "__main__":
    main()
