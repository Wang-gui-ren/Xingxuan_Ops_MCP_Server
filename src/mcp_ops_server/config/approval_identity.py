from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from mcp_ops_server.branding import get_compat_env, get_compat_env_source, version_matches


APPROVAL_IDENTITY_CONFIG_FILE_ENV = "XINGXUAN_MCP_APPROVAL_IDENTITY_CONFIG_FILE"
LEGACY_APPROVAL_IDENTITY_CONFIG_FILE_ENV = "TMP_MCP_APPROVAL_IDENTITY_CONFIG_FILE"
APPROVAL_IDENTITY_LOCAL_CONFIG_FILE_ENV = "XINGXUAN_MCP_APPROVAL_IDENTITY_LOCAL_CONFIG_FILE"
LEGACY_APPROVAL_IDENTITY_LOCAL_CONFIG_FILE_ENV = "TMP_MCP_APPROVAL_IDENTITY_LOCAL_CONFIG_FILE"

APPROVAL_IDENTITY_SECRET_ENV = "XINGXUAN_MCP_APPROVAL_IDENTITY_SECRET"
LEGACY_APPROVAL_IDENTITY_SECRET_ENV = "TMP_MCP_APPROVAL_IDENTITY_SECRET"
REQUIRE_APPROVAL_IDENTITY_ENV = "XINGXUAN_MCP_REQUIRE_APPROVAL_IDENTITY"
LEGACY_REQUIRE_APPROVAL_IDENTITY_ENV = "TMP_MCP_REQUIRE_APPROVAL_IDENTITY"
REQUIRE_APPROVAL_IDENTITY_SCOPE_ENV = "XINGXUAN_MCP_REQUIRE_APPROVAL_IDENTITY_SCOPE"
LEGACY_REQUIRE_APPROVAL_IDENTITY_SCOPE_ENV = "TMP_MCP_REQUIRE_APPROVAL_IDENTITY_SCOPE"
ENTERPRISE_TOKEN_ISSUER_ENABLED_ENV = "XINGXUAN_MCP_ENABLE_ENTERPRISE_APPROVAL_TOKEN_ISSUER"
LEGACY_ENTERPRISE_TOKEN_ISSUER_ENABLED_ENV = "TMP_MCP_ENABLE_ENTERPRISE_APPROVAL_TOKEN_ISSUER"
ENTERPRISE_ASSERTION_SECRET_ENV = "XINGXUAN_MCP_ENTERPRISE_IDENTITY_ASSERTION_SECRET"
LEGACY_ENTERPRISE_ASSERTION_SECRET_ENV = "TMP_MCP_ENTERPRISE_IDENTITY_ASSERTION_SECRET"
ENTERPRISE_APPROVER_ROLE_ENV = "XINGXUAN_MCP_ENTERPRISE_APPROVER_ROLE"
LEGACY_ENTERPRISE_APPROVER_ROLE_ENV = "TMP_MCP_ENTERPRISE_APPROVER_ROLE"
ENTERPRISE_ALLOWED_ISSUERS_ENV = "XINGXUAN_MCP_ENTERPRISE_IDENTITY_ALLOWED_ISSUERS"
LEGACY_ENTERPRISE_ALLOWED_ISSUERS_ENV = "TMP_MCP_ENTERPRISE_IDENTITY_ALLOWED_ISSUERS"

CONFIG_SCHEMA_VERSION = "approval-identity-config-v1"
CONFIG_ADMIN_ASSERTION_VERSION = "xingxuan-mcp-config-admin-identity-assertion-v1"
LEGACY_CONFIG_ADMIN_ASSERTION_VERSION = "tmp-mcp-config-admin-identity-assertion-v1"
SIGNATURE_ALGORITHM = "hmac-sha256"

_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9._:-]+$")
_ALLOWED_PATCH_KEYS = {"schema_version", "identity", "enterprise", "secrets", "admin"}
_ALLOWED_SECTION_KEYS = {
    "identity": {"require_approval_identity", "require_approval_identity_scope", "approval_token_ttl_minutes"},
    "enterprise": {
        "enable_enterprise_approval_token_issuer",
        "allowed_issuers",
        "required_approver_role",
        "enterprise_assertion_ttl_minutes",
    },
    "secrets": {
        "approval_identity_secret",
        "approval_identity_secret_ref",
        "approval_identity_key_id",
        "enterprise_identity_assertion_secret",
        "enterprise_identity_assertion_secret_ref",
        "enterprise_identity_assertion_key_id",
    },
    "admin": {"require_admin_identity", "allowed_admin_roles"},
}


@dataclass(frozen=True)
class EffectiveApprovalIdentityConfig:
    schema_version: str
    require_approval_identity: bool
    require_approval_identity_scope: bool
    approval_token_ttl_minutes: int
    enterprise_token_issuer_enabled: bool
    enterprise_allowed_issuers: tuple[str, ...]
    enterprise_required_approver_role: str
    enterprise_assertion_ttl_minutes: int
    admin_require_identity: bool
    admin_allowed_roles: tuple[str, ...]
    approval_identity_secret_value: str | None = None
    approval_identity_secret_source: str | None = None
    approval_identity_secret_ref: str | None = None
    approval_identity_key_id: str | None = None
    enterprise_identity_assertion_secret_value: str | None = None
    enterprise_identity_assertion_secret_source: str | None = None
    enterprise_identity_assertion_secret_ref: str | None = None
    enterprise_identity_assertion_key_id: str | None = None
    primary_config_path: str | None = None
    local_config_path: str | None = None
    source_map: dict[str, str] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    def effective_config(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "require_approval_identity": self.require_approval_identity,
            "require_approval_identity_scope": self.require_approval_identity_scope,
            "approval_token_ttl_minutes": self.approval_token_ttl_minutes,
            "enterprise_token_issuer_enabled": self.enterprise_token_issuer_enabled,
            "enterprise_allowed_issuers": list(self.enterprise_allowed_issuers),
            "enterprise_required_approver_role": self.enterprise_required_approver_role,
            "enterprise_assertion_ttl_minutes": self.enterprise_assertion_ttl_minutes,
            "admin_require_identity": self.admin_require_identity,
            "admin_allowed_roles": list(self.admin_allowed_roles),
        }

    def secret_status(self) -> dict[str, Any]:
        return {
            "approval_identity_secret": _secret_status(
                value=self.approval_identity_secret_value,
                source=self.approval_identity_secret_source,
                secret_ref=self.approval_identity_secret_ref,
                key_id=self.approval_identity_key_id,
            ),
            "enterprise_identity_assertion_secret": _secret_status(
                value=self.enterprise_identity_assertion_secret_value,
                source=self.enterprise_identity_assertion_secret_source,
                secret_ref=self.enterprise_identity_assertion_secret_ref,
                key_id=self.enterprise_identity_assertion_key_id,
            ),
        }

    def config_paths(self) -> dict[str, Any]:
        return {
            "primary_config_path": self.primary_config_path,
            "local_config_path": self.local_config_path,
        }

    def to_public_dict(self, *, include_sources: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "effective_config": self.effective_config(),
            "secret_status": self.secret_status(),
            "config_paths": self.config_paths(),
            "warnings": list(self.warnings),
            "restart_required": False,
        }
        if include_sources:
            payload["source_map"] = dict(self.source_map)
        return payload


@dataclass(frozen=True)
class ApprovalIdentityConfigValidation:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    proposed_config: dict[str, Any] = field(default_factory=dict)
    normalized_patch: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "proposed_config": dict(self.proposed_config),
            "normalized_patch": _redact_secrets(self.normalized_patch),
        }


@dataclass(frozen=True)
class ConfigAdminIdentityVerification:
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


def default_approval_identity_config_path() -> Path:
    configured = get_compat_env(APPROVAL_IDENTITY_CONFIG_FILE_ENV, LEGACY_APPROVAL_IDENTITY_CONFIG_FILE_ENV)
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[3] / "config" / "approval_identity.json"


def default_approval_identity_local_config_path() -> Path:
    configured = get_compat_env(APPROVAL_IDENTITY_LOCAL_CONFIG_FILE_ENV, LEGACY_APPROVAL_IDENTITY_LOCAL_CONFIG_FILE_ENV)
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[3] / "config" / "approval_identity.local.json"


def load_approval_identity_config(
    *,
    config_file: str | Path | None = None,
    local_config_file: str | Path | None = None,
    primary_payload_override: dict[str, Any] | None = None,
) -> EffectiveApprovalIdentityConfig:
    primary_path = Path(config_file) if config_file is not None else default_approval_identity_config_path()
    local_path = Path(local_config_file) if local_config_file is not None else default_approval_identity_local_config_path()
    primary_payload = (
        _deep_merge(default_config_payload(), primary_payload_override)
        if primary_payload_override is not None
        else _deep_merge(default_config_payload(), _read_json_object(primary_path))
    )
    local_payload = _read_json_object(local_path)
    merged_payload = _deep_merge(primary_payload, local_payload)
    source_map = _source_map_from_payload(merged_payload, "file")
    warnings: list[str] = []

    identity = _section(merged_payload, "identity")
    enterprise = _section(merged_payload, "enterprise")
    secrets = _section(merged_payload, "secrets")
    admin = _section(merged_payload, "admin")

    require_identity = _as_bool(identity.get("require_approval_identity"), False)
    require_scope = _as_bool(identity.get("require_approval_identity_scope"), True)
    approval_token_ttl = _safe_minutes(identity.get("approval_token_ttl_minutes"), default=15)
    enterprise_enabled = _as_bool(enterprise.get("enable_enterprise_approval_token_issuer"), False)
    allowed_issuers = tuple(_normalize_string_list(enterprise.get("allowed_issuers")))
    required_role = str(enterprise.get("required_approver_role") or "ops_approver").strip()
    assertion_ttl = _safe_minutes(enterprise.get("enterprise_assertion_ttl_minutes"), default=10)
    admin_require_identity = _as_bool(admin.get("require_admin_identity"), True)
    admin_allowed_roles = tuple(_normalize_string_list(admin.get("allowed_admin_roles")) or ["mcp_security_admin"])

    approval_secret, approval_source = _secret_from_file(
        env_name=APPROVAL_IDENTITY_SECRET_ENV,
        legacy_env_name=LEGACY_APPROVAL_IDENTITY_SECRET_ENV,
        file_value=secrets.get("approval_identity_secret"),
        file_source="file",
    )
    enterprise_secret, enterprise_source = _secret_from_file(
        env_name=ENTERPRISE_ASSERTION_SECRET_ENV,
        legacy_env_name=LEGACY_ENTERPRISE_ASSERTION_SECRET_ENV,
        file_value=secrets.get("enterprise_identity_assertion_secret"),
        file_source="file",
    )

    env_value = _env_bool(REQUIRE_APPROVAL_IDENTITY_ENV, LEGACY_REQUIRE_APPROVAL_IDENTITY_ENV)
    if env_value is not None:
        require_identity = env_value
        source_map["identity.require_approval_identity"] = f"env:{get_compat_env_source(REQUIRE_APPROVAL_IDENTITY_ENV, LEGACY_REQUIRE_APPROVAL_IDENTITY_ENV) or REQUIRE_APPROVAL_IDENTITY_ENV}"
    env_value = _env_bool(REQUIRE_APPROVAL_IDENTITY_SCOPE_ENV, LEGACY_REQUIRE_APPROVAL_IDENTITY_SCOPE_ENV)
    if env_value is not None:
        require_scope = env_value
        source_map["identity.require_approval_identity_scope"] = f"env:{get_compat_env_source(REQUIRE_APPROVAL_IDENTITY_SCOPE_ENV, LEGACY_REQUIRE_APPROVAL_IDENTITY_SCOPE_ENV) or REQUIRE_APPROVAL_IDENTITY_SCOPE_ENV}"
    env_value = _env_bool(ENTERPRISE_TOKEN_ISSUER_ENABLED_ENV, LEGACY_ENTERPRISE_TOKEN_ISSUER_ENABLED_ENV)
    if env_value is not None:
        enterprise_enabled = env_value
        source_map["enterprise.enable_enterprise_approval_token_issuer"] = f"env:{get_compat_env_source(ENTERPRISE_TOKEN_ISSUER_ENABLED_ENV, LEGACY_ENTERPRISE_TOKEN_ISSUER_ENABLED_ENV) or ENTERPRISE_TOKEN_ISSUER_ENABLED_ENV}"

    env_allowed = get_compat_env(ENTERPRISE_ALLOWED_ISSUERS_ENV, LEGACY_ENTERPRISE_ALLOWED_ISSUERS_ENV)
    if env_allowed is not None:
        allowed_issuers = tuple(_csv_values(env_allowed))
        source_map["enterprise.allowed_issuers"] = f"env:{get_compat_env_source(ENTERPRISE_ALLOWED_ISSUERS_ENV, LEGACY_ENTERPRISE_ALLOWED_ISSUERS_ENV) or ENTERPRISE_ALLOWED_ISSUERS_ENV}"
    env_role = get_compat_env(ENTERPRISE_APPROVER_ROLE_ENV, LEGACY_ENTERPRISE_APPROVER_ROLE_ENV)
    if env_role is not None:
        required_role = env_role.strip()
        source_map["enterprise.required_approver_role"] = f"env:{get_compat_env_source(ENTERPRISE_APPROVER_ROLE_ENV, LEGACY_ENTERPRISE_APPROVER_ROLE_ENV) or ENTERPRISE_APPROVER_ROLE_ENV}"
    approval_secret_source = get_compat_env_source(APPROVAL_IDENTITY_SECRET_ENV, LEGACY_APPROVAL_IDENTITY_SECRET_ENV)
    if approval_secret_source:
        source_map["secrets.approval_identity_secret"] = f"env:{approval_secret_source}"
    enterprise_secret_source = get_compat_env_source(ENTERPRISE_ASSERTION_SECRET_ENV, LEGACY_ENTERPRISE_ASSERTION_SECRET_ENV)
    if enterprise_secret_source:
        source_map["secrets.enterprise_identity_assertion_secret"] = f"env:{enterprise_secret_source}"

    if not primary_path.exists():
        warnings.append(f"primary config file not found: {primary_path}")

    return EffectiveApprovalIdentityConfig(
        schema_version=str(merged_payload.get("schema_version") or CONFIG_SCHEMA_VERSION),
        require_approval_identity=require_identity,
        require_approval_identity_scope=require_scope,
        approval_token_ttl_minutes=approval_token_ttl,
        enterprise_token_issuer_enabled=enterprise_enabled,
        enterprise_allowed_issuers=allowed_issuers,
        enterprise_required_approver_role=required_role,
        enterprise_assertion_ttl_minutes=assertion_ttl,
        admin_require_identity=admin_require_identity,
        admin_allowed_roles=admin_allowed_roles,
        approval_identity_secret_value=approval_secret,
        approval_identity_secret_source=approval_source,
        approval_identity_secret_ref=_optional_str(secrets.get("approval_identity_secret_ref")),
        approval_identity_key_id=_optional_str(secrets.get("approval_identity_key_id")) or "local-hmac",
        enterprise_identity_assertion_secret_value=enterprise_secret,
        enterprise_identity_assertion_secret_source=enterprise_source,
        enterprise_identity_assertion_secret_ref=_optional_str(secrets.get("enterprise_identity_assertion_secret_ref")),
        enterprise_identity_assertion_key_id=_optional_str(secrets.get("enterprise_identity_assertion_key_id")) or "enterprise-hmac",
        primary_config_path=str(primary_path),
        local_config_path=str(local_path),
        source_map=source_map,
        warnings=tuple(warnings),
    )


def approval_identity_secret() -> str | None:
    return load_approval_identity_config().approval_identity_secret_value


def enterprise_identity_assertion_secret() -> str | None:
    return load_approval_identity_config().enterprise_identity_assertion_secret_value


def validate_approval_identity_config_patch(
    config_patch: dict[str, Any] | None,
    *,
    config_file: str | Path | None = None,
    local_config_file: str | Path | None = None,
) -> ApprovalIdentityConfigValidation:
    patch = dict(config_patch or {})
    shape_errors = _patch_shape_errors(patch)
    normalized_patch = _normalize_patch(patch)
    primary_path = Path(config_file) if config_file is not None else default_approval_identity_config_path()
    base_payload = _deep_merge(default_config_payload(), _read_json_object(primary_path))
    proposed_payload = _deep_merge(base_payload, normalized_patch)
    proposed = load_approval_identity_config(
        config_file=primary_path,
        local_config_file=local_config_file,
        primary_payload_override=proposed_payload,
    )
    errors = list(shape_errors)
    warnings = _config_warnings(proposed)
    errors.extend(_config_errors(proposed))
    return ApprovalIdentityConfigValidation(
        ok=not errors,
        errors=errors,
        warnings=warnings,
        proposed_config=proposed.to_public_dict(include_sources=True),
        normalized_patch=normalized_patch,
    )


def update_approval_identity_config(
    config_patch: dict[str, Any],
    *,
    config_file: str | Path | None = None,
    local_config_file: str | Path | None = None,
) -> dict[str, Any]:
    validation = validate_approval_identity_config_patch(
        config_patch,
        config_file=config_file,
        local_config_file=local_config_file,
    )
    if not validation.ok:
        raise ValueError("; ".join(validation.errors))
    primary_path = Path(config_file) if config_file is not None else default_approval_identity_config_path()
    before_payload = _deep_merge(default_config_payload(), _read_json_object(primary_path))
    after_payload = _deep_merge(before_payload, validation.normalized_patch)
    _write_json_atomic(primary_path, after_payload)
    after_config = load_approval_identity_config(config_file=primary_path, local_config_file=local_config_file)
    return {
        "config_path": str(primary_path),
        "diff": _diff_summary(before_payload, after_payload),
        "validation": validation.to_dict(),
        "effective_config": after_config.to_public_dict(include_sources=True),
        "restart_required": False,
    }


def build_approval_identity_config_patch(
    *,
    require_approval_identity: bool | None = None,
    require_approval_identity_scope: bool | None = None,
    enable_enterprise_approval_token_issuer: bool | None = None,
    allowed_issuers: list[str] | tuple[str, ...] | None = None,
    required_approver_role: str | None = None,
) -> dict[str, Any]:
    patch: dict[str, Any] = {}
    if require_approval_identity is not None or require_approval_identity_scope is not None:
        patch["identity"] = {}
        if require_approval_identity is not None:
            patch["identity"]["require_approval_identity"] = bool(require_approval_identity)
        if require_approval_identity_scope is not None:
            patch["identity"]["require_approval_identity_scope"] = bool(require_approval_identity_scope)
    if (
        enable_enterprise_approval_token_issuer is not None
        or allowed_issuers is not None
        or required_approver_role is not None
    ):
        patch["enterprise"] = {}
        if enable_enterprise_approval_token_issuer is not None:
            patch["enterprise"]["enable_enterprise_approval_token_issuer"] = bool(enable_enterprise_approval_token_issuer)
        if allowed_issuers is not None:
            patch["enterprise"]["allowed_issuers"] = list(allowed_issuers)
        if required_approver_role is not None:
            patch["enterprise"]["required_approver_role"] = required_approver_role
    return patch


def rotate_approval_identity_secret(
    *,
    secret_kind: str,
    new_secret_value: str | None = None,
    new_secret_ref: str | None = None,
    new_key_id: str | None = None,
    config_file: str | Path | None = None,
    local_config_file: str | Path | None = None,
) -> dict[str, Any]:
    normalized_kind = str(secret_kind or "").strip()
    if normalized_kind not in {"approval_identity_secret", "enterprise_identity_assertion_secret"}:
        raise ValueError("secret_kind must be approval_identity_secret or enterprise_identity_assertion_secret")
    if not new_secret_value and not new_secret_ref:
        raise ValueError("new_secret_value or new_secret_ref is required")
    if new_secret_value is not None and len(str(new_secret_value)) < 16:
        raise ValueError("new_secret_value must be at least 16 characters")

    secret_patch: dict[str, Any] = {}
    if normalized_kind == "approval_identity_secret":
        secret_patch["approval_identity_secret"] = new_secret_value
        secret_patch["approval_identity_secret_ref"] = new_secret_ref
        if new_key_id:
            secret_patch["approval_identity_key_id"] = new_key_id
    else:
        secret_patch["enterprise_identity_assertion_secret"] = new_secret_value
        secret_patch["enterprise_identity_assertion_secret_ref"] = new_secret_ref
        if new_key_id:
            secret_patch["enterprise_identity_assertion_key_id"] = new_key_id
    before = load_approval_identity_config(config_file=config_file, local_config_file=local_config_file)
    update = update_approval_identity_config(
        {"secrets": secret_patch},
        config_file=config_file,
        local_config_file=local_config_file,
    )
    after = load_approval_identity_config(config_file=config_file, local_config_file=local_config_file)
    return {
        "secret_kind": normalized_kind,
        "config_path": update["config_path"],
        "old_secret_status": before.secret_status().get(normalized_kind),
        "new_secret_status": after.secret_status().get(normalized_kind),
        "diff": update["diff"],
        "restart_required": False,
    }


def create_config_admin_identity_assertion(
    *,
    admin_approver: str,
    roles: list[str] | tuple[str, ...] | None = None,
    secret: str | None = None,
    issuer: str = "xingxuan-mcp-config-admin",
    subject: str | None = None,
    key_id: str = "enterprise-hmac",
    expires_in_minutes: int = 5,
    nonce: str | None = None,
) -> dict[str, Any]:
    secret_text = secret if secret is not None else enterprise_identity_assertion_secret()
    if not secret_text:
        raise ValueError(f"{ENTERPRISE_ASSERTION_SECRET_ENV} or configured enterprise assertion secret is required")
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "version": CONFIG_ADMIN_ASSERTION_VERSION,
        "assertion_id": uuid4().hex,
        "issuer": issuer,
        "subject": subject or admin_approver,
        "admin_approver": admin_approver,
        "roles": _normalize_string_list(roles or ["mcp_security_admin"]),
        "issued_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=_safe_minutes(expires_in_minutes, default=5))).isoformat(),
        "key_id": key_id,
        "signature_algorithm": SIGNATURE_ALGORITHM,
        "nonce": nonce or uuid4().hex,
    }
    payload["signature"] = _sign_payload(payload, secret_text)
    return payload


def verify_config_admin_identity_assertion(
    assertion: dict[str, Any] | str | None,
    *,
    admin_approver: str,
    config: EffectiveApprovalIdentityConfig | None = None,
) -> ConfigAdminIdentityVerification:
    cfg = config or load_approval_identity_config()
    if not cfg.admin_require_identity:
        return ConfigAdminIdentityVerification(
            ok=True,
            enforced=False,
            verified=False,
            summary="Admin identity assertion is not enforced by current config.",
        )
    if assertion is None:
        return _admin_failure(True, ["admin identity assertion required"], "Admin identity assertion is required.")
    secret_text = cfg.enterprise_identity_assertion_secret_value
    if not secret_text:
        return _admin_failure(True, ["enterprise identity assertion secret not configured"], "Admin assertion secret is not configured.")
    payload, parse_errors = _parse_assertion(assertion)
    if parse_errors:
        return _admin_failure(True, parse_errors, "Admin identity assertion format is invalid.")

    errors: list[str] = []
    if not version_matches(
        payload.get("version"),
        CONFIG_ADMIN_ASSERTION_VERSION,
        LEGACY_CONFIG_ADMIN_ASSERTION_VERSION,
    ):
        errors.append("unsupported config admin assertion version")
    if payload.get("signature_algorithm") != SIGNATURE_ALGORITHM:
        errors.append("unsupported config admin signature algorithm")
    expected_signature = _sign_payload(payload, secret_text)
    actual_signature = str(payload.get("signature") or "")
    if not hmac.compare_digest(expected_signature, actual_signature):
        errors.append("config admin assertion signature mismatch")
    if str(payload.get("admin_approver") or "") != str(admin_approver or ""):
        errors.append("admin_approver mismatch")
    issuer = str(payload.get("issuer") or "")
    if cfg.enterprise_allowed_issuers and issuer not in set(cfg.enterprise_allowed_issuers):
        errors.append("config admin issuer not allowed")
    roles = payload.get("roles") or []
    if not isinstance(roles, list):
        errors.append("config admin roles must be a list")
    else:
        role_set = {str(item).strip() for item in roles if str(item).strip()}
        if cfg.admin_allowed_roles and not role_set.intersection(set(cfg.admin_allowed_roles)):
            errors.append("config admin role missing")
    errors.extend(_time_errors(payload))

    claims = _safe_admin_claims(payload)
    if errors:
        return _admin_failure(True, errors, "Admin identity assertion verification failed.", claims=claims)
    return ConfigAdminIdentityVerification(
        ok=True,
        enforced=True,
        verified=True,
        summary="Admin identity assertion verified.",
        claims=claims,
    )


def default_config_payload() -> dict[str, Any]:
    return {
        "schema_version": CONFIG_SCHEMA_VERSION,
        "identity": {
            "require_approval_identity": False,
            "require_approval_identity_scope": True,
            "approval_token_ttl_minutes": 15,
        },
        "enterprise": {
            "enable_enterprise_approval_token_issuer": False,
            "allowed_issuers": [],
            "required_approver_role": "ops_approver",
            "enterprise_assertion_ttl_minutes": 10,
        },
        "secrets": {
            "approval_identity_secret_ref": None,
            "enterprise_identity_assertion_secret_ref": None,
        },
        "admin": {
            "require_admin_identity": True,
            "allowed_admin_roles": ["mcp_security_admin"],
        },
    }


def _config_errors(config: EffectiveApprovalIdentityConfig) -> list[str]:
    errors: list[str] = []
    if config.approval_token_ttl_minutes < 1 or config.approval_token_ttl_minutes > 1440:
        errors.append("approval_token_ttl_minutes must be between 1 and 1440")
    if config.enterprise_assertion_ttl_minutes < 1 or config.enterprise_assertion_ttl_minutes > 1440:
        errors.append("enterprise_assertion_ttl_minutes must be between 1 and 1440")
    for issuer in config.enterprise_allowed_issuers:
        if not _SAFE_NAME_RE.match(issuer):
            errors.append(f"enterprise allowed issuer has unsafe characters: {issuer}")
    if config.enterprise_required_approver_role and not _SAFE_NAME_RE.match(config.enterprise_required_approver_role):
        errors.append("enterprise required approver role has unsafe characters")
    for role in config.admin_allowed_roles:
        if not _SAFE_NAME_RE.match(role):
            errors.append(f"admin role has unsafe characters: {role}")
    if config.require_approval_identity and not config.approval_identity_secret_value:
        errors.append("approval identity secret not configured")
    if config.enterprise_token_issuer_enabled and not config.enterprise_identity_assertion_secret_value:
        errors.append("enterprise identity assertion secret not configured")
    return errors


def _config_warnings(config: EffectiveApprovalIdentityConfig) -> list[str]:
    warnings: list[str] = []
    if config.require_approval_identity and not config.require_approval_identity_scope:
        warnings.append("approval identity is enforced without scope binding")
    if config.enterprise_token_issuer_enabled and not config.enterprise_allowed_issuers:
        warnings.append("enterprise token issuer is enabled without issuer allowlist")
    if config.approval_identity_secret_ref and not config.approval_identity_secret_value:
        warnings.append("approval identity secret_ref is configured but no local HMAC secret is available")
    if config.enterprise_identity_assertion_secret_ref and not config.enterprise_identity_assertion_secret_value:
        warnings.append("enterprise assertion secret_ref is configured but no local HMAC secret is available")
    return warnings


def _patch_shape_errors(patch: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for key, value in patch.items():
        if key not in _ALLOWED_PATCH_KEYS:
            errors.append(f"unsupported top-level config key: {key}")
            continue
        if key in _ALLOWED_SECTION_KEYS:
            if value is not None and not isinstance(value, dict):
                errors.append(f"config section must be an object: {key}")
                continue
            for section_key in dict(value or {}).keys():
                if section_key not in _ALLOWED_SECTION_KEYS[key]:
                    errors.append(f"unsupported config key: {key}.{section_key}")
    return errors


def _normalize_patch(patch: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    if "schema_version" in patch:
        normalized["schema_version"] = str(patch.get("schema_version") or CONFIG_SCHEMA_VERSION)
    for section in ("identity", "enterprise", "secrets", "admin"):
        value = patch.get(section)
        if not isinstance(value, dict):
            continue
        normalized[section] = {}
        for key, item in value.items():
            if key not in _ALLOWED_SECTION_KEYS[section]:
                continue
            if key in {"allowed_issuers", "allowed_admin_roles"}:
                normalized[section][key] = _normalize_string_list(item)
            elif key in {
                "require_approval_identity",
                "require_approval_identity_scope",
                "enable_enterprise_approval_token_issuer",
                "require_admin_identity",
            }:
                normalized[section][key] = _as_bool(item, False)
            elif key in {"approval_token_ttl_minutes", "enterprise_assertion_ttl_minutes"}:
                normalized[section][key] = _safe_minutes(item, default=15)
            elif item is None:
                normalized[section][key] = None
            else:
                normalized[section][key] = str(item).strip()
    return normalized


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid approval identity config JSON: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"approval identity config must be a JSON object: {path}")
    return payload


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in dict(patch or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _section(payload: dict[str, Any], name: str) -> dict[str, Any]:
    value = payload.get(name)
    return dict(value) if isinstance(value, dict) else {}


def _as_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on", "required", "enforce", "enforced"}


def _env_bool(name: str, legacy_name: str | None = None) -> bool | None:
    if get_compat_env_source(name, legacy_name) is None:
        return None
    return _as_bool(get_compat_env(name, legacy_name), False)


def _safe_minutes(value: Any, *, default: int) -> int:
    if value is None or value == "":
        return default
    try:
        return max(1, min(int(value), 24 * 60))
    except (TypeError, ValueError):
        return default


def _normalize_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return _csv_values(value)
    if isinstance(value, (list, tuple, set, frozenset)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def _csv_values(value: str | None) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _secret_from_file(
    *,
    env_name: str,
    legacy_env_name: str | None = None,
    file_value: Any,
    file_source: str,
) -> tuple[str | None, str | None]:
    env_value = get_compat_env(env_name, legacy_env_name)
    if env_value:
        source = get_compat_env_source(env_name, legacy_env_name) or env_name
        return env_value, f"env:{source}"
    file_text = _optional_str(file_value)
    if file_text:
        return file_text, file_source
    return None, None


def _secret_status(
    *,
    value: str | None,
    source: str | None,
    secret_ref: str | None,
    key_id: str | None,
) -> dict[str, Any]:
    return {
        "configured": bool(value or secret_ref),
        "usable_for_hmac": bool(value),
        "source": source or ("secret_ref" if secret_ref else None),
        "secret_ref": secret_ref,
        "key_id": key_id,
        "fingerprint": _fingerprint(value) if value else None,
    }


def _fingerprint(value: str | None) -> str | None:
    if not value:
        return None
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return f"sha256:{digest[:12]}"


def _source_map_from_payload(payload: dict[str, Any], source: str) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for section in ("identity", "enterprise", "secrets", "admin"):
        value = payload.get(section)
        if isinstance(value, dict):
            for key in value.keys():
                mapping[f"{section}.{key}"] = source
    if "schema_version" in payload:
        mapping["schema_version"] = source
    return mapping


def _diff_summary(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    before_flat = _flatten(before)
    after_flat = _flatten(after)
    keys = sorted(set(before_flat) | set(after_flat))
    changes = []
    for key in keys:
        before_value = before_flat.get(key)
        after_value = after_flat.get(key)
        if before_value != after_value:
            changes.append(
                {
                    "path": key,
                    "before": _redact_if_secret(key, before_value),
                    "after": _redact_if_secret(key, after_value),
                }
            )
    return {"change_count": len(changes), "changes": changes}


def _flatten(payload: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in payload.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            result.update(_flatten(value, path))
        else:
            result[path] = value
    return result


def _redact_if_secret(key: str, value: Any) -> Any:
    if "secret" in key.lower() and value:
        return "***REDACTED***"
    return value


def _redact_secrets(value: Any, *, path: str = "") -> Any:
    if isinstance(value, dict):
        return {str(key): _redact_secrets(item, path=f"{path}.{key}" if path else str(key)) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_secrets(item, path=path) for item in value]
    if "secret" in path.lower() and value:
        return "***REDACTED***"
    return value


def _parse_assertion(assertion: dict[str, Any] | str) -> tuple[dict[str, Any], list[str]]:
    if isinstance(assertion, dict):
        return dict(assertion), []
    if isinstance(assertion, str):
        try:
            payload = json.loads(assertion)
        except json.JSONDecodeError as exc:
            return {}, [f"config admin assertion is not valid JSON: {exc}"]
        if not isinstance(payload, dict):
            return {}, ["config admin assertion JSON must be an object"]
        return payload, []
    return {}, ["config admin assertion must be a JSON object or JSON string"]


def _time_errors(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    now = datetime.now(timezone.utc)
    expires_at = _parse_iso(payload.get("expires_at"))
    issued_at = _parse_iso(payload.get("issued_at"))
    if expires_at is None:
        errors.append("missing or invalid expires_at")
    elif expires_at <= now:
        errors.append("config admin assertion expired")
    if issued_at is None:
        errors.append("missing or invalid issued_at")
    elif issued_at > now + timedelta(minutes=5):
        errors.append("config admin assertion issued_at is in the future")
    return errors


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


def _sign_payload(payload: dict[str, Any], secret: str) -> str:
    unsigned = {key: value for key, value in payload.items() if key != "signature"}
    digest = hmac.new(secret.encode("utf-8"), _stable_json(unsigned).encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{SIGNATURE_ALGORITHM}:{digest}"


def _stable_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _safe_admin_claims(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: payload.get(key)
        for key in (
            "version",
            "assertion_id",
            "issuer",
            "subject",
            "admin_approver",
            "roles",
            "issued_at",
            "expires_at",
            "key_id",
            "signature_algorithm",
        )
        if payload.get(key) is not None
    }


def _admin_failure(
    enforced: bool,
    errors: list[str],
    summary: str,
    *,
    claims: dict[str, Any] | None = None,
) -> ConfigAdminIdentityVerification:
    return ConfigAdminIdentityVerification(
        ok=False,
        enforced=enforced,
        verified=False,
        summary=summary,
        errors=errors,
        claims=claims or {},
    )
