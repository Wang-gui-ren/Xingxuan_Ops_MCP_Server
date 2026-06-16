from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from mcp_ops_server.branding import get_prefixed_env

APPROVAL_POLICY_FILE_ENV = "TMP_MCP_APPROVAL_POLICY_FILE"


@dataclass(frozen=True)
class ApprovalPolicyRule:
    id: str
    match: dict[str, Any] = field(default_factory=dict)
    decision: Literal["allow_request", "deny_request"] = "allow_request"
    reason: str | None = None
    ttl_minutes: int | None = None
    required_approvals: int | None = None
    max_renewals: int | None = None
    require_distinct_approvers: bool | None = None
    allow_self_approval: bool | None = None
    approver_roles: tuple[str, ...] = ()
    approver_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ApprovalPolicySet:
    version: str
    default_decision: Literal["allow_request", "deny_request"]
    default_ttl_minutes: int
    default_required_approvals: int
    default_max_renewals: int
    default_require_distinct_approvers: bool
    default_allow_self_approval: bool
    trusted_approver_ids: tuple[str, ...]
    approver_roles: dict[str, tuple[str, ...]]
    rules: tuple[ApprovalPolicyRule, ...]
    source_path: str
    loaded_from_config: bool
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class ApprovalPolicyDecision:
    decision: Literal["allow_request", "deny_request"]
    ttl_minutes: int
    required_approvals: int
    max_renewals: int
    require_distinct_approvers: bool
    allow_self_approval: bool
    trusted_approver_ids: tuple[str, ...]
    allowed_approver_roles: tuple[str, ...]
    allowed_approver_ids: tuple[str, ...]
    matched_rule_ids: tuple[str, ...]
    reasons: tuple[str, ...]
    source_path: str
    loaded_from_config: bool
    errors: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "ttl_minutes": self.ttl_minutes,
            "required_approvals": self.required_approvals,
            "max_renewals": self.max_renewals,
            "require_distinct_approvers": self.require_distinct_approvers,
            "allow_self_approval": self.allow_self_approval,
            "trusted_approver_ids": list(self.trusted_approver_ids),
            "allowed_approver_roles": list(self.allowed_approver_roles),
            "allowed_approver_ids": list(self.allowed_approver_ids),
            "matched_rule_ids": list(self.matched_rule_ids),
            "reasons": list(self.reasons),
            "source_path": self.source_path,
            "loaded_from_config": self.loaded_from_config,
            "errors": list(self.errors),
        }


def default_policy_path() -> Path:
    return Path(__file__).resolve().parents[3] / "config" / "approvals" / "policies.yaml"


def clear_policy_cache() -> None:
    load_approval_policy.cache_clear()


@lru_cache(maxsize=4)
def load_approval_policy(path_text: str | None = None) -> ApprovalPolicySet:
    path = Path(path_text or get_prefixed_env(APPROVAL_POLICY_FILE_ENV) or default_policy_path())
    if path.exists():
        try:
            payload = _load_mapping(path)
            return _parse_policy_set(payload, source_path=str(path), loaded_from_config=True)
        except Exception as exc:  # noqa: BLE001 - bad local policy must not crash the MCP server
            fallback = _fallback_policy(str(path), errors=(f"failed to load approval policy from {path}: {exc}",))
            return fallback
    return _fallback_policy(str(path), errors=(f"approval policy file not found: {path}",))


def evaluate_approval_policy(
    *,
    tool_name: str,
    operation: str,
    target: str,
    risk_level: str,
    params: dict[str, Any] | None = None,
    policy_set: ApprovalPolicySet | None = None,
) -> ApprovalPolicyDecision:
    policy = policy_set or load_approval_policy()
    ttl_minutes = policy.default_ttl_minutes
    required_approvals = policy.default_required_approvals
    max_renewals = policy.default_max_renewals
    require_distinct = policy.default_require_distinct_approvers
    allow_self = policy.default_allow_self_approval
    decision: Literal["allow_request", "deny_request"] = policy.default_decision
    matched_rule_ids: list[str] = []
    reasons: list[str] = []
    role_names: list[str] = []
    explicit_ids: list[str] = []

    context = {
        "tool_name": tool_name,
        "operation": operation,
        "target": target or "local",
        "risk_level": risk_level or "high",
        "params": params or {},
    }
    for rule in policy.rules:
        if not _rule_matches(rule, context):
            continue
        matched_rule_ids.append(rule.id)
        if rule.reason:
            reasons.append(rule.reason)
        if rule.decision == "deny_request":
            decision = "deny_request"
        if rule.ttl_minutes is not None:
            ttl_minutes = min(ttl_minutes, _safe_positive_int(rule.ttl_minutes, ttl_minutes))
        if rule.required_approvals is not None:
            required_approvals = max(required_approvals, _safe_positive_int(rule.required_approvals, required_approvals))
        if rule.max_renewals is not None:
            max_renewals = min(max_renewals, max(0, int(rule.max_renewals)))
        if rule.require_distinct_approvers is not None:
            require_distinct = bool(rule.require_distinct_approvers)
        if rule.allow_self_approval is not None:
            allow_self = bool(rule.allow_self_approval)
        role_names.extend(rule.approver_roles)
        explicit_ids.extend(rule.approver_ids)

    if str(risk_level or "").strip().lower() == "critical":
        decision = "deny_request"
        if "CRITICAL_DENY" not in matched_rule_ids:
            matched_rule_ids.append("CRITICAL_DENY")
        if not any("critical" in reason.lower() for reason in reasons):
            reasons.append("critical 风险不能通过审批放行")

    role_names = _dedupe(role_names)
    explicit_ids = _dedupe(explicit_ids)
    allowed_ids = list(explicit_ids)
    for role_name in role_names:
        allowed_ids.extend(policy.approver_roles.get(role_name, ()))
    if not allowed_ids and policy.trusted_approver_ids:
        allowed_ids.extend(policy.trusted_approver_ids)

    return ApprovalPolicyDecision(
        decision=decision,
        ttl_minutes=_safe_positive_int(ttl_minutes, 60),
        required_approvals=_safe_positive_int(required_approvals, 1),
        max_renewals=max(0, int(max_renewals)),
        require_distinct_approvers=require_distinct,
        allow_self_approval=allow_self,
        trusted_approver_ids=policy.trusted_approver_ids,
        allowed_approver_roles=tuple(role_names),
        allowed_approver_ids=tuple(_dedupe(allowed_ids)),
        matched_rule_ids=tuple(_dedupe(matched_rule_ids)),
        reasons=tuple(_dedupe(reasons)),
        source_path=policy.source_path,
        loaded_from_config=policy.loaded_from_config,
        errors=policy.errors,
    )


def validate_approver(
    *,
    decision: ApprovalPolicyDecision,
    approver: str,
    requester: str | None,
    existing_approvers: set[str],
) -> tuple[bool, list[str]]:
    errors: list[str] = []
    approver_text = str(approver or "").strip()
    if not approver_text:
        errors.append("missing approver")
    if approver_text and decision.allowed_approver_ids and approver_text not in decision.allowed_approver_ids:
        errors.append("approver not allowed")
    requester_text = str(requester or "").strip()
    if approver_text and requester_text and not decision.allow_self_approval and approver_text == requester_text:
        errors.append("self approval denied")
    if decision.require_distinct_approvers and approver_text in existing_approvers:
        errors.append("duplicate approver")
    return (not errors, errors)


def _load_mapping(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore[import-not-found]

        payload = yaml.safe_load(text)
    except ModuleNotFoundError:
        payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("approval policy root must be a mapping")
    return payload


def _parse_policy_set(payload: dict[str, Any], *, source_path: str, loaded_from_config: bool) -> ApprovalPolicySet:
    default = payload.get("default") or {}
    if not isinstance(default, dict):
        raise ValueError("approval policy default must be a mapping")
    approvers = payload.get("approvers") or {}
    if not isinstance(approvers, dict):
        raise ValueError("approval policy approvers must be a mapping")
    roles_payload = approvers.get("roles") or {}
    if not isinstance(roles_payload, dict):
        raise ValueError("approval policy approver roles must be a mapping")
    rules_payload = payload.get("rules") or []
    if not isinstance(rules_payload, list):
        raise ValueError("approval policy rules must be a list")

    return ApprovalPolicySet(
        version=str(payload.get("version") or "fallback"),
        default_decision=_normalize_decision(default.get("decision"), default_value="allow_request"),
        default_ttl_minutes=_safe_positive_int(default.get("ttl_minutes"), 60),
        default_required_approvals=_safe_positive_int(default.get("required_approvals"), 1),
        default_max_renewals=max(0, int(default.get("max_renewals") if default.get("max_renewals") is not None else 1)),
        default_require_distinct_approvers=bool(default.get("require_distinct_approvers", True)),
        default_allow_self_approval=bool(default.get("allow_self_approval", False)),
        trusted_approver_ids=tuple(_string_list(approvers.get("trusted_ids"))),
        approver_roles={str(key): tuple(_string_list(value)) for key, value in roles_payload.items()},
        rules=tuple(_parse_rule(item) for item in rules_payload if isinstance(item, dict)),
        source_path=source_path,
        loaded_from_config=loaded_from_config,
    )


def _parse_rule(payload: dict[str, Any]) -> ApprovalPolicyRule:
    match = payload.get("match") or {}
    if not isinstance(match, dict):
        raise ValueError("approval policy rule match must be a mapping")
    return ApprovalPolicyRule(
        id=str(payload.get("id") or "unnamed_rule"),
        match=match,
        decision=_normalize_decision(payload.get("decision"), default_value="allow_request"),
        reason=str(payload.get("reason")) if payload.get("reason") else None,
        ttl_minutes=_optional_int(payload.get("ttl_minutes")),
        required_approvals=_optional_int(payload.get("required_approvals")),
        max_renewals=_optional_int(payload.get("max_renewals")),
        require_distinct_approvers=_optional_bool(payload.get("require_distinct_approvers")),
        allow_self_approval=_optional_bool(payload.get("allow_self_approval")),
        approver_roles=tuple(_string_list(payload.get("approver_roles"))),
        approver_ids=tuple(_string_list(payload.get("approver_ids"))),
    )


def _fallback_policy(source_path: str, *, errors: tuple[str, ...] = ()) -> ApprovalPolicySet:
    return ApprovalPolicySet(
        version="fallback",
        default_decision="allow_request",
        default_ttl_minutes=60,
        default_required_approvals=1,
        default_max_renewals=1,
        default_require_distinct_approvers=True,
        default_allow_self_approval=False,
        trusted_approver_ids=(),
        approver_roles={},
        rules=(
            ApprovalPolicyRule(
                id="CRITICAL_DENY",
                match={"risk_level": "critical"},
                decision="deny_request",
                reason="critical 风险不能通过审批放行",
            ),
        ),
        source_path=source_path,
        loaded_from_config=False,
        errors=errors,
    )


def _rule_matches(rule: ApprovalPolicyRule, context: dict[str, Any]) -> bool:
    match = rule.match
    for key in ("risk_level", "tool_name", "operation", "target"):
        if key not in match:
            continue
        values = _string_list(match.get(key))
        if values and str(context.get(key) or "") not in values:
            return False
    if "path_prefix" in match:
        prefixes = [_normalize_path_prefix(item) for item in _string_list(match.get("path_prefix"))]
        paths = _candidate_paths(context)
        if prefixes and not any(_path_has_prefix(path, prefix) for path in paths for prefix in prefixes):
            return False
    return True


def _candidate_paths(context: dict[str, Any]) -> list[str]:
    params = context.get("params") or {}
    candidates = [context.get("target")]
    if isinstance(params, dict):
        for key in ("path", "log_path", "target_path"):
            candidates.append(params.get(key))
    return [str(item) for item in candidates if item]


def _normalize_path_prefix(value: str) -> str:
    text = str(value)
    if text == "%TEMP%":
        text = tempfile.gettempdir()
    text = os.path.expanduser(os.path.expandvars(text))
    return text.replace("\\", "/").rstrip("/").lower()


def _path_has_prefix(path: str, prefix: str) -> bool:
    normalized = os.path.expanduser(os.path.expandvars(str(path))).replace("\\", "/").rstrip("/").lower()
    return normalized == prefix or normalized.startswith(prefix + "/")


def _normalize_decision(value: Any, *, default_value: Literal["allow_request", "deny_request"]) -> Literal["allow_request", "deny_request"]:
    text = str(value or default_value).strip().lower()
    if text in {"allow", "allow_request", "require_approval"}:
        return "allow_request"
    if text in {"deny", "deny_request", "block"}:
        return "deny_request"
    return default_value


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _safe_positive_int(value: Any, default_value: int) -> int:
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return default_value


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result
