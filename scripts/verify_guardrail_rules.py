from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mcp_ops_server.guardrails import OperationContext, validate_intent  # noqa: E402
from mcp_ops_server.guardrails.rule_loader import clear_rule_cache, load_guardrail_rules  # noqa: E402


def main() -> None:
    clear_rule_cache()
    rule_set = load_guardrail_rules()
    rows: list[dict[str, object]] = []
    failed = 0
    total = 0

    for rule in rule_set.rules:
        for index, case in enumerate(rule.definition.test_cases, start=1):
            total += 1
            context = OperationContext(
                tool_name="shell",
                operation="execute_command",
                command=case.input if "path" not in rule.match_targets else None,
                path=case.input if "path" in rule.match_targets else None,
                params={"path": case.input} if "path" in rule.match_targets else {},
                dry_run=True,
            )
            decision = validate_intent(context)
            matched = any(finding.rule_id == rule.id for finding in decision.findings)
            ok = matched is case.expect_match
            if case.expect_match and case.expect_risk_level:
                ok = ok and decision.risk_level == case.expect_risk_level
            if case.expect_match and case.expect_decision:
                ok = ok and decision.decision == case.expect_decision
            status = "PASS" if ok else "FAIL"
            if not ok:
                failed += 1
            rows.append(
                {
                    "rule_id": rule.id,
                    "case": index,
                    "status": status,
                    "input": case.input,
                    "expect_match": case.expect_match,
                    "matched": matched,
                    "risk_level": decision.risk_level,
                    "decision": decision.decision,
                }
            )
            marker = "OK" if ok else "!!"
            print(f"[{marker}] {rule.id} case {index} matched={matched} risk={decision.risk_level} decision={decision.decision}")

    report = {
        "loaded_from_config": rule_set.loaded_from_config,
        "source_path": rule_set.source_path,
        "errors": list(rule_set.errors),
        "total": total,
        "passed": total - failed,
        "failed": failed,
        "rows": rows,
    }
    print("\n=== Guardrail Rule Verification Summary ===")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if failed or not rule_set.loaded_from_config:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
