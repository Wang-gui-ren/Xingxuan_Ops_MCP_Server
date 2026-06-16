from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mcp_ops_server.audit import AuditEvent, AuditLogger, verify_audit_chain  # noqa: E402


def main() -> None:
    if len(sys.argv) > 1:
        result = verify_audit_chain(Path(sys.argv[1]))
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        raise SystemExit(0 if result.ok else 1)

    with tempfile.TemporaryDirectory(prefix="tmp_mcp_audit_chain_") as tmp:
        logger = AuditLogger(Path(tmp))
        for index in range(3):
            logger.append(
                AuditEvent(
                    event_type="guardrail_decision",
                    tool_name="verify_audit_chain",
                    risk_level="low",
                    decision="allow",
                    params_summary={"index": index, "token": "should-not-leak"},
                    result_summary={"summary": f"event {index}"},
                )
            )
        audit_file = next(Path(tmp).glob("audit-*.jsonl"))
        result = verify_audit_chain(audit_file)
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        assert result.ok, result.to_dict()

        lines = audit_file.read_text(encoding="utf-8").splitlines()
        event = json.loads(lines[1])
        event["result_summary"]["summary"] = "tampered"
        lines[1] = json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        tampered_file = Path(tmp) / "audit-tampered.jsonl"
        tampered_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        tampered = verify_audit_chain(tampered_file)
        print(json.dumps(tampered.to_dict(), ensure_ascii=False, indent=2))
        assert not tampered.ok, tampered.to_dict()


if __name__ == "__main__":
    main()
