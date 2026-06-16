from __future__ import annotations

import hashlib
import json
import os
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from mcp_ops_server.branding import get_prefixed_env
from mcp_ops_server.approvals.policy import ApprovalPolicyDecision, evaluate_approval_policy, validate_approver
from mcp_ops_server.audit.logger import GENESIS_HASH, compute_event_hash


ApprovalStatus = Literal["requested", "partially_granted", "granted", "rejected", "revoked", "expired"]
TERMINAL_APPROVAL_STATUSES = {"rejected", "revoked", "expired"}

_IGNORED_SCOPE_KEYS = {
    "approval_id",
    "dry_run",
    "guard_context",
    "reason",
    "session_id",
    "trace_id",
    "platform_hint",
    "target",
}


def default_approval_dir() -> Path:
    configured = get_prefixed_env("TMP_MCP_APPROVAL_DIR")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[3] / "data" / "approvals"


@dataclass(frozen=True)
class ApprovalRecord:
    approval_id: str
    status: ApprovalStatus
    tool_name: str
    operation: str
    target: str
    risk_level: str
    scope_hash: str
    created_at: str
    expires_at: str
    requester: str | None = None
    approver: str | None = None
    reason: str | None = None
    comment: str | None = None
    plan_hash: str | None = None
    trace_id: str | None = None
    session_id: str | None = None
    params_summary: dict[str, Any] = field(default_factory=dict)
    plan_summary: dict[str, Any] = field(default_factory=dict)
    schema_version: int = 3
    updated_at: str | None = None
    revoked_at: str | None = None
    revoked_by: str | None = None
    renewed_at: str | None = None
    renewed_by: str | None = None
    expired_at: str | None = None
    expired_by: str | None = None
    renewal_count: int = 0
    last_action: str | None = None
    required_approvals: int = 1
    granted_approvals: int = 0
    require_distinct_approvers: bool = True
    allow_self_approval: bool = False
    max_renewals: int = 1
    policy_ttl_minutes: int = 60
    policy_rule_ids: tuple[str, ...] = ()
    policy_reasons: tuple[str, ...] = ()
    allowed_approver_roles: tuple[str, ...] = ()
    allowed_approver_ids: tuple[str, ...] = ()
    approver_history: tuple[dict[str, Any], ...] = ()
    prev_hash: str | None = None
    event_hash: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "approval_id": self.approval_id,
            "status": self.status,
            "tool_name": self.tool_name,
            "operation": self.operation,
            "target": self.target,
            "risk_level": self.risk_level,
            "scope_hash": self.scope_hash,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "expires_at": self.expires_at,
            "requester": self.requester,
            "approver": self.approver,
            "reason": self.reason,
            "comment": self.comment,
            "plan_hash": self.plan_hash,
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "params_summary": self.params_summary,
            "plan_summary": self.plan_summary,
            "revoked_at": self.revoked_at,
            "revoked_by": self.revoked_by,
            "renewed_at": self.renewed_at,
            "renewed_by": self.renewed_by,
            "expired_at": self.expired_at,
            "expired_by": self.expired_by,
            "renewal_count": self.renewal_count,
            "last_action": self.last_action,
            "required_approvals": self.required_approvals,
            "granted_approvals": self.granted_approvals,
            "require_distinct_approvers": self.require_distinct_approvers,
            "allow_self_approval": self.allow_self_approval,
            "max_renewals": self.max_renewals,
            "policy_ttl_minutes": self.policy_ttl_minutes,
            "policy_rule_ids": list(self.policy_rule_ids),
            "policy_reasons": list(self.policy_reasons),
            "allowed_approver_roles": list(self.allowed_approver_roles),
            "allowed_approver_ids": list(self.allowed_approver_ids),
            "approver_history": list(self.approver_history),
            "prev_hash": self.prev_hash,
            "event_hash": self.event_hash,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ApprovalRecord":
        return cls(
            approval_id=str(payload["approval_id"]),
            status=_normalize_status(payload.get("status")),
            tool_name=str(payload.get("tool_name") or ""),
            operation=str(payload.get("operation") or ""),
            target=str(payload.get("target") or "local"),
            risk_level=str(payload.get("risk_level") or "high"),
            scope_hash=str(payload.get("scope_hash") or ""),
            created_at=str(payload.get("created_at") or _now_iso()),
            expires_at=str(payload.get("expires_at") or _future_iso(60)),
            requester=_optional_str(payload.get("requester")),
            approver=_optional_str(payload.get("approver")),
            reason=_optional_str(payload.get("reason")),
            comment=_optional_str(payload.get("comment")),
            plan_hash=_optional_str(payload.get("plan_hash")),
            trace_id=_optional_str(payload.get("trace_id")),
            session_id=_optional_str(payload.get("session_id")),
            params_summary=dict(payload.get("params_summary") or {}),
            plan_summary=dict(payload.get("plan_summary") or {}),
            schema_version=int(payload.get("schema_version") or 1),
            updated_at=_optional_str(payload.get("updated_at")) or _optional_str(payload.get("created_at")),
            revoked_at=_optional_str(payload.get("revoked_at")),
            revoked_by=_optional_str(payload.get("revoked_by")),
            renewed_at=_optional_str(payload.get("renewed_at")),
            renewed_by=_optional_str(payload.get("renewed_by")),
            expired_at=_optional_str(payload.get("expired_at")),
            expired_by=_optional_str(payload.get("expired_by")),
            renewal_count=int(payload.get("renewal_count") or 0),
            last_action=_optional_str(payload.get("last_action")) or _optional_str(payload.get("status")),
            required_approvals=max(1, int(payload.get("required_approvals") or 1)),
            granted_approvals=max(0, int(payload.get("granted_approvals") or (1 if payload.get("status") == "granted" else 0))),
            require_distinct_approvers=bool(payload.get("require_distinct_approvers", True)),
            allow_self_approval=bool(payload.get("allow_self_approval", False)),
            max_renewals=max(0, int(payload.get("max_renewals") if payload.get("max_renewals") is not None else 1)),
            policy_ttl_minutes=max(1, int(payload.get("policy_ttl_minutes") or 60)),
            policy_rule_ids=_tuple_str(payload.get("policy_rule_ids")),
            policy_reasons=_tuple_str(payload.get("policy_reasons")),
            allowed_approver_roles=_tuple_str(payload.get("allowed_approver_roles")),
            allowed_approver_ids=_tuple_str(payload.get("allowed_approver_ids")),
            approver_history=_tuple_dict(payload.get("approver_history")),
            prev_hash=_optional_str(payload.get("prev_hash")),
            event_hash=_optional_str(payload.get("event_hash")),
        )


@dataclass(frozen=True)
class ApprovalValidation:
    ok: bool
    approval_id: str | None
    summary: str
    record: dict[str, Any] | None = None
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "approval_id": self.approval_id,
            "summary": self.summary,
            "record": self.record,
            "errors": self.errors,
        }


class ApprovalStore:
    """本地 JSONL 审批账本。

    审批记录采用追加写。相同 approval_id 的最后一条记录代表当前状态。
    """

    def __init__(self, approval_dir: Path | None = None) -> None:
        self.approval_dir = approval_dir or default_approval_dir()

    def request_approval(
        self,
        *,
        tool_name: str,
        operation: str,
        target: str,
        params: dict[str, Any] | None = None,
        plan: dict[str, Any] | None = None,
        risk_level: str = "high",
        requester: str | None = None,
        reason: str | None = None,
        expires_in_minutes: int = 60,
        trace_id: str | None = None,
        session_id: str | None = None,
    ) -> ApprovalRecord:
        now = _now_iso()
        policy = evaluate_approval_policy(
            tool_name=tool_name,
            operation=operation,
            target=target or "local",
            risk_level=risk_level or "high",
            params=params or {},
        )
        if policy.decision == "deny_request":
            reason = "；".join(policy.reasons) if policy.reasons else "policy denied"
            raise ValueError(f"approval request denied by policy: {reason}")
        ttl = min(_safe_minutes(expires_in_minutes), policy.ttl_minutes)
        record = ApprovalRecord(
            approval_id=f"appr_{secrets.token_hex(12)}",
            status="requested",
            tool_name=tool_name,
            operation=operation,
            target=target or "local",
            risk_level=risk_level or "high",
            scope_hash=build_approval_scope_hash(tool_name, operation, target or "local", params or {}),
            created_at=now,
            expires_at=_future_iso(ttl),
            requester=requester,
            reason=reason,
            plan_hash=stable_payload_hash(plan) if plan else None,
            trace_id=trace_id,
            session_id=session_id,
            params_summary=_summarize_params(params or {}),
            plan_summary=_summarize_params(plan or {}),
            updated_at=now,
            last_action="request",
            schema_version=3,
            required_approvals=policy.required_approvals,
            granted_approvals=0,
            require_distinct_approvers=policy.require_distinct_approvers,
            allow_self_approval=policy.allow_self_approval,
            max_renewals=policy.max_renewals,
            policy_ttl_minutes=policy.ttl_minutes,
            policy_rule_ids=policy.matched_rule_ids,
            policy_reasons=policy.reasons,
            allowed_approver_roles=policy.allowed_approver_roles,
            allowed_approver_ids=policy.allowed_approver_ids,
            approver_history=(),
        )
        return self._append(record)

    def record_decision(
        self,
        *,
        approval_id: str,
        decision: str,
        approver: str,
        comment: str | None = None,
        expires_in_minutes: int | None = None,
        identity_claims: dict[str, Any] | None = None,
    ) -> ApprovalRecord:
        current = self.get_latest(approval_id)
        if current is None:
            raise ValueError(f"Approval not found: {approval_id}")
        if current.status in TERMINAL_APPROVAL_STATUSES:
            raise ValueError(f"Approval is terminal and cannot be changed: {current.status}")
        if current.status not in {"requested", "partially_granted"}:
            raise ValueError(f"Approval decision can only be recorded for requested or partially_granted approvals, got: {current.status}")
        if _is_expired(current):
            raise ValueError("Approval expired before decision was recorded.")
        normalized = _decision_to_status(decision)
        now = _now_iso()
        history = list(current.approver_history)
        policy = _policy_decision_from_record(current)
        if normalized == "granted":
            existing_approvers = {
                str(item.get("approver"))
                for item in history
                if item.get("decision") == "grant" and item.get("approver")
            }
            ok, errors = validate_approver(
                decision=policy,
                approver=approver,
                requester=current.requester,
                existing_approvers=existing_approvers,
            )
            if not ok:
                raise ValueError("; ".join(errors))
            history.append(_approval_history_item(
                approver=approver,
                decision="grant",
                recorded_at=now,
                comment=comment,
                policy_rule_ids=current.policy_rule_ids,
                identity_claims=identity_claims,
            ))
            granted_count = _count_grants(tuple(history), require_distinct=current.require_distinct_approvers)
            next_status: ApprovalStatus = "granted" if granted_count >= current.required_approvals else "partially_granted"
            last_action = "grant" if next_status == "granted" else "partial_grant"
        else:
            ok, errors = validate_approver(
                decision=policy,
                approver=approver,
                requester=current.requester,
                existing_approvers=set(),
            )
            if errors and any(error != "duplicate approver" for error in errors):
                raise ValueError("; ".join(error for error in errors if error != "duplicate approver"))
            history.append(_approval_history_item(
                approver=approver,
                decision="reject",
                recorded_at=now,
                comment=comment,
                policy_rule_ids=current.policy_rule_ids,
                identity_claims=identity_claims,
            ))
            granted_count = _count_grants(tuple(history), require_distinct=current.require_distinct_approvers)
            next_status = "rejected"
            last_action = "reject"
        ttl = min(_safe_minutes(expires_in_minutes), current.policy_ttl_minutes) if expires_in_minutes else None
        record = ApprovalRecord(
            approval_id=current.approval_id,
            status=next_status,
            tool_name=current.tool_name,
            operation=current.operation,
            target=current.target,
            risk_level=current.risk_level,
            scope_hash=current.scope_hash,
            created_at=current.created_at,
            updated_at=now,
            expires_at=_future_iso(ttl) if ttl else current.expires_at,
            requester=current.requester,
            approver=approver,
            reason=current.reason,
            comment=comment,
            plan_hash=current.plan_hash,
            trace_id=current.trace_id,
            session_id=current.session_id,
            params_summary=current.params_summary,
            plan_summary=current.plan_summary,
            schema_version=3,
            revoked_at=current.revoked_at,
            revoked_by=current.revoked_by,
            renewed_at=current.renewed_at,
            renewed_by=current.renewed_by,
            expired_at=current.expired_at,
            expired_by=current.expired_by,
            renewal_count=current.renewal_count,
            last_action=last_action,
            required_approvals=current.required_approvals,
            granted_approvals=granted_count,
            require_distinct_approvers=current.require_distinct_approvers,
            allow_self_approval=current.allow_self_approval,
            max_renewals=current.max_renewals,
            policy_ttl_minutes=current.policy_ttl_minutes,
            policy_rule_ids=current.policy_rule_ids,
            policy_reasons=current.policy_reasons,
            allowed_approver_roles=current.allowed_approver_roles,
            allowed_approver_ids=current.allowed_approver_ids,
            approver_history=tuple(history),
        )
        return self._append(record)

    def revoke_approval(
        self,
        *,
        approval_id: str,
        revoked_by: str,
        comment: str | None = None,
    ) -> ApprovalRecord:
        current = self.get_latest(approval_id)
        if current is None:
            raise ValueError(f"Approval not found: {approval_id}")
        if current.status in TERMINAL_APPROVAL_STATUSES:
            raise ValueError(f"Approval is terminal and cannot be revoked: {current.status}")
        now = _now_iso()
        record = _copy_record(
            current,
            status="revoked",
            updated_at=now,
            revoked_at=now,
            revoked_by=revoked_by,
            comment=comment,
            last_action="revoke",
        )
        return self._append(record)

    def renew_approval(
        self,
        *,
        approval_id: str,
        renewed_by: str,
        expires_in_minutes: int,
        comment: str | None = None,
    ) -> ApprovalRecord:
        current = self.get_latest(approval_id)
        if current is None:
            raise ValueError(f"Approval not found: {approval_id}")
        if current.status != "granted":
            raise ValueError(f"Only granted approvals can be renewed, got: {current.status}")
        if _is_expired(current):
            raise ValueError("Approval expired and cannot be renewed.")
        if current.renewal_count >= current.max_renewals:
            raise ValueError("max renewals exceeded")
        now = _now_iso()
        ttl = min(_safe_minutes(expires_in_minutes), current.policy_ttl_minutes)
        record = _copy_record(
            current,
            status="granted",
            updated_at=now,
            expires_at=_extend_iso(current.expires_at, ttl),
            renewed_at=now,
            renewed_by=renewed_by,
            comment=comment,
            renewal_count=current.renewal_count + 1,
            last_action="renew",
        )
        return self._append(record)

    def mark_expired_approvals(
        self,
        *,
        limit: int = 200,
        dry_run: bool = True,
    ) -> list[ApprovalRecord]:
        limit = max(1, min(int(limit), 1000))
        now = _now_iso()
        expired: list[ApprovalRecord] = []
        for record in sorted(self._latest_records().values(), key=lambda item: item.expires_at):
            if len(expired) >= limit:
                break
            if record.status not in {"requested", "partially_granted", "granted"}:
                continue
            if not _is_expired(record):
                continue
            expired_record = _copy_record(
                record,
                status="expired",
                updated_at=now,
                expired_at=now,
                expired_by="cleanup_expired_operation_approvals_tool",
                last_action="expire",
            )
            if not dry_run:
                expired_record = self._append(expired_record)
            expired.append(expired_record)
        return expired

    def validate_approval(
        self,
        *,
        approval_id: str | None,
        tool_name: str,
        operation: str,
        target: str,
        params: dict[str, Any] | None = None,
    ) -> ApprovalValidation:
        if not approval_id:
            return ApprovalValidation(False, approval_id, "真实执行缺少 approval_id。", errors=["missing approval_id"])
        record = self.get_latest(approval_id)
        if record is None:
            return ApprovalValidation(False, approval_id, "approval_id 不存在或未记录。", errors=["approval not found"])

        errors: list[str] = []
        if record.status != "granted":
            if record.status == "revoked":
                errors.append("approval revoked")
            elif record.status == "expired":
                errors.append("approval expired")
            elif record.status == "rejected":
                errors.append("approval rejected")
            elif record.status == "requested":
                errors.append("approval not granted")
            elif record.status == "partially_granted":
                errors.append("approval not fully granted")
            else:
                errors.append(f"approval status is {record.status}")
        if _parse_iso(record.expires_at) <= datetime.now(timezone.utc):
            if "approval expired" not in errors:
                errors.append("approval expired")
        if record.tool_name != tool_name:
            errors.append("tool_name mismatch")
        if record.operation != operation:
            errors.append("operation mismatch")
        if record.target != (target or "local"):
            errors.append("target mismatch")

        current_scope_hash = build_approval_scope_hash(tool_name, operation, target or "local", params or {})
        if record.scope_hash != current_scope_hash:
            errors.append("operation scope_hash mismatch")

        if errors:
            return ApprovalValidation(
                ok=False,
                approval_id=approval_id,
                summary="审批校验失败：" + "；".join(errors) + "。",
                record=record.to_dict(),
                errors=errors,
            )
        return ApprovalValidation(
            ok=True,
            approval_id=approval_id,
            summary="审批校验通过：approval_id 已授权且未过期，操作范围匹配。",
            record=record.to_dict(),
            errors=[],
        )

    def get_latest(self, approval_id: str) -> ApprovalRecord | None:
        latest: ApprovalRecord | None = None
        for record in self._read_all():
            if record.approval_id == approval_id:
                latest = record
        return latest

    def get_history(self, approval_id: str) -> list[dict[str, Any]]:
        """返回同一 approval_id 的追加账本历史，按写入顺序排列。"""

        return [record.to_dict() for record in self._read_all() if record.approval_id == approval_id]

    def list_recent(
        self,
        *,
        limit: int = 20,
        status: str | None = None,
        trace_id: str | None = None,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 200))
        normalized_status = _normalize_status(status) if status else None
        records = self._latest_records()
        rows: list[dict[str, Any]] = []
        for record in sorted(records.values(), key=lambda item: item.created_at, reverse=True):
            if normalized_status and record.status != normalized_status:
                continue
            if trace_id and record.trace_id != trace_id:
                continue
            rows.append(record.to_dict())
            if len(rows) >= limit:
                break
        return rows

    def ledger_path(self) -> Path:
        return self._path()

    def _latest_records(self) -> dict[str, ApprovalRecord]:
        rows: dict[str, ApprovalRecord] = {}
        for record in self._read_all():
            rows[record.approval_id] = record
        return rows

    def _read_all(self) -> list[ApprovalRecord]:
        path = self._path()
        if not path.exists():
            return []
        rows: list[ApprovalRecord] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rows.append(ApprovalRecord.from_dict(json.loads(line)))
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                continue
        return rows

    def _append(self, record: ApprovalRecord) -> ApprovalRecord:
        self.approval_dir.mkdir(parents=True, exist_ok=True)
        path = self._path()
        previous_hash = _read_last_approval_event_hash(path)
        payload = record.to_dict()
        payload["prev_hash"] = previous_hash
        payload["event_hash"] = compute_event_hash(payload, previous_hash=previous_hash)
        with path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
            file.write("\n")
        return ApprovalRecord.from_dict(payload)

    def _path(self) -> Path:
        return self.approval_dir / "approvals.jsonl"


def build_approval_scope_hash(tool_name: str, operation: str, target: str, params: dict[str, Any]) -> str:
    payload = {
        "tool_name": tool_name,
        "operation": operation,
        "target": target or "local",
        "params": _normalize_scope_params(params),
    }
    return stable_payload_hash(payload)


def stable_payload_hash(payload: Any) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _normalize_scope_params(params: dict[str, Any]) -> dict[str, Any]:
    return {
        str(key): value
        for key, value in sorted(params.items(), key=lambda item: str(item[0]))
        if str(key) not in _IGNORED_SCOPE_KEYS and value is not None and not callable(value)
    }


def _summarize_params(params: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "action",
        "backup",
        "dry_run",
        "manager",
        "match",
        "mode",
        "operation",
        "package",
        "path",
        "pid",
        "port",
        "process_name",
        "protocol",
        "recursive",
        "rule_name",
        "service",
        "target",
        "platform_hint",
    )
    return {key: params.get(key) for key in keys if key in params and params.get(key) is not None}


def _normalize_status(value: Any) -> ApprovalStatus:
    text = str(value or "requested").strip().lower()
    if text in {"requested", "partially_granted", "granted", "rejected", "revoked", "expired"}:
        return text  # type: ignore[return-value]
    raise ValueError(f"Invalid approval status: {value}")


def _decision_to_status(value: str) -> ApprovalStatus:
    text = (value or "").strip().lower()
    if text in {"grant", "granted", "approve", "approved", "allow"}:
        return "granted"
    if text in {"reject", "rejected", "deny", "denied"}:
        return "rejected"
    raise ValueError("decision must be grant or reject.")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _future_iso(minutes: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()


def _extend_iso(current_expires_at: str, minutes: int) -> str:
    now = datetime.now(timezone.utc)
    base = max(_parse_iso(current_expires_at), now)
    return (base + timedelta(minutes=minutes)).isoformat()


def _parse_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _is_expired(record: ApprovalRecord) -> bool:
    return _parse_iso(record.expires_at) <= datetime.now(timezone.utc)


def _copy_record(
    record: ApprovalRecord,
    *,
    status: ApprovalStatus | None = None,
    expires_at: str | None = None,
    updated_at: str | None = None,
    approver: str | None = None,
    comment: str | None = None,
    revoked_at: str | None = None,
    revoked_by: str | None = None,
    renewed_at: str | None = None,
        renewed_by: str | None = None,
        expired_at: str | None = None,
        expired_by: str | None = None,
        renewal_count: int | None = None,
        last_action: str | None = None,
) -> ApprovalRecord:
    return ApprovalRecord(
        approval_id=record.approval_id,
        status=status or record.status,
        tool_name=record.tool_name,
        operation=record.operation,
        target=record.target,
        risk_level=record.risk_level,
        scope_hash=record.scope_hash,
        created_at=record.created_at,
        expires_at=expires_at or record.expires_at,
        requester=record.requester,
        approver=approver if approver is not None else record.approver,
        reason=record.reason,
        comment=comment if comment is not None else record.comment,
        plan_hash=record.plan_hash,
        trace_id=record.trace_id,
        session_id=record.session_id,
        params_summary=record.params_summary,
        plan_summary=record.plan_summary,
        schema_version=3,
        updated_at=updated_at or record.updated_at,
        revoked_at=revoked_at if revoked_at is not None else record.revoked_at,
        revoked_by=revoked_by if revoked_by is not None else record.revoked_by,
        renewed_at=renewed_at if renewed_at is not None else record.renewed_at,
        renewed_by=renewed_by if renewed_by is not None else record.renewed_by,
        expired_at=expired_at if expired_at is not None else record.expired_at,
        expired_by=expired_by if expired_by is not None else record.expired_by,
        renewal_count=renewal_count if renewal_count is not None else record.renewal_count,
        last_action=last_action if last_action is not None else record.last_action,
        required_approvals=record.required_approvals,
        granted_approvals=record.granted_approvals,
        require_distinct_approvers=record.require_distinct_approvers,
        allow_self_approval=record.allow_self_approval,
        max_renewals=record.max_renewals,
        policy_ttl_minutes=record.policy_ttl_minutes,
        policy_rule_ids=record.policy_rule_ids,
        policy_reasons=record.policy_reasons,
        allowed_approver_roles=record.allowed_approver_roles,
        allowed_approver_ids=record.allowed_approver_ids,
        approver_history=record.approver_history,
        prev_hash=None,
        event_hash=None,
    )


def _approval_history_item(
    *,
    approver: str,
    decision: str,
    recorded_at: str,
    comment: str | None,
    policy_rule_ids: tuple[str, ...],
    identity_claims: dict[str, Any] | None = None,
) -> dict[str, Any]:
    item = {
        "approver": approver,
        "decision": decision,
        "recorded_at": recorded_at,
        "comment": comment,
        "policy_rule_ids": list(policy_rule_ids),
    }
    if identity_claims:
        item["identity"] = dict(identity_claims)
    return item


def _count_grants(history: tuple[dict[str, Any], ...], *, require_distinct: bool) -> int:
    if require_distinct:
        return len({str(item.get("approver")) for item in history if item.get("decision") == "grant" and item.get("approver")})
    return sum(1 for item in history if item.get("decision") == "grant")


def _policy_decision_from_record(record: ApprovalRecord) -> ApprovalPolicyDecision:
    return ApprovalPolicyDecision(
        decision="allow_request",
        ttl_minutes=record.policy_ttl_minutes,
        required_approvals=record.required_approvals,
        max_renewals=record.max_renewals,
        require_distinct_approvers=record.require_distinct_approvers,
        allow_self_approval=record.allow_self_approval,
        trusted_approver_ids=record.allowed_approver_ids,
        allowed_approver_roles=record.allowed_approver_roles,
        allowed_approver_ids=record.allowed_approver_ids,
        matched_rule_ids=record.policy_rule_ids,
        reasons=record.policy_reasons,
        source_path="approval-record",
        loaded_from_config=False,
    )


def _safe_minutes(value: int | None) -> int:
    if value is None:
        return 60
    return max(1, min(int(value), 7 * 24 * 60))


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _tuple_str(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (list, tuple, set)):
        return tuple(str(item) for item in value if str(item).strip())
    text = str(value).strip()
    return (text,) if text else ()


def _tuple_dict(value: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(dict(item) for item in value if isinstance(item, dict))


def _read_last_approval_event_hash(path: Path) -> str:
    if not path.exists():
        return GENESIS_HASH
    try:
        with path.open("rb") as file:
            file.seek(0, os.SEEK_END)
            position = file.tell()
            buffer = bytearray()
            while position > 0:
                position -= 1
                file.seek(position)
                char = file.read(1)
                if char == b"\n" and buffer:
                    break
                if char != b"\n":
                    buffer.extend(char)
        if not buffer:
            return GENESIS_HASH
        line = bytes(reversed(buffer)).decode("utf-8")
        event = json.loads(line)
        return str(event.get("event_hash") or GENESIS_HASH)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return GENESIS_HASH
