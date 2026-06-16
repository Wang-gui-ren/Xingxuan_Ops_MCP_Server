from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mcp_ops_server.audit.logger import GENESIS_HASH, compute_event_hash


@dataclass(frozen=True)
class AuditChainVerification:
    """审计 JSONL 哈希链校验结果。"""

    ok: bool
    file: str
    checked_events: int
    first_bad_line: int | None = None
    expected_hash: str | None = None
    actual_hash: str | None = None
    summary: str = ""
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "file": self.file,
            "checked_events": self.checked_events,
            "first_bad_line": self.first_bad_line,
            "expected_hash": self.expected_hash,
            "actual_hash": self.actual_hash,
            "summary": self.summary,
            "errors": self.errors,
        }


def verify_audit_chain(path: Path) -> AuditChainVerification:
    previous_hash = GENESIS_HASH
    checked = 0
    errors: list[str] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return AuditChainVerification(ok=False, file=str(path), checked_events=0, summary="审计文件不存在。", errors=[f"file not found: {path}"])

    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            return AuditChainVerification(
                ok=False,
                file=str(path),
                checked_events=checked,
                first_bad_line=line_number,
                summary=f"审计哈希链校验失败：第 {line_number} 行不是合法 JSON。",
                errors=[str(exc)],
            )
        checked += 1
        actual_prev = str(event.get("prev_hash") or "")
        if actual_prev != previous_hash:
            return AuditChainVerification(
                ok=False,
                file=str(path),
                checked_events=checked,
                first_bad_line=line_number,
                expected_hash=previous_hash,
                actual_hash=actual_prev,
                summary=f"审计哈希链校验失败：第 {line_number} 行 prev_hash 不匹配。",
                errors=errors,
            )
        expected_event_hash = compute_event_hash(event, previous_hash=previous_hash)
        actual_event_hash = str(event.get("event_hash") or "")
        if actual_event_hash != expected_event_hash:
            return AuditChainVerification(
                ok=False,
                file=str(path),
                checked_events=checked,
                first_bad_line=line_number,
                expected_hash=expected_event_hash,
                actual_hash=actual_event_hash,
                summary=f"审计哈希链校验失败：第 {line_number} 行 event_hash 不匹配。",
                errors=errors,
            )
        previous_hash = actual_event_hash

    return AuditChainVerification(
        ok=True,
        file=str(path),
        checked_events=checked,
        summary=f"审计哈希链校验通过：共检查 {checked} 条事件。",
        errors=errors,
    )
