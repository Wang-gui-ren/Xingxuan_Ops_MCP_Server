from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from mcp_ops_server.audit import AuditEvent, AuditLogger
from mcp_ops_server.config import (
    load_approval_identity_config,
    rotate_approval_identity_secret,
    update_approval_identity_config,
    validate_approval_identity_config_patch,
    verify_config_admin_identity_assertion,
)
from mcp_ops_server.models import ToolEnvelope
from mcp_ops_server.presentation import attach_human_report, build_human_report
from mcp_ops_server.tracing import build_trace_context
from mcp_ops_server.web import build_config_admin_console_bundle


CONFIG_AUDIT_EVENT_TYPES = {
    "approval_identity_config_viewed",
    "approval_identity_config_validated",
    "approval_identity_config_update_denied",
    "approval_identity_config_updated",
    "approval_identity_secret_rotation_denied",
    "approval_identity_secret_rotated",
}


def register_config_tools(mcp: FastMCP, audit_logger: AuditLogger | None = None) -> None:
    """Register approval identity configuration management tools."""

    audit_logger = audit_logger or AuditLogger()

    @mcp.tool()
    def get_approval_identity_config_tool(
        include_sources: bool = True,
        include_audit_events: bool = False,
        audit_limit: int = 30,
        session_id: str | None = None,
        trace_id: str | None = None,
    ) -> dict:
        """Return the redacted effective approval identity configuration."""

        trace = build_trace_context(session_id=session_id, trace_id=trace_id)
        config = load_approval_identity_config()
        audit_logger.append(
            AuditEvent(
                event_type="approval_identity_config_viewed",
                tool_name="get_approval_identity_config_tool",
                session_id=trace.session_id,
                trace_id=trace.trace_id,
                risk_level="low",
                decision="view",
                params_summary={"include_sources": include_sources, "include_audit_events": include_audit_events},
                result_summary=_config_result_summary(config.to_public_dict(include_sources=include_sources)),
            )
        )
        events = _config_audit_events(audit_logger, limit=audit_limit) if include_audit_events else []
        result = ToolEnvelope(
            ok=True,
            risk_level="low",
            summary="Approval identity configuration loaded with secrets redacted.",
            data={
                "config": config.to_public_dict(include_sources=include_sources),
                "audit_events": events,
                "trace": trace.to_dict(),
            },
            next_actions=[
                "Use validate_approval_identity_config_tool before update_approval_identity_config_tool.",
                "Expose this tool only in security-admin or trusted B/S gateway channels.",
            ],
        ).model_dump()
        return attach_human_report(
            result,
            _config_human_report(
                title="Approval Identity Config",
                conclusion=result["summary"],
                config=result["data"]["config"],
                ok=True,
                trace_id=trace.trace_id,
                session_id=trace.session_id,
                next_actions=result["next_actions"],
            ),
        )

    @mcp.tool()
    def validate_approval_identity_config_tool(
        config_patch: dict[str, Any] | None,
        include_sources: bool = True,
        session_id: str | None = None,
        trace_id: str | None = None,
    ) -> dict:
        """Validate an approval identity config patch without writing it."""

        trace = build_trace_context(session_id=session_id, trace_id=trace_id)
        validation = validate_approval_identity_config_patch(config_patch or {})
        audit_logger.append(
            AuditEvent(
                event_type="approval_identity_config_validated",
                tool_name="validate_approval_identity_config_tool",
                session_id=trace.session_id,
                trace_id=trace.trace_id,
                risk_level="low" if validation.ok else "medium",
                decision="valid" if validation.ok else "invalid",
                params_summary={"config_patch": _redact_config(config_patch or {})},
                result_summary={
                    "ok": validation.ok,
                    "errors": validation.errors,
                    "warnings": validation.warnings,
                },
            )
        )
        public_validation = validation.to_dict()
        if not include_sources and isinstance(public_validation.get("proposed_config"), dict):
            public_validation["proposed_config"].pop("source_map", None)
        result = ToolEnvelope(
            ok=validation.ok,
            risk_level="low" if validation.ok else "medium",
            summary="Approval identity config patch is valid." if validation.ok else "Approval identity config patch is invalid.",
            data={
                "validation": public_validation,
                "trace": trace.to_dict(),
            },
            next_actions=(
                ["Submit the same patch to update_approval_identity_config_tool from a security-admin channel."]
                if validation.ok
                else ["Fix validation errors before trying to update the approval identity config."]
            ),
        ).model_dump()
        return attach_human_report(
            result,
            build_human_report(
                title="Approval Identity Config Validation",
                conclusion=result["summary"],
                risk_level=result["risk_level"],
                ok=validation.ok,
                evidence=[
                    f"errors={len(validation.errors)}",
                    f"warnings={len(validation.warnings)}",
                ],
                risk_explanation="Config validation is dry-run only; it does not write files or change runtime behavior.",
                safe_next_steps=result["next_actions"],
                trace_id=trace.trace_id,
                session_id=trace.session_id,
                audit_hint="The dry-run result was written as approval_identity_config_validated.",
                details={"validation": public_validation},
            ),
        )

    @mcp.tool()
    def update_approval_identity_config_tool(
        config_patch: dict[str, Any],
        admin_approver: str,
        admin_identity_assertion: dict[str, Any] | str | None,
        change_reason: str | None = None,
        session_id: str | None = None,
        trace_id: str | None = None,
    ) -> dict:
        """Update the tmp_MCP approval identity config through an audited admin path."""

        trace = build_trace_context(session_id=session_id, trace_id=trace_id)
        config = load_approval_identity_config()
        admin_identity = verify_config_admin_identity_assertion(
            admin_identity_assertion,
            admin_approver=admin_approver,
            config=config,
        )
        if not admin_identity.ok:
            audit_logger.append(
                AuditEvent(
                    event_type="approval_identity_config_update_denied",
                    tool_name="update_approval_identity_config_tool",
                    session_id=trace.session_id,
                    trace_id=trace.trace_id,
                    risk_level="high",
                    decision="admin_identity_denied",
                    params_summary={
                        "admin_approver": admin_approver,
                        "change_reason": change_reason,
                        "config_patch": _redact_config(config_patch or {}),
                    },
                    result_summary=admin_identity.to_dict(),
                    error="; ".join(admin_identity.errors),
                )
            )
            return _admin_denied_result(
                title="Approval Identity Config Update Denied",
                admin_identity=admin_identity,
                trace=trace.to_dict(),
            )

        validation = validate_approval_identity_config_patch(config_patch or {})
        if not validation.ok:
            audit_logger.append(
                AuditEvent(
                    event_type="approval_identity_config_update_denied",
                    tool_name="update_approval_identity_config_tool",
                    session_id=trace.session_id,
                    trace_id=trace.trace_id,
                    risk_level="medium",
                    decision="config_invalid",
                    params_summary={
                        "admin_approver": admin_approver,
                        "change_reason": change_reason,
                        "config_patch": _redact_config(config_patch or {}),
                    },
                    result_summary={
                        "validation": validation.to_dict(),
                        "admin_identity": admin_identity.to_dict(),
                    },
                    error="; ".join(validation.errors),
                )
            )
            result = ToolEnvelope(
                ok=False,
                risk_level="medium",
                summary="Approval identity config update rejected by validation.",
                data={
                    "validation": validation.to_dict(),
                    "admin_identity_verification": admin_identity.to_dict(),
                    "trace": trace.to_dict(),
                },
                next_actions=["Fix validation errors and retry from a security-admin channel."],
            ).model_dump()
            return attach_human_report(
                result,
                build_human_report(
                    title="Approval Identity Config Update Invalid",
                    conclusion=result["summary"],
                    risk_level="medium",
                    ok=False,
                    evidence=[f"errors={validation.errors}"],
                    risk_explanation="Invalid config patches are not written to disk.",
                    safe_next_steps=result["next_actions"],
                    trace_id=trace.trace_id,
                    session_id=trace.session_id,
                    audit_hint="The denial was written as approval_identity_config_update_denied.",
                ),
            )

        update = update_approval_identity_config(config_patch or {})
        audit_logger.append(
            AuditEvent(
                event_type="approval_identity_config_updated",
                tool_name="update_approval_identity_config_tool",
                session_id=trace.session_id,
                trace_id=trace.trace_id,
                risk_level="medium",
                decision="updated",
                params_summary={
                    "admin_approver": admin_approver,
                    "change_reason": change_reason,
                    "config_patch": _redact_config(config_patch or {}),
                },
                result_summary={
                    "config_path": update.get("config_path"),
                    "diff": update.get("diff"),
                    "restart_required": update.get("restart_required"),
                    "admin_identity": admin_identity.to_dict(),
                },
            )
        )
        result = ToolEnvelope(
            ok=True,
            risk_level="medium",
            summary="Approval identity config updated.",
            data={
                "update": update,
                "admin_identity_verification": admin_identity.to_dict(),
                "trace": trace.to_dict(),
            },
            next_actions=[
                "Review approval_identity_config_updated in the audit log.",
                "Run verify_approval_identity.py and verify_approval_console.py after security-sensitive changes.",
            ],
        ).model_dump()
        return attach_human_report(
            result,
            build_human_report(
                title="Approval Identity Config Updated",
                conclusion=result["summary"],
                risk_level="medium",
                ok=True,
                evidence=[
                    f"config_path={update.get('config_path')}",
                    f"change_count={update.get('diff', {}).get('change_count')}",
                    f"admin={admin_approver}",
                    f"restart_required={update.get('restart_required')}",
                ],
                risk_explanation="The config write is audited and secrets are redacted from the response.",
                safe_next_steps=result["next_actions"],
                trace_id=trace.trace_id,
                session_id=trace.session_id,
                audit_hint="The update was written as approval_identity_config_updated.",
                details={"diff": update.get("diff")},
            ),
        )

    @mcp.tool()
    def rotate_approval_identity_secret_tool(
        secret_kind: str,
        admin_approver: str,
        admin_identity_assertion: dict[str, Any] | str | None,
        new_secret_value: str | None = None,
        new_secret_ref: str | None = None,
        new_key_id: str | None = None,
        change_reason: str | None = None,
        session_id: str | None = None,
        trace_id: str | None = None,
    ) -> dict:
        """Rotate approval identity secrets without returning plaintext secrets."""

        trace = build_trace_context(session_id=session_id, trace_id=trace_id)
        config = load_approval_identity_config()
        admin_identity = verify_config_admin_identity_assertion(
            admin_identity_assertion,
            admin_approver=admin_approver,
            config=config,
        )
        if not admin_identity.ok:
            audit_logger.append(
                AuditEvent(
                    event_type="approval_identity_secret_rotation_denied",
                    tool_name="rotate_approval_identity_secret_tool",
                    session_id=trace.session_id,
                    trace_id=trace.trace_id,
                    risk_level="high",
                    decision="admin_identity_denied",
                    params_summary={
                        "admin_approver": admin_approver,
                        "secret_kind": secret_kind,
                        "new_secret_ref": new_secret_ref,
                        "change_reason": change_reason,
                    },
                    result_summary=admin_identity.to_dict(),
                    error="; ".join(admin_identity.errors),
                )
            )
            return _admin_denied_result(
                title="Approval Identity Secret Rotation Denied",
                admin_identity=admin_identity,
                trace=trace.to_dict(),
            )

        try:
            rotation = rotate_approval_identity_secret(
                secret_kind=secret_kind,
                new_secret_value=new_secret_value,
                new_secret_ref=new_secret_ref,
                new_key_id=new_key_id,
            )
        except Exception as exc:
            audit_logger.append(
                AuditEvent(
                    event_type="approval_identity_secret_rotation_denied",
                    tool_name="rotate_approval_identity_secret_tool",
                    session_id=trace.session_id,
                    trace_id=trace.trace_id,
                    risk_level="high",
                    decision="rotation_invalid",
                    params_summary={
                        "admin_approver": admin_approver,
                        "secret_kind": secret_kind,
                        "new_secret_ref": new_secret_ref,
                        "change_reason": change_reason,
                    },
                    result_summary={"error": str(exc), "admin_identity": admin_identity.to_dict()},
                    error=str(exc),
                )
            )
            result = ToolEnvelope(
                ok=False,
                risk_level="high",
                summary="Approval identity secret rotation failed.",
                data={"error": str(exc), "admin_identity_verification": admin_identity.to_dict(), "trace": trace.to_dict()},
                next_actions=["Check secret_kind and provide new_secret_value or new_secret_ref."],
            ).model_dump()
            return attach_human_report(
                result,
                build_human_report(
                    title="Approval Identity Secret Rotation Failed",
                    conclusion=result["summary"],
                    risk_level="high",
                    ok=False,
                    evidence=[f"secret_kind={secret_kind}", f"error={exc}"],
                    risk_explanation="Invalid secret rotation requests are not written to disk.",
                    safe_next_steps=result["next_actions"],
                    trace_id=trace.trace_id,
                    session_id=trace.session_id,
                    audit_hint="The denial was written as approval_identity_secret_rotation_denied.",
                ),
            )

        audit_logger.append(
            AuditEvent(
                event_type="approval_identity_secret_rotated",
                tool_name="rotate_approval_identity_secret_tool",
                session_id=trace.session_id,
                trace_id=trace.trace_id,
                risk_level="high",
                decision="rotated",
                params_summary={
                    "admin_approver": admin_approver,
                    "secret_kind": secret_kind,
                    "new_secret_ref": new_secret_ref,
                    "new_key_id": new_key_id,
                    "change_reason": change_reason,
                },
                result_summary={
                    "rotation": rotation,
                    "admin_identity": admin_identity.to_dict(),
                },
            )
        )
        result = ToolEnvelope(
            ok=True,
            risk_level="high",
            summary="Approval identity secret rotated.",
            data={
                "rotation": rotation,
                "admin_identity_verification": admin_identity.to_dict(),
                "trace": trace.to_dict(),
            },
            next_actions=[
                "Verify old approval tokens are no longer accepted if the secret changed.",
                "Run approval identity and console verification scripts after rotation.",
            ],
        ).model_dump()
        return attach_human_report(
            result,
            build_human_report(
                title="Approval Identity Secret Rotated",
                conclusion=result["summary"],
                risk_level="high",
                ok=True,
                evidence=[
                    f"secret_kind={rotation.get('secret_kind')}",
                    f"old_fingerprint={rotation.get('old_secret_status', {}).get('fingerprint')}",
                    f"new_fingerprint={rotation.get('new_secret_status', {}).get('fingerprint')}",
                ],
                risk_explanation="Only secret fingerprints and status are returned; plaintext secrets are not exposed.",
                safe_next_steps=result["next_actions"],
                trace_id=trace.trace_id,
                session_id=trace.session_id,
                audit_hint="The rotation was written as approval_identity_secret_rotated.",
            ),
        )

    @mcp.tool()
    def get_config_admin_console_bundle_tool(
        include_html: bool = True,
        include_audit_events: bool = True,
        audit_limit: int = 50,
        validation_patch: dict[str, Any] | None = None,
        session_id: str | None = None,
        trace_id: str | None = None,
    ) -> dict:
        """Return a read-only B/S config admin console bundle."""

        trace = build_trace_context(session_id=session_id, trace_id=trace_id)
        config = load_approval_identity_config()
        validation = (
            validate_approval_identity_config_patch(validation_patch).to_dict()
            if validation_patch is not None
            else {}
        )
        audit_logger.append(
            AuditEvent(
                event_type="approval_identity_config_viewed",
                tool_name="get_config_admin_console_bundle_tool",
                session_id=trace.session_id,
                trace_id=trace.trace_id,
                risk_level="low",
                decision="bundle",
                params_summary={"include_html": include_html, "include_audit_events": include_audit_events},
                result_summary=_config_result_summary(config.to_public_dict(include_sources=True)),
            )
        )
        events = _config_audit_events(audit_logger, limit=audit_limit) if include_audit_events else []
        bundle = build_config_admin_console_bundle(
            config_state=config.to_public_dict(include_sources=True),
            audit_events=events,
            validation_result=validation,
            include_html=include_html,
        )
        result = ToolEnvelope(
            ok=True,
            risk_level="low",
            summary="Config admin console bundle generated.",
            data={
                "config_bundle": bundle,
                "include_html": include_html,
                "trace": trace.to_dict(),
            },
            next_actions=[
                "Render config_bundle.html only in a trusted admin browser surface.",
                "Use update_approval_identity_config_tool for audited writes.",
            ],
        ).model_dump()
        return attach_human_report(
            result,
            build_human_report(
                title="Config Admin Console Bundle",
                conclusion=result["summary"],
                risk_level="low",
                ok=True,
                evidence=[
                    f"schema={bundle.get('schema_version')}",
                    f"include_html={include_html}",
                    f"audit_events={len(events)}",
                ],
                risk_explanation="The config admin bundle is read-only page material; writes remain separate MCP tools.",
                safe_next_steps=result["next_actions"],
                trace_id=trace.trace_id,
                session_id=trace.session_id,
                audit_hint="The read was written as approval_identity_config_viewed.",
                details={"mcp_contract": bundle["state"].get("mcp_contract")},
            ),
        )


def _admin_denied_result(
    *,
    title: str,
    admin_identity: Any,
    trace: dict[str, Any],
) -> dict:
    result = ToolEnvelope(
        ok=False,
        risk_level="high",
        summary="Admin identity verification failed.",
        data={"admin_identity_verification": admin_identity.to_dict(), "trace": trace},
        next_actions=[
            "Use a trusted security-admin channel to issue admin_identity_assertion.",
            "Do not expose config write tools to ordinary user sessions.",
        ],
    ).model_dump()
    return attach_human_report(
        result,
        build_human_report(
            title=title,
            conclusion=result["summary"],
            risk_level="high",
            ok=False,
            evidence=[f"errors={admin_identity.errors}", f"verified={admin_identity.verified}"],
            risk_explanation="Config writes require a verifiable security-admin identity assertion.",
            safe_next_steps=result["next_actions"],
            trace_id=trace.get("trace_id"),
            session_id=trace.get("session_id"),
            audit_hint="The denial was written to the audit log.",
        ),
    )


def _config_human_report(
    *,
    title: str,
    conclusion: str,
    config: dict[str, Any],
    ok: bool,
    trace_id: str,
    session_id: str,
    next_actions: list[str],
) -> dict[str, Any]:
    effective = config.get("effective_config") if isinstance(config.get("effective_config"), dict) else {}
    secret_status = config.get("secret_status") if isinstance(config.get("secret_status"), dict) else {}
    return build_human_report(
        title=title,
        conclusion=conclusion,
        risk_level="low",
        ok=ok,
        evidence=[
            f"identity_required={effective.get('require_approval_identity')}",
            f"scope_required={effective.get('require_approval_identity_scope')}",
            f"enterprise_issuer_enabled={effective.get('enterprise_token_issuer_enabled')}",
            f"secret_fields={list(secret_status.keys())}",
        ],
        risk_explanation="Config query is read-only and returns redacted secret status only.",
        safe_next_steps=next_actions,
        trace_id=trace_id,
        session_id=session_id,
        audit_hint="The config view was written as approval_identity_config_viewed.",
        details={"effective_config": effective, "secret_status": secret_status},
    )


def _config_result_summary(config: dict[str, Any]) -> dict[str, Any]:
    effective = config.get("effective_config") if isinstance(config.get("effective_config"), dict) else {}
    secret_status = config.get("secret_status") if isinstance(config.get("secret_status"), dict) else {}
    return {
        "require_approval_identity": effective.get("require_approval_identity"),
        "require_approval_identity_scope": effective.get("require_approval_identity_scope"),
        "enterprise_token_issuer_enabled": effective.get("enterprise_token_issuer_enabled"),
        "secret_status": secret_status,
        "warning_count": len(config.get("warnings") or []),
    }


def _config_audit_events(audit_logger: AuditLogger, *, limit: int) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit), 200))
    events = []
    for item in audit_logger.read_recent(limit=safe_limit * 2):
        if item.get("event_type") in CONFIG_AUDIT_EVENT_TYPES:
            events.append(item)
            if len(events) >= safe_limit:
                break
    return list(reversed(events))


def _redact_config(value: Any, *, path: str = "") -> Any:
    if isinstance(value, dict):
        return {str(key): _redact_config(item, path=f"{path}.{key}" if path else str(key)) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_config(item, path=path) for item in value]
    if "secret" in path.lower() and value:
        return "***REDACTED***"
    return value
