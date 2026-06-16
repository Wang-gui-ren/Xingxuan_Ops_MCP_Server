from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mcp_ops_server.approvals.store import default_approval_dir
from mcp_ops_server.audit.logger import GENESIS_HASH, compute_event_hash


@dataclass(frozen=True)
class ApprovalChainVerification:
    """审批 JSONL 账本哈希链校验结果。"""

    ok: bool
    file: str
    checked_records: int
    first_bad_line: int | None = None
    expected_hash: str | None = None
    actual_hash: str | None = None
    summary: str = ""
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "file": self.file,
            "checked_records": self.checked_records,
            "first_bad_line": self.first_bad_line,
            "expected_hash": self.expected_hash,
            "actual_hash": self.actual_hash,
            "summary": self.summary,
            "errors": self.errors,
        }


def verify_approval_chain(path: Path | None = None) -> ApprovalChainVerification:
    approval_file = _resolve_approval_file(path)
    previous_hash = GENESIS_HASH
    checked = 0
    errors: list[str] = []
    try:
        lines = approval_file.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return ApprovalChainVerification(
            ok=False,
            file=str(approval_file),
            checked_records=0,
            summary="审批账本文件不存在。",
            errors=[f"file not found: {approval_file}"],
        )

    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            return ApprovalChainVerification(
                ok=False,
                file=str(approval_file),
                checked_records=checked,
                first_bad_line=line_number,
                summary=f"审批账本哈希链校验失败：第 {line_number} 行不是合法 JSON。",
                errors=[str(exc)],
            )
        checked += 1
        if "prev_hash" not in record or "event_hash" not in record:
            return ApprovalChainVerification(
                ok=False,
                file=str(approval_file),
                checked_records=checked,
                first_bad_line=line_number,
                summary=f"审批账本哈希链校验失败：第 {line_number} 行缺少链字段。",
                errors=["missing hash chain fields"],
            )

        actual_prev = str(record.get("prev_hash") or "")
        if actual_prev != previous_hash:
            return ApprovalChainVerification(
                ok=False,
                file=str(approval_file),
                checked_records=checked,
                first_bad_line=line_number,
                expected_hash=previous_hash,
                actual_hash=actual_prev,
                summary=f"审批账本哈希链校验失败：第 {line_number} 行 prev_hash 不匹配。",
                errors=errors,
            )
        expected_event_hash = compute_event_hash(record, previous_hash=previous_hash)
        actual_event_hash = str(record.get("event_hash") or "")
        if actual_event_hash != expected_event_hash:
            return ApprovalChainVerification(
                ok=False,
                file=str(approval_file),
                checked_records=checked,
                first_bad_line=line_number,
                expected_hash=expected_event_hash,
                actual_hash=actual_event_hash,
                summary=f"审批账本哈希链校验失败：第 {line_number} 行 event_hash 不匹配。",
                errors=errors,
            )
        previous_hash = actual_event_hash

    return ApprovalChainVerification(
        ok=True,
        file=str(approval_file),
        checked_records=checked,
        summary=f"审批账本哈希链校验通过：共检查 {checked} 条记录。",
        errors=errors,
    )


def _resolve_approval_file(path: Path | None) -> Path:
    if path is None:
        return default_approval_dir() / "approvals.jsonl"
    if path.suffix == ".jsonl":
        return path
    return path / "approvals.jsonl"
