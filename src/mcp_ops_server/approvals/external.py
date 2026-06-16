from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol
from uuid import uuid4

from mcp_ops_server.branding import version_matches
from mcp_ops_server.config import (
    approval_identity_secret,
    enterprise_identity_assertion_secret,
    load_approval_identity_config,
)


APPROVAL_IDENTITY_SECRET_ENV = "XINGXUAN_MCP_APPROVAL_IDENTITY_SECRET"
REQUIRE_APPROVAL_IDENTITY_ENV = "XINGXUAN_MCP_REQUIRE_APPROVAL_IDENTITY"
REQUIRE_APPROVAL_IDENTITY_SCOPE_ENV = "XINGXUAN_MCP_REQUIRE_APPROVAL_IDENTITY_SCOPE"
ENTERPRISE_TOKEN_ISSUER_ENABLED_ENV = "XINGXUAN_MCP_ENABLE_ENTERPRISE_APPROVAL_TOKEN_ISSUER"
ENTERPRISE_ASSERTION_SECRET_ENV = "XINGXUAN_MCP_ENTERPRISE_IDENTITY_ASSERTION_SECRET"
ENTERPRISE_APPROVER_ROLE_ENV = "XINGXUAN_MCP_ENTERPRISE_APPROVER_ROLE"
ENTERPRISE_ALLOWED_ISSUERS_ENV = "XINGXUAN_MCP_ENTERPRISE_IDENTITY_ALLOWED_ISSUERS"

TOKEN_VERSION = "xingxuan-mcp-approval-identity-v1"
LEGACY_TOKEN_VERSION = "tmp-mcp-approval-identity-v1"
ENTERPRISE_ASSERTION_VERSION = "xingxuan-mcp-enterprise-identity-assertion-v1"
LEGACY_ENTERPRISE_ASSERTION_VERSION = "tmp-mcp-enterprise-identity-assertion-v1"
SIGNATURE_ALGORITHM = "hmac-sha256"


class ExternalApprovalClient(Protocol):
    """外部审批系统预留接口。

    后续 B/S、OA、飞书、企业微信或 IAM 审批服务可以实现这个协议。
    MCP Server 不直接写外部系统，只消费外部系统返回的可验证审批凭证。
    """

    def submit_request(self, record: Any) -> dict[str, Any]:
        ...

    def fetch_decision(self, approval_id: str) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class ApprovalIdentityVerification:
    ok: bool
    enforced: bool
    verified: bool
    summary: str
    errors: list[str] = field(default_factory=list)
    claims: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "enforced": self.enforced,
            "verified": self.verified,
            "summary": self.summary,
            "errors": list(self.errors),
            "claims": dict(self.claims),
        }

    def to_history_identity(self) -> dict[str, Any] | None:
        if not self.verified:
            return None
        claims = self.claims
        return {
            "verified": True,
            "provider": claims.get("issuer"),
            "subject": claims.get("subject"),
            "token_id": claims.get("token_id"),
            "key_id": claims.get("key_id"),
            "signature_algorithm": claims.get("signature_algorithm"),
            "issued_at": claims.get("issued_at"),
            "expires_at": claims.get("expires_at"),
        }


@dataclass(frozen=True)
class EnterpriseIdentityVerification:
    ok: bool
    enabled: bool
    verified: bool
    summary: str
    errors: list[str] = field(default_factory=list)
    claims: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "enabled": self.enabled,
            "verified": self.verified,
            "summary": self.summary,
            "errors": list(self.errors),
            "claims": dict(self.claims),
        }


def approval_identity_required() -> bool:
    return load_approval_identity_config().require_approval_identity


def enterprise_approval_token_issuer_enabled() -> bool:
    return load_approval_identity_config().enterprise_token_issuer_enabled


def create_approval_decision_token(
    *,
    approval_id: str,
    decision: str,
    approver: str,
    secret: str | None = None,
    issuer: str = "xingxuan-mcp-external-approval",
    subject: str | None = None,
    key_id: str = "local-hmac",
    expires_in_minutes: int = 15,
    scope_hash: str | None = None,
    record_event_hash: str | None = None,
    nonce: str | None = None,
) -> dict[str, Any]:
    """创建外部审批决策 token。

    该函数用于测试、离线脚本或未来外部审批服务复用；不要作为普通 MCP 工具暴露。
    """

    secret_text = secret if secret is not None else approval_identity_secret()
    if not secret_text:
        raise ValueError(f"{APPROVAL_IDENTITY_SECRET_ENV} is required to sign approval identity token")
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "version": TOKEN_VERSION,
        "token_id": uuid4().hex,
        "issuer": issuer,
        "subject": subject or approver,
        "approval_id": approval_id,
        "decision": _normalize_decision(decision),
        "approver": approver,
        "issued_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=_safe_minutes(expires_in_minutes))).isoformat(),
        "key_id": key_id,
        "signature_algorithm": SIGNATURE_ALGORITHM,
        "nonce": nonce or uuid4().hex,
    }
    if scope_hash:
        payload["scope_hash"] = scope_hash
    if record_event_hash:
        payload["record_event_hash"] = record_event_hash
    payload["signature"] = _sign_payload(payload, secret_text)
    return payload


def create_enterprise_identity_assertion(
    *,
    approval_id: str,
    decision: str,
    approver: str,
    roles: list[str] | tuple[str, ...] | None = None,
    secret: str | None = None,
    issuer: str = "xingxuan-mcp-enterprise-bridge",
    subject: str | None = None,
    key_id: str = "enterprise-hmac",
    expires_in_minutes: int = 5,
    nonce: str | None = None,
) -> dict[str, Any]:
    """创建企业身份桥接断言。

    该函数供 B/S 管理端、OA/IAM 桥接层或测试脚本复用。MCP Server 只在
    `XINGXUAN_MCP_ENABLE_ENTERPRISE_APPROVAL_TOKEN_ISSUER=true` 且断言签名有效时，
    才能把它换成审批决策 token。
    """

    config = load_approval_identity_config()
    secret_text = secret if secret is not None else enterprise_identity_assertion_secret()
    if not secret_text:
        raise ValueError(f"{ENTERPRISE_ASSERTION_SECRET_ENV} is required to sign enterprise identity assertion")
    now = datetime.now(timezone.utc)
    normalized_roles = [
        str(role).strip()
        for role in (roles or [config.enterprise_required_approver_role or "ops_approver"])
        if str(role).strip()
    ]
    payload: dict[str, Any] = {
        "version": ENTERPRISE_ASSERTION_VERSION,
        "assertion_id": uuid4().hex,
        "issuer": issuer,
        "subject": subject or approver,
        "approver": approver,
        "roles": normalized_roles,
        "approval_id": approval_id,
        "decision": _normalize_decision(decision),
        "issued_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=_safe_minutes(expires_in_minutes))).isoformat(),
        "key_id": key_id,
        "signature_algorithm": SIGNATURE_ALGORITHM,
        "nonce": nonce or uuid4().hex,
    }
    payload["signature"] = _sign_payload(payload, secret_text)
    return payload


def verify_approval_decision_token(
    token: dict[str, Any] | str | None,
    *,
    approval_id: str,
    decision: str,
    approver: str,
    approval_record: dict[str, Any] | None = None,
    secret: str | None = None,
    required: bool | None = None,
) -> ApprovalIdentityVerification:
    enforced = approval_identity_required() if required is None else bool(required)
    if token is None:
        if enforced:
            return _failure(True, ["approval identity token required"], "审批身份凭证缺失。")
        return ApprovalIdentityVerification(
            ok=True,
            enforced=False,
            verified=False,
            summary="未启用审批身份强校验；继续使用本地 approver 字符串策略。",
        )

    secret_text = secret if secret is not None else approval_identity_secret()
    if not secret_text:
        return _failure(enforced, ["approval identity secret not configured"], "审批身份密钥未配置，无法校验凭证。")

    payload, parse_errors = _parse_token(token)
    if parse_errors:
        return _failure(enforced, parse_errors, "审批身份凭证格式无效。")

    errors: list[str] = []
    if not version_matches(payload.get("version"), TOKEN_VERSION, LEGACY_TOKEN_VERSION):
        errors.append("unsupported approval identity token version")
    if payload.get("signature_algorithm") != SIGNATURE_ALGORITHM:
        errors.append("unsupported approval identity signature algorithm")
    expected_signature = _sign_payload(payload, secret_text)
    actual_signature = str(payload.get("signature") or "")
    if not hmac.compare_digest(expected_signature, actual_signature):
        errors.append("approval identity signature mismatch")
    if str(payload.get("approval_id") or "") != approval_id:
        errors.append("approval_id mismatch")
    if _normalize_decision(payload.get("decision")) != _normalize_decision(decision):
        errors.append("decision mismatch")
    if str(payload.get("approver") or "") != str(approver or ""):
        errors.append("approver mismatch")
    errors.extend(_time_errors(payload))
    errors.extend(_record_binding_errors(payload, approval_record))

    if errors:
        return _failure(enforced, errors, "审批身份凭证校验失败。", claims=_safe_claims(payload))
    return ApprovalIdentityVerification(
        ok=True,
        enforced=enforced,
        verified=True,
        summary="审批身份凭证校验通过。",
        claims=_safe_claims(payload),
    )


def verify_enterprise_identity_assertion(
    assertion: dict[str, Any] | str | None,
    *,
    approval_id: str,
    decision: str,
    approver: str,
    secret: str | None = None,
    enabled: bool | None = None,
    required_role: str | None = None,
) -> EnterpriseIdentityVerification:
    issuer_enabled = enterprise_approval_token_issuer_enabled() if enabled is None else bool(enabled)
    if not issuer_enabled:
        return _enterprise_failure(False, ["enterprise approval token issuer disabled"], "企业审批 token 签发器未启用。")
    if assertion is None:
        return _enterprise_failure(True, ["enterprise identity assertion required"], "企业身份断言缺失。")

    secret_text = secret if secret is not None else enterprise_identity_assertion_secret()
    if not secret_text:
        return _enterprise_failure(True, ["enterprise identity assertion secret not configured"], "企业身份断言密钥未配置。")

    payload, parse_errors = _parse_token(assertion)
    if parse_errors:
        return _enterprise_failure(True, parse_errors, "企业身份断言格式无效。")

    errors: list[str] = []
    if not version_matches(
        payload.get("version"),
        ENTERPRISE_ASSERTION_VERSION,
        LEGACY_ENTERPRISE_ASSERTION_VERSION,
    ):
        errors.append("unsupported enterprise identity assertion version")
    if payload.get("signature_algorithm") != SIGNATURE_ALGORITHM:
        errors.append("unsupported enterprise identity signature algorithm")
    expected_signature = _sign_payload(payload, secret_text)
    actual_signature = str(payload.get("signature") or "")
    if not hmac.compare_digest(expected_signature, actual_signature):
        errors.append("enterprise identity signature mismatch")
    if str(payload.get("approval_id") or "") != approval_id:
        errors.append("approval_id mismatch")
    if _normalize_decision(payload.get("decision")) != _normalize_decision(decision):
        errors.append("decision mismatch")
    if str(payload.get("approver") or "") != str(approver or ""):
        errors.append("approver mismatch")
    errors.extend(_time_errors(payload))
    errors.extend(_enterprise_issuer_errors(payload))
    errors.extend(_enterprise_role_errors(payload, required_role=required_role))

    claims = _safe_enterprise_claims(payload)
    if errors:
        return _enterprise_failure(True, errors, "企业身份断言校验失败。", claims=claims)
    return EnterpriseIdentityVerification(
        ok=True,
        enabled=True,
        verified=True,
        summary="企业身份断言校验通过。",
        claims=claims,
    )


def _record_binding_errors(payload: dict[str, Any], approval_record: dict[str, Any] | None) -> list[str]:
    errors: list[str] = []
    require_scope = load_approval_identity_config().require_approval_identity_scope
    if approval_record is None:
        if require_scope:
            errors.append("approval record required for identity scope binding")
        return errors
    token_scope = payload.get("scope_hash")
    token_event_hash = payload.get("record_event_hash")
    if require_scope and not token_scope:
        errors.append("scope_hash required in approval identity token")
    if token_scope and token_scope != approval_record.get("scope_hash"):
        errors.append("scope_hash mismatch")
    if token_event_hash and token_event_hash != approval_record.get("event_hash"):
        errors.append("record_event_hash mismatch")
    return errors


def _parse_token(token: dict[str, Any] | str) -> tuple[dict[str, Any], list[str]]:
    if isinstance(token, dict):
        return dict(token), []
    if isinstance(token, str):
        try:
            payload = json.loads(token)
        except json.JSONDecodeError as exc:
            return {}, [f"approval identity token is not valid JSON: {exc}"]
        if not isinstance(payload, dict):
            return {}, ["approval identity token JSON must be an object"]
        return payload, []
    return {}, ["approval identity token must be a JSON object or JSON string"]


def _time_errors(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    now = datetime.now(timezone.utc)
    expires_at = _parse_iso(payload.get("expires_at"))
    issued_at = _parse_iso(payload.get("issued_at"))
    if expires_at is None:
        errors.append("missing or invalid expires_at")
    elif expires_at <= now:
        errors.append("approval identity token expired")
    if issued_at is None:
        errors.append("missing or invalid issued_at")
    elif issued_at > now + timedelta(minutes=5):
        errors.append("approval identity token issued_at is in the future")
    return errors


def _sign_payload(payload: dict[str, Any], secret: str) -> str:
    unsigned = {key: value for key, value in payload.items() if key != "signature"}
    digest = hmac.new(secret.encode("utf-8"), _stable_json(unsigned).encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{SIGNATURE_ALGORITHM}:{digest}"


def _stable_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _safe_claims(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: payload.get(key)
        for key in (
            "version",
            "token_id",
            "issuer",
            "subject",
            "approval_id",
            "decision",
            "approver",
            "issued_at",
            "expires_at",
            "key_id",
            "signature_algorithm",
            "scope_hash",
            "record_event_hash",
        )
        if payload.get(key) is not None
    }


def _safe_enterprise_claims(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: payload.get(key)
        for key in (
            "version",
            "assertion_id",
            "issuer",
            "subject",
            "approver",
            "roles",
            "approval_id",
            "decision",
            "issued_at",
            "expires_at",
            "key_id",
            "signature_algorithm",
        )
        if payload.get(key) is not None
    }


def _failure(
    enforced: bool,
    errors: list[str],
    summary: str,
    *,
    claims: dict[str, Any] | None = None,
) -> ApprovalIdentityVerification:
    return ApprovalIdentityVerification(
        ok=False,
        enforced=enforced,
        verified=False,
        summary=summary,
        errors=errors,
        claims=claims or {},
    )


def _enterprise_failure(
    enabled: bool,
    errors: list[str],
    summary: str,
    *,
    claims: dict[str, Any] | None = None,
) -> EnterpriseIdentityVerification:
    return EnterpriseIdentityVerification(
        ok=False,
        enabled=enabled,
        verified=False,
        summary=summary,
        errors=errors,
        claims=claims or {},
    )


def _enterprise_issuer_errors(payload: dict[str, Any]) -> list[str]:
    allowed = set(load_approval_identity_config().enterprise_allowed_issuers)
    if not allowed:
        return []
    issuer = str(payload.get("issuer") or "")
    if issuer not in allowed:
        return ["enterprise identity issuer not allowed"]
    return []


def _enterprise_role_errors(payload: dict[str, Any], *, required_role: str | None = None) -> list[str]:
    role = required_role if required_role is not None else load_approval_identity_config().enterprise_required_approver_role
    role = str(role or "").strip()
    if not role:
        return []
    roles = payload.get("roles") or []
    if not isinstance(roles, list):
        return ["enterprise identity roles must be a list"]
    normalized = {str(item).strip() for item in roles if str(item).strip()}
    if role not in normalized:
        return ["enterprise approver role missing"]
    return []


def _csv_set(value: str | None) -> set[str]:
    return {item.strip() for item in str(value or "").split(",") if item.strip()}


def _normalize_decision(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"grant", "granted", "approve", "approved", "allow"}:
        return "grant"
    if text in {"reject", "rejected", "deny", "denied"}:
        return "reject"
    return text


def _parse_iso(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _safe_minutes(value: int | None) -> int:
    if value is None:
        return 15
    return max(1, min(int(value), 24 * 60))


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "required", "enforce", "enforced"}
