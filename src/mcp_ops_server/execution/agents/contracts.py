from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mcp_ops_server.approvals import build_approval_scope_hash


@dataclass(frozen=True)
class RemoteConnectionContract:
    transport: str
    target: str
    port: int
    username: str | None = None
    auth_ref: str | None = None
    auth_mode: str | None = None
    endpoint: str | None = None
    requires_known_host: bool | None = None
    strict_host_key_checking: bool | None = None
    https_recommended: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "transport": self.transport,
            "target": self.target,
            "port": self.port,
        }
        if self.username is not None:
            payload["username"] = self.username
        if self.auth_ref is not None:
            payload["auth_ref"] = self.auth_ref
        if self.auth_mode is not None:
            payload["auth_mode"] = self.auth_mode
        if self.endpoint is not None:
            payload["endpoint"] = self.endpoint
        if self.requires_known_host is not None:
            payload["requires_known_host"] = self.requires_known_host
        if self.strict_host_key_checking is not None:
            payload["strict_host_key_checking"] = self.strict_host_key_checking
        if self.https_recommended is not None:
            payload["https_recommended"] = self.https_recommended
        return payload


@dataclass(frozen=True)
class RemoteApprovalBindingContract:
    required_for_real_execution: bool
    approval_id_present: bool
    scope_hash_present: bool
    scope_hash_should_bind: tuple[str, ...]
    approval_id: str | None = None
    scope_hash: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "required_for_real_execution": self.required_for_real_execution,
            "approval_id_present": self.approval_id_present,
            "approval_id": self.approval_id,
            "scope_hash_present": self.scope_hash_present,
            "scope_hash": self.scope_hash,
            "scope_hash_should_bind": list(self.scope_hash_should_bind),
        }
        return payload


@dataclass(frozen=True)
class RemoteTraceBindingContract:
    trace_id_present: bool
    session_id_present: bool
    required_for_remote_audit: bool
    trace_id: str | None = None
    session_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "trace_id_present": self.trace_id_present,
            "trace_id": self.trace_id,
            "session_id_present": self.session_id_present,
            "session_id": self.session_id,
            "required_for_remote_audit": self.required_for_remote_audit,
        }
        return payload


@dataclass(frozen=True)
class RemoteExecutionStageContract:
    adapter_kind: str
    fixed_template_only: bool
    target: str
    platform: str
    real_execution_enabled: bool
    expected_execute_stage: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "adapter_kind": self.adapter_kind,
            "fixed_template_only": self.fixed_template_only,
            "target": self.target,
            "platform": self.platform,
            "real_execution_enabled": self.real_execution_enabled,
            "expected_execute_stage": self.expected_execute_stage,
        }


@dataclass(frozen=True)
class RemoteExecutionReferenceBundle:
    transport: str
    target: str
    platform: str
    profile_id: str | None
    deployment_state: str | None
    remote_runtime_account: str | None
    reference_request: dict[str, Any]
    reference_preflight: dict[str, Any]
    connection: RemoteConnectionContract
    auth_requirements: tuple[str, ...]
    approval_binding: RemoteApprovalBindingContract
    trace_binding: RemoteTraceBindingContract
    execution_contract: RemoteExecutionStageContract
    post_check_plan: tuple[str, ...]
    rollback_plan: tuple[str, ...]
    requirements: tuple[str, ...]
    next_stage: str
    mode: str = "reference_only"
    can_execute_now: bool = False
    structured_request_only: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "transport": self.transport,
            "target": self.target,
            "platform": self.platform,
            "profile_id": self.profile_id,
            "deployment_state": self.deployment_state,
            "can_execute_now": self.can_execute_now,
            "structured_request_only": self.structured_request_only,
            "remote_runtime_account": self.remote_runtime_account,
            "reference_request": self.reference_request,
            "reference_preflight": self.reference_preflight,
            "connection": self.connection.to_dict(),
            "auth_requirements": list(self.auth_requirements),
            "approval_binding": self.approval_binding.to_dict(),
            "trace_binding": self.trace_binding.to_dict(),
            "execution_contract": self.execution_contract.to_dict(),
            "post_check_plan": list(self.post_check_plan),
            "rollback_plan": list(self.rollback_plan),
            "requirements": list(self.requirements),
            "next_stage": self.next_stage,
        }


@dataclass(frozen=True)
class RemoteAdapterHandoffRequest:
    transport: str
    target: str
    platform: str
    action: str
    template_id: str
    profile_id: str | None
    deployment_state: str | None
    approval_id: str | None
    scope_hash: str | None
    trace_id: str | None
    session_id: str | None
    connection: dict[str, Any]
    identity_source: str | None
    endpoint_profile: str | None
    host_verification_policy: str | None
    execution_contract: dict[str, Any]
    health_probe_contract: dict[str, Any]
    post_check_contract: list[dict[str, Any]]
    rollback_contract: list[dict[str, Any]]
    auth_requirements: tuple[str, ...]
    requirements: tuple[str, ...]
    next_stage: str
    readiness: dict[str, Any]
    schema_version: str = "remote-adapter-handoff-v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "transport": self.transport,
            "target": self.target,
            "platform": self.platform,
            "action": self.action,
            "template_id": self.template_id,
            "profile_id": self.profile_id,
            "deployment_state": self.deployment_state,
            "approval_id": self.approval_id,
            "scope_hash": self.scope_hash,
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "connection": self.connection,
            "identity_source": self.identity_source,
            "endpoint_profile": self.endpoint_profile,
            "host_verification_policy": self.host_verification_policy,
            "execution_contract": self.execution_contract,
            "health_probe_contract": self.health_probe_contract,
            "post_check_contract": self.post_check_contract,
            "rollback_contract": self.rollback_contract,
            "auth_requirements": list(self.auth_requirements),
            "requirements": list(self.requirements),
            "next_stage": self.next_stage,
            "readiness": self.readiness,
        }


@dataclass(frozen=True)
class RemoteAdapterExecuteRequestPreview:
    transport: str
    target: str
    platform: str
    action: str
    template_id: str
    profile_id: str | None
    deployment_state: str | None
    approval_id: str | None
    scope_hash: str | None
    trace_id: str | None
    session_id: str | None
    connection: dict[str, Any]
    identity_source: str | None
    endpoint_profile: str | None
    host_verification_policy: str | None
    parameter_contract: dict[str, Any]
    parameter_materialization: dict[str, Any]
    execution_contract: dict[str, Any]
    health_probe_contract: dict[str, Any]
    post_check_contract: list[dict[str, Any]]
    rollback_contract: list[dict[str, Any]]
    auth_requirements: tuple[str, ...]
    requirements: tuple[str, ...]
    next_stage: str
    readiness: dict[str, Any]
    source_handoff_schema_version: str | None = None
    schema_version: str = "remote-adapter-execute-request-preview-v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "transport": self.transport,
            "target": self.target,
            "platform": self.platform,
            "action": self.action,
            "template_id": self.template_id,
            "profile_id": self.profile_id,
            "deployment_state": self.deployment_state,
            "approval_id": self.approval_id,
            "scope_hash": self.scope_hash,
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "connection": self.connection,
            "identity_source": self.identity_source,
            "endpoint_profile": self.endpoint_profile,
            "host_verification_policy": self.host_verification_policy,
            "parameter_contract": self.parameter_contract,
            "parameter_materialization": self.parameter_materialization,
            "execution_contract": self.execution_contract,
            "health_probe_contract": self.health_probe_contract,
            "post_check_contract": self.post_check_contract,
            "rollback_contract": self.rollback_contract,
            "auth_requirements": list(self.auth_requirements),
            "requirements": list(self.requirements),
            "next_stage": self.next_stage,
            "readiness": self.readiness,
            "source_handoff_schema_version": self.source_handoff_schema_version,
        }


@dataclass(frozen=True)
class RemoteAdapterExecuteSchema:
    transport: str
    target: str
    platform: str
    action: str
    template_id: str
    profile_id: str | None
    approval_id: str | None
    scope_hash: str | None
    trace_id: str | None
    session_id: str | None
    connection: dict[str, Any]
    identity_source: str | None
    endpoint_profile: str | None
    host_verification_policy: str | None
    execution_contract: dict[str, Any]
    parameter_values_source: str
    parameter_values_scope: list[str]
    materialization_required: bool
    fixed_template_only: bool
    schema_version: str = "remote-adapter-execute-schema-v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "transport": self.transport,
            "target": self.target,
            "platform": self.platform,
            "action": self.action,
            "template_id": self.template_id,
            "profile_id": self.profile_id,
            "approval_id": self.approval_id,
            "scope_hash": self.scope_hash,
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "connection": self.connection,
            "identity_source": self.identity_source,
            "endpoint_profile": self.endpoint_profile,
            "host_verification_policy": self.host_verification_policy,
            "execution_contract": self.execution_contract,
            "parameter_values_source": self.parameter_values_source,
            "parameter_values_scope": self.parameter_values_scope,
            "materialization_required": self.materialization_required,
            "fixed_template_only": self.fixed_template_only,
        }


@dataclass(frozen=True)
class RemoteAdapterConsumeRequest:
    transport: str
    target: str
    platform: str
    action: str
    template_id: str
    profile_id: str | None
    approval_id: str | None
    scope_hash: str | None
    trace_id: str | None
    session_id: str | None
    connection: dict[str, Any]
    identity_source: str | None
    endpoint_profile: str | None
    host_verification_policy: str | None
    execution_contract: dict[str, Any]
    materialized_params: dict[str, Any]
    parameter_values_source: str
    parameter_values_scope: list[str]
    parameter_values_hash: str | None
    materialization_required: bool
    fixed_template_only: bool
    schema_version: str = "remote-adapter-consume-request-v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "transport": self.transport,
            "target": self.target,
            "platform": self.platform,
            "action": self.action,
            "template_id": self.template_id,
            "profile_id": self.profile_id,
            "approval_id": self.approval_id,
            "scope_hash": self.scope_hash,
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "connection": self.connection,
            "identity_source": self.identity_source,
            "endpoint_profile": self.endpoint_profile,
            "host_verification_policy": self.host_verification_policy,
            "execution_contract": self.execution_contract,
            "materialized_params": self.materialized_params,
            "parameter_values_source": self.parameter_values_source,
            "parameter_values_scope": self.parameter_values_scope,
            "parameter_values_hash": self.parameter_values_hash,
            "materialization_required": self.materialization_required,
            "fixed_template_only": self.fixed_template_only,
        }


def build_remote_reference_bundle(
    *,
    transport: str,
    target: str,
    platform: str,
    profile_id: str | None,
    deployment_state: str | None,
    remote_runtime_account: str | None,
    reference_request: dict[str, Any],
    reference_preflight: dict[str, Any],
    connection: dict[str, Any],
    auth_requirements: list[str] | tuple[str, ...],
    approval_binding: dict[str, Any],
    trace_binding: dict[str, Any],
    execution_contract: dict[str, Any],
    post_check_plan: list[str] | tuple[str, ...],
    rollback_plan: list[str] | tuple[str, ...],
    requirements: list[str] | tuple[str, ...],
    next_stage: str,
) -> dict[str, Any]:
    bundle = RemoteExecutionReferenceBundle(
        transport=transport,
        target=target,
        platform=platform,
        profile_id=profile_id,
        deployment_state=deployment_state,
        remote_runtime_account=remote_runtime_account,
        reference_request=reference_request,
        reference_preflight=reference_preflight,
        connection=RemoteConnectionContract(
            transport=transport,
            target=str(connection.get("target") or target),
            port=int(connection.get("port") or 0),
            username=connection.get("username"),
            auth_ref=connection.get("auth_ref"),
            auth_mode=connection.get("auth_mode"),
            endpoint=connection.get("endpoint"),
            requires_known_host=connection.get("requires_known_host"),
            strict_host_key_checking=connection.get("strict_host_key_checking"),
            https_recommended=connection.get("https_recommended"),
        ),
        auth_requirements=tuple(auth_requirements),
        approval_binding=RemoteApprovalBindingContract(
            required_for_real_execution=bool(approval_binding.get("required_for_real_execution")),
            approval_id_present=bool(approval_binding.get("approval_id_present")),
            scope_hash_present=bool(approval_binding.get("scope_hash_present")),
            scope_hash_should_bind=tuple(approval_binding.get("scope_hash_should_bind") or ()),
            approval_id=approval_binding.get("approval_id"),
            scope_hash=approval_binding.get("scope_hash"),
        ),
        trace_binding=RemoteTraceBindingContract(
            trace_id_present=bool(trace_binding.get("trace_id_present")),
            session_id_present=bool(trace_binding.get("session_id_present")),
            required_for_remote_audit=bool(trace_binding.get("required_for_remote_audit")),
            trace_id=trace_binding.get("trace_id"),
            session_id=trace_binding.get("session_id"),
        ),
        execution_contract=RemoteExecutionStageContract(
            adapter_kind=str(execution_contract.get("adapter_kind") or transport),
            fixed_template_only=bool(execution_contract.get("fixed_template_only")),
            target=str(execution_contract.get("target") or target),
            platform=str(execution_contract.get("platform") or platform),
            real_execution_enabled=bool(execution_contract.get("real_execution_enabled")),
            expected_execute_stage=str(
                execution_contract.get("expected_execute_stage") or next_stage
            ),
        ),
        post_check_plan=tuple(post_check_plan),
        rollback_plan=tuple(rollback_plan),
        requirements=tuple(requirements),
        next_stage=next_stage,
    )
    return bundle.to_dict()


def _build_remote_contract_readiness(
    *,
    bundle_validation: dict[str, Any],
    approval_binding: dict[str, Any],
    trace_binding: dict[str, Any],
    execution_contract: dict[str, Any],
    include_handoff_ok: bool = False,
) -> dict[str, Any]:
    readiness = {
        "bundle_ok": bool(bundle_validation.get("ok")),
        "request_contract_ok": bool(bundle_validation.get("request_contract_ok")),
        "approval_ready": bool(approval_binding.get("approval_id")) and bool(approval_binding.get("scope_hash")),
        "trace_ready": bool(trace_binding.get("trace_id")) and bool(trace_binding.get("session_id")),
        "real_execution_enabled": bool(execution_contract.get("real_execution_enabled")),
        "ready_for_real_execution": False,
        "missing_for_real_execution": [],
    }
    if include_handoff_ok:
        readiness["handoff_ok"] = bool(bundle_validation.get("handoff_ok"))
    if not readiness["approval_ready"]:
        readiness["missing_for_real_execution"].append("approval_id_or_scope_hash")
    if not readiness["trace_ready"]:
        readiness["missing_for_real_execution"].append("trace_id_or_session_id")
    if include_handoff_ok and not readiness.get("handoff_ok"):
        readiness["missing_for_real_execution"].append("adapter_handoff_not_validated")
    if not readiness["real_execution_enabled"]:
        readiness["missing_for_real_execution"].append("real_execution_not_enabled")
    readiness["ready_for_real_execution"] = bool(
        readiness["bundle_ok"]
        and readiness["request_contract_ok"]
        and readiness["approval_ready"]
        and readiness["trace_ready"]
        and (not include_handoff_ok or readiness.get("handoff_ok"))
        and readiness["real_execution_enabled"]
    )
    return readiness


def build_remote_adapter_handoff_request(
    bundle: dict[str, Any],
    *,
    bundle_validation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(bundle, dict):
        return {}

    reference_request = bundle.get("reference_request")
    approval_binding = bundle.get("approval_binding")
    trace_binding = bundle.get("trace_binding")
    execution_contract = bundle.get("execution_contract")
    bundle_validation = bundle_validation or bundle.get("bundle_validation")
    if not isinstance(reference_request, dict):
        reference_request = {}
    if not isinstance(approval_binding, dict):
        approval_binding = {}
    if not isinstance(trace_binding, dict):
        trace_binding = {}
    if not isinstance(execution_contract, dict):
        execution_contract = {}
    if not isinstance(bundle_validation, dict):
        bundle_validation = {}

    readiness = _build_remote_contract_readiness(
        bundle_validation=bundle_validation,
        approval_binding=approval_binding,
        trace_binding=trace_binding,
        execution_contract=execution_contract,
    )

    handoff = RemoteAdapterHandoffRequest(
        transport=str(bundle.get("transport") or ""),
        target=str(bundle.get("target") or ""),
        platform=str(bundle.get("platform") or ""),
        action=str(reference_request.get("action") or ""),
        template_id=str(reference_request.get("template_id") or ""),
        profile_id=bundle.get("profile_id"),
        deployment_state=bundle.get("deployment_state"),
        approval_id=approval_binding.get("approval_id"),
        scope_hash=approval_binding.get("scope_hash"),
        trace_id=trace_binding.get("trace_id"),
        session_id=trace_binding.get("session_id"),
        connection=reference_request.get("connection") if isinstance(reference_request.get("connection"), dict) else {},
        identity_source=reference_request.get("identity_source"),
        endpoint_profile=reference_request.get("endpoint_profile"),
        host_verification_policy=reference_request.get("host_verification_policy"),
        execution_contract=execution_contract,
        health_probe_contract=reference_request.get("health_probe_contract") if isinstance(reference_request.get("health_probe_contract"), dict) else {},
        post_check_contract=reference_request.get("post_check_contract") if isinstance(reference_request.get("post_check_contract"), list) else [],
        rollback_contract=reference_request.get("rollback_contract") if isinstance(reference_request.get("rollback_contract"), list) else [],
        auth_requirements=tuple(bundle.get("auth_requirements") or ()),
        requirements=tuple(bundle.get("requirements") or ()),
        next_stage=str(bundle.get("next_stage") or ""),
        readiness=readiness,
    )
    return handoff.to_dict()


def validate_remote_adapter_handoff_request(handoff: dict[str, Any]) -> tuple[bool, list[str]]:
    errors: list[str] = []
    if not isinstance(handoff, dict):
        return False, ["handoff_must_be_object"]
    if handoff.get("schema_version") != "remote-adapter-handoff-v1":
        errors.append("handoff_schema_version_invalid")
    for key in ("transport", "target", "platform", "action", "template_id", "next_stage"):
        if not handoff.get(key):
            errors.append(f"handoff_{key}_required")

    connection = handoff.get("connection")
    if not isinstance(connection, dict):
        errors.append("handoff_connection_required")
    else:
        if connection.get("target") != handoff.get("target"):
            errors.append("handoff_connection_target_mismatch")
        port = connection.get("port")
        if not isinstance(port, int) or port <= 0:
            errors.append("handoff_connection_port_invalid")

    readiness = handoff.get("readiness")
    if not isinstance(readiness, dict):
        errors.append("handoff_readiness_required")
    else:
        for key in (
            "bundle_ok",
            "request_contract_ok",
            "approval_ready",
            "trace_ready",
            "real_execution_enabled",
            "ready_for_real_execution",
            "missing_for_real_execution",
        ):
            if key not in readiness:
                errors.append(f"handoff_readiness_{key}_required")
        if isinstance(readiness.get("missing_for_real_execution"), list):
            if readiness.get("ready_for_real_execution") and readiness.get("missing_for_real_execution"):
                errors.append("handoff_missing_for_real_execution_should_be_empty_when_ready")

    if not handoff.get("identity_source"):
        errors.append("handoff_identity_source_required")
    if not handoff.get("endpoint_profile"):
        errors.append("handoff_endpoint_profile_required")
    if not handoff.get("host_verification_policy"):
        errors.append("handoff_host_verification_policy_required")
    if not isinstance(handoff.get("health_probe_contract"), dict):
        errors.append("handoff_health_probe_contract_required")
    if not isinstance(handoff.get("post_check_contract"), list):
        errors.append("handoff_post_check_contract_required")
    if not isinstance(handoff.get("rollback_contract"), list):
        errors.append("handoff_rollback_contract_required")

    return (len(errors) == 0), errors


def build_remote_adapter_execute_request_preview(
    bundle: dict[str, Any],
    *,
    handoff: dict[str, Any] | None = None,
    bundle_validation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(bundle, dict):
        return {}

    reference_request = bundle.get("reference_request")
    approval_binding = bundle.get("approval_binding")
    trace_binding = bundle.get("trace_binding")
    execution_contract = bundle.get("execution_contract")
    bundle_validation = bundle_validation or bundle.get("bundle_validation")
    handoff = handoff or build_remote_adapter_handoff_request(bundle, bundle_validation=bundle_validation)
    if not isinstance(reference_request, dict):
        reference_request = {}
    if not isinstance(approval_binding, dict):
        approval_binding = {}
    if not isinstance(trace_binding, dict):
        trace_binding = {}
    if not isinstance(execution_contract, dict):
        execution_contract = {}
    if not isinstance(bundle_validation, dict):
        bundle_validation = {}
    if not isinstance(handoff, dict):
        handoff = {}

    readiness = _build_remote_contract_readiness(
        bundle_validation=bundle_validation,
        approval_binding=approval_binding,
        trace_binding=trace_binding,
        execution_contract=execution_contract,
        include_handoff_ok=True,
    )

    parameter_contract = {
        "params_keys": list(reference_request.get("params_keys") or []),
        "raw_command_present": bool(reference_request.get("raw_command_present")),
        "denied_request_keys": list(reference_request.get("denied_request_keys") or []),
        "fixed_template_only": bool(reference_request.get("fixed_template_only")),
    }
    parameter_materialization = {
        "mode": "approval_bound_execute_after_reference",
        "parameter_values_in_summary": False,
        "parameter_values_source": "execute_after_approval.params",
        "parameter_values_scope": list(parameter_contract.get("params_keys") or []),
        "requires_approval_scope_hash": True,
        "requires_trace_binding": True,
        "notes": [
            "The future remote adapter must materialize parameter values from the approved execute_after payload, not from audit summaries.",
            "Parameter keys may appear in preflight and contract previews, but raw values must stay outside request summaries.",
        ],
    }

    preview = RemoteAdapterExecuteRequestPreview(
        transport=str(bundle.get("transport") or ""),
        target=str(bundle.get("target") or ""),
        platform=str(bundle.get("platform") or ""),
        action=str(reference_request.get("action") or ""),
        template_id=str(reference_request.get("template_id") or ""),
        profile_id=bundle.get("profile_id"),
        deployment_state=bundle.get("deployment_state"),
        approval_id=approval_binding.get("approval_id"),
        scope_hash=approval_binding.get("scope_hash"),
        trace_id=trace_binding.get("trace_id"),
        session_id=trace_binding.get("session_id"),
        connection=reference_request.get("connection") if isinstance(reference_request.get("connection"), dict) else {},
        identity_source=reference_request.get("identity_source"),
        endpoint_profile=reference_request.get("endpoint_profile"),
        host_verification_policy=reference_request.get("host_verification_policy"),
        parameter_contract=parameter_contract,
        parameter_materialization=parameter_materialization,
        execution_contract=execution_contract,
        health_probe_contract=reference_request.get("health_probe_contract") if isinstance(reference_request.get("health_probe_contract"), dict) else {},
        post_check_contract=reference_request.get("post_check_contract") if isinstance(reference_request.get("post_check_contract"), list) else [],
        rollback_contract=reference_request.get("rollback_contract") if isinstance(reference_request.get("rollback_contract"), list) else [],
        auth_requirements=tuple(bundle.get("auth_requirements") or ()),
        requirements=tuple(bundle.get("requirements") or ()),
        next_stage=str(bundle.get("next_stage") or ""),
        readiness=readiness,
        source_handoff_schema_version=str(handoff.get("schema_version") or "") or None,
    )
    return preview.to_dict()


def build_remote_adapter_execute_schema(preview: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(preview, dict):
        return {}

    parameter_contract = preview.get("parameter_contract") if isinstance(preview.get("parameter_contract"), dict) else {}
    parameter_materialization = preview.get("parameter_materialization") if isinstance(preview.get("parameter_materialization"), dict) else {}
    execution_contract = preview.get("execution_contract") if isinstance(preview.get("execution_contract"), dict) else {}

    schema = RemoteAdapterExecuteSchema(
        transport=str(preview.get("transport") or ""),
        target=str(preview.get("target") or ""),
        platform=str(preview.get("platform") or ""),
        action=str(preview.get("action") or ""),
        template_id=str(preview.get("template_id") or ""),
        profile_id=preview.get("profile_id"),
        approval_id=preview.get("approval_id"),
        scope_hash=preview.get("scope_hash"),
        trace_id=preview.get("trace_id"),
        session_id=preview.get("session_id"),
        connection=preview.get("connection") if isinstance(preview.get("connection"), dict) else {},
        identity_source=preview.get("identity_source"),
        endpoint_profile=preview.get("endpoint_profile"),
        host_verification_policy=preview.get("host_verification_policy"),
        execution_contract=execution_contract,
        parameter_values_source=str(parameter_materialization.get("parameter_values_source") or ""),
        parameter_values_scope=list(parameter_materialization.get("parameter_values_scope") or []),
        materialization_required=bool(parameter_materialization.get("requires_approval_scope_hash")) and bool(parameter_materialization.get("requires_trace_binding")),
        fixed_template_only=bool(parameter_contract.get("fixed_template_only")),
    )
    return schema.to_dict()


def validate_remote_adapter_execute_schema(schema: dict[str, Any]) -> tuple[bool, list[str]]:
    errors: list[str] = []
    if not isinstance(schema, dict):
        return False, ["execute_schema_must_be_object"]
    if schema.get("schema_version") != "remote-adapter-execute-schema-v1":
        errors.append("execute_schema_version_invalid")
    for key in ("transport", "target", "platform", "action", "template_id", "parameter_values_source"):
        if not schema.get(key):
            errors.append(f"execute_schema_{key}_required")
    if schema.get("parameter_values_source") != "execute_after_approval.params":
        errors.append("execute_schema_parameter_values_source_invalid")
    values_scope = schema.get("parameter_values_scope")
    if not isinstance(values_scope, list) or not values_scope:
        errors.append("execute_schema_parameter_values_scope_required")
    if schema.get("materialization_required") is not True:
        errors.append("execute_schema_materialization_required_must_be_true")
    if schema.get("fixed_template_only") is not True:
        errors.append("execute_schema_fixed_template_only_must_be_true")
    connection = schema.get("connection")
    if not isinstance(connection, dict):
        errors.append("execute_schema_connection_required")
    else:
        if connection.get("target") != schema.get("target"):
            errors.append("execute_schema_connection_target_mismatch")
        port = connection.get("port")
        if not isinstance(port, int) or port <= 0:
            errors.append("execute_schema_connection_port_invalid")
    if not schema.get("identity_source"):
        errors.append("execute_schema_identity_source_required")
    if not schema.get("endpoint_profile"):
        errors.append("execute_schema_endpoint_profile_required")
    if not schema.get("host_verification_policy"):
        errors.append("execute_schema_host_verification_policy_required")
    return (len(errors) == 0), errors


def build_remote_adapter_consume_request(
    execute_schema: dict[str, Any],
    *,
    execute_after_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(execute_schema, dict):
        return {}
    execute_after_params = execute_after_params or {}
    values_scope = list(execute_schema.get("parameter_values_scope") or [])
    materialized_params = {
        key: execute_after_params[key]
        for key in values_scope
        if key in execute_after_params
    }
    materialized_scope = sorted(materialized_params.keys())
    parameter_values_hash = None
    if materialized_params:
        parameter_values_hash = build_approval_scope_hash(
            str(execute_schema.get("template_id") or ""),
            str(execute_schema.get("action") or ""),
            str(execute_schema.get("target") or "local"),
            materialized_params,
        )
    request = RemoteAdapterConsumeRequest(
        transport=str(execute_schema.get("transport") or ""),
        target=str(execute_schema.get("target") or ""),
        platform=str(execute_schema.get("platform") or ""),
        action=str(execute_schema.get("action") or ""),
        template_id=str(execute_schema.get("template_id") or ""),
        profile_id=execute_schema.get("profile_id"),
        approval_id=execute_schema.get("approval_id"),
        scope_hash=execute_schema.get("scope_hash"),
        trace_id=execute_schema.get("trace_id"),
        session_id=execute_schema.get("session_id"),
        connection=execute_schema.get("connection") if isinstance(execute_schema.get("connection"), dict) else {},
        identity_source=execute_schema.get("identity_source"),
        endpoint_profile=execute_schema.get("endpoint_profile"),
        host_verification_policy=execute_schema.get("host_verification_policy"),
        execution_contract=execute_schema.get("execution_contract") if isinstance(execute_schema.get("execution_contract"), dict) else {},
        materialized_params=materialized_params,
        parameter_values_source=str(execute_schema.get("parameter_values_source") or ""),
        parameter_values_scope=materialized_scope,
        parameter_values_hash=parameter_values_hash,
        materialization_required=bool(execute_schema.get("materialization_required")),
        fixed_template_only=bool(execute_schema.get("fixed_template_only")),
    )
    return request.to_dict()


def validate_remote_adapter_consume_request(request: dict[str, Any]) -> tuple[bool, list[str]]:
    errors: list[str] = []
    if not isinstance(request, dict):
        return False, ["consume_request_must_be_object"]
    if request.get("schema_version") != "remote-adapter-consume-request-v1":
        errors.append("consume_request_schema_version_invalid")
    for key in ("transport", "target", "platform", "action", "template_id", "parameter_values_source"):
        if not request.get(key):
            errors.append(f"consume_request_{key}_required")
    if request.get("parameter_values_source") != "execute_after_approval.params":
        errors.append("consume_request_parameter_values_source_invalid")
    values_scope = request.get("parameter_values_scope")
    if not isinstance(values_scope, list) or not values_scope:
        errors.append("consume_request_parameter_values_scope_required")
    materialized_params = request.get("materialized_params")
    if not isinstance(materialized_params, dict):
        errors.append("consume_request_materialized_params_required")
    else:
        if sorted(materialized_params.keys()) != sorted(values_scope or []):
            errors.append("consume_request_materialized_params_scope_mismatch")
    if not isinstance(request.get("parameter_values_hash"), str) or not str(request.get("parameter_values_hash")).startswith("sha256:"):
        errors.append("consume_request_parameter_values_hash_invalid")
    if request.get("materialization_required") is not True:
        errors.append("consume_request_materialization_required_must_be_true")
    if request.get("fixed_template_only") is not True:
        errors.append("consume_request_fixed_template_only_must_be_true")
    connection = request.get("connection")
    if not isinstance(connection, dict):
        errors.append("consume_request_connection_required")
    else:
        if connection.get("target") != request.get("target"):
            errors.append("consume_request_connection_target_mismatch")
        port = connection.get("port")
        if not isinstance(port, int) or port <= 0:
            errors.append("consume_request_connection_port_invalid")
    if not isinstance(request.get("scope_hash"), str) or not str(request.get("scope_hash")).startswith("sha256:"):
        errors.append("consume_request_scope_hash_invalid")
    if not request.get("trace_id") or not request.get("session_id"):
        errors.append("consume_request_trace_binding_required")
    if not request.get("identity_source"):
        errors.append("consume_request_identity_source_required")
    if not request.get("endpoint_profile"):
        errors.append("consume_request_endpoint_profile_required")
    if not request.get("host_verification_policy"):
        errors.append("consume_request_host_verification_policy_required")
    return (len(errors) == 0), errors


def build_remote_consumed_execution_agent_request(consume_request: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(consume_request, dict):
        return {}
    params = consume_request.get("materialized_params") if isinstance(consume_request.get("materialized_params"), dict) else {}
    return {
        "consumed_execution_agent_request_mode": "approved" if consume_request.get("approval_id") else "preview",
        "template_id": str(consume_request.get("template_id") or ""),
        "action": str(consume_request.get("action") or ""),
        "platform": str(consume_request.get("platform") or ""),
        "target": str(consume_request.get("target") or "local"),
        "params": params,
        "profile_id": consume_request.get("profile_id"),
        "approval_id": consume_request.get("approval_id"),
        "scope_hash": consume_request.get("scope_hash"),
        "trace_id": consume_request.get("trace_id"),
        "session_id": consume_request.get("session_id"),
        "transport": consume_request.get("transport"),
        "connection": consume_request.get("connection") if isinstance(consume_request.get("connection"), dict) else {},
        "identity_source": consume_request.get("identity_source"),
        "endpoint_profile": consume_request.get("endpoint_profile"),
        "host_verification_policy": consume_request.get("host_verification_policy"),
        "health_probe_contract": None,
        "post_check_contract": None,
        "rollback_contract": None,
        "raw_command_present": False,
        "params_keys": sorted(str(key) for key in params.keys()),
        "fixed_template_only": True,
        "source_consume_request_schema_version": consume_request.get("schema_version"),
        "parameter_values_hash": consume_request.get("parameter_values_hash"),
    }


def validate_remote_consumed_execution_agent_request(request: dict[str, Any]) -> tuple[bool, list[str]]:
    errors: list[str] = []
    if not isinstance(request, dict):
        return False, ["consumed_execution_agent_request_must_be_object"]
    for key in ("template_id", "action", "platform", "target", "transport"):
        if not request.get(key):
            errors.append(f"consumed_execution_agent_request_{key}_required")
    params = request.get("params")
    if not isinstance(params, dict) or not params:
        errors.append("consumed_execution_agent_request_params_required")
    params_keys = request.get("params_keys")
    if not isinstance(params_keys, list) or sorted(params_keys) != sorted(params.keys() if isinstance(params, dict) else []):
        errors.append("consumed_execution_agent_request_params_keys_mismatch")
    if request.get("raw_command_present") is not False:
        errors.append("consumed_execution_agent_request_raw_command_must_be_false")
    if request.get("fixed_template_only") is not True:
        errors.append("consumed_execution_agent_request_fixed_template_only_must_be_true")
    if not isinstance(request.get("scope_hash"), str) or not str(request.get("scope_hash")).startswith("sha256:"):
        errors.append("consumed_execution_agent_request_scope_hash_invalid")
    if not request.get("trace_id") or not request.get("session_id"):
        errors.append("consumed_execution_agent_request_trace_binding_required")
    connection = request.get("connection")
    if not isinstance(connection, dict):
        errors.append("consumed_execution_agent_request_connection_required")
    else:
        if connection.get("target") != request.get("target"):
            errors.append("consumed_execution_agent_request_connection_target_mismatch")
    if not request.get("identity_source"):
        errors.append("consumed_execution_agent_request_identity_source_required")
    if not request.get("endpoint_profile"):
        errors.append("consumed_execution_agent_request_endpoint_profile_required")
    if not request.get("host_verification_policy"):
        errors.append("consumed_execution_agent_request_host_verification_policy_required")
    if request.get("source_consume_request_schema_version") != "remote-adapter-consume-request-v1":
        errors.append("consumed_execution_agent_request_source_schema_version_invalid")
    if not isinstance(request.get("parameter_values_hash"), str) or not str(request.get("parameter_values_hash")).startswith("sha256:"):
        errors.append("consumed_execution_agent_request_parameter_values_hash_invalid")
    if request.get("consumed_execution_agent_request_mode") not in {"preview", "approved"}:
        errors.append("consumed_execution_agent_request_mode_invalid")
    if request.get("consumed_execution_agent_request_mode") == "approved" and not request.get("approval_id"):
        errors.append("consumed_execution_agent_request_approval_id_required")
    return (len(errors) == 0), errors


def validate_remote_adapter_execute_request_preview(preview: dict[str, Any]) -> tuple[bool, list[str]]:
    errors: list[str] = []
    if not isinstance(preview, dict):
        return False, ["execute_request_preview_must_be_object"]
    if preview.get("schema_version") != "remote-adapter-execute-request-preview-v1":
        errors.append("execute_request_preview_schema_version_invalid")
    for key in ("transport", "target", "platform", "action", "template_id", "next_stage"):
        if not preview.get(key):
            errors.append(f"execute_request_preview_{key}_required")

    connection = preview.get("connection")
    if not isinstance(connection, dict):
        errors.append("execute_request_preview_connection_required")
    else:
        if connection.get("target") != preview.get("target"):
            errors.append("execute_request_preview_connection_target_mismatch")
        port = connection.get("port")
        if not isinstance(port, int) or port <= 0:
            errors.append("execute_request_preview_connection_port_invalid")

    parameter_contract = preview.get("parameter_contract")
    if not isinstance(parameter_contract, dict):
        errors.append("execute_request_preview_parameter_contract_required")
    else:
        params_keys = parameter_contract.get("params_keys")
        denied_request_keys = parameter_contract.get("denied_request_keys")
        if not isinstance(params_keys, list) or not params_keys:
            errors.append("execute_request_preview_params_keys_required")
        if parameter_contract.get("raw_command_present") is not False:
            errors.append("execute_request_preview_raw_command_must_be_false")
        if parameter_contract.get("fixed_template_only") is not True:
            errors.append("execute_request_preview_fixed_template_only_must_be_true")
        if not isinstance(denied_request_keys, list):
            errors.append("execute_request_preview_denied_request_keys_invalid")
        elif denied_request_keys:
            errors.append("execute_request_preview_denied_request_keys_must_be_empty")

    parameter_materialization = preview.get("parameter_materialization")
    if not isinstance(parameter_materialization, dict):
        errors.append("execute_request_preview_parameter_materialization_required")
    else:
        if parameter_materialization.get("mode") != "approval_bound_execute_after_reference":
            errors.append("execute_request_preview_parameter_materialization_mode_invalid")
        if parameter_materialization.get("parameter_values_in_summary") is not False:
            errors.append("execute_request_preview_parameter_values_in_summary_must_be_false")
        if parameter_materialization.get("parameter_values_source") != "execute_after_approval.params":
            errors.append("execute_request_preview_parameter_values_source_invalid")
        if parameter_materialization.get("requires_approval_scope_hash") is not True:
            errors.append("execute_request_preview_requires_approval_scope_hash_must_be_true")
        if parameter_materialization.get("requires_trace_binding") is not True:
            errors.append("execute_request_preview_requires_trace_binding_must_be_true")
        values_scope = parameter_materialization.get("parameter_values_scope")
        if not isinstance(values_scope, list):
            errors.append("execute_request_preview_parameter_values_scope_invalid")
        elif values_scope != parameter_contract.get("params_keys"):
            errors.append("execute_request_preview_parameter_values_scope_mismatch")

    readiness = preview.get("readiness")
    if not isinstance(readiness, dict):
        errors.append("execute_request_preview_readiness_required")
    else:
        for key in (
            "bundle_ok",
            "request_contract_ok",
            "handoff_ok",
            "approval_ready",
            "trace_ready",
            "real_execution_enabled",
            "ready_for_real_execution",
            "missing_for_real_execution",
        ):
            if key not in readiness:
                errors.append(f"execute_request_preview_readiness_{key}_required")
        if isinstance(readiness.get("missing_for_real_execution"), list):
            if readiness.get("ready_for_real_execution") and readiness.get("missing_for_real_execution"):
                errors.append("execute_request_preview_missing_for_real_execution_should_be_empty_when_ready")

    if preview.get("source_handoff_schema_version") != "remote-adapter-handoff-v1":
        errors.append("execute_request_preview_source_handoff_schema_version_invalid")
    if not preview.get("identity_source"):
        errors.append("execute_request_preview_identity_source_required")
    if not preview.get("endpoint_profile"):
        errors.append("execute_request_preview_endpoint_profile_required")
    if not preview.get("host_verification_policy"):
        errors.append("execute_request_preview_host_verification_policy_required")
    if not isinstance(preview.get("health_probe_contract"), dict):
        errors.append("execute_request_preview_health_probe_contract_required")
    if not isinstance(preview.get("post_check_contract"), list):
        errors.append("execute_request_preview_post_check_contract_required")
    if not isinstance(preview.get("rollback_contract"), list):
        errors.append("execute_request_preview_rollback_contract_required")

    return (len(errors) == 0), errors


def validate_remote_reference_request_contract(
    reference_request: dict[str, Any],
    *,
    transport: str,
) -> tuple[bool, list[str]]:
    errors: list[str] = []
    action = str(reference_request.get("action") or "")
    identity_source = reference_request.get("identity_source")
    endpoint_profile = reference_request.get("endpoint_profile")
    host_verification_policy = reference_request.get("host_verification_policy")

    if not identity_source:
        errors.append("reference_request_identity_source_required")
    if not endpoint_profile:
        errors.append("reference_request_endpoint_profile_required")
    if not host_verification_policy:
        errors.append("reference_request_host_verification_policy_required")
    if transport == "ssh":
        if identity_source and not str(identity_source).startswith("ssh_"):
            errors.append("ssh_identity_source_invalid")
        if host_verification_policy not in {"known_hosts_strict"}:
            errors.append("ssh_host_verification_policy_invalid")
    elif transport == "winrm":
        if identity_source and not str(identity_source).startswith("winrm_"):
            errors.append("winrm_identity_source_invalid")
        if host_verification_policy not in {"winrm_listener_and_tls_policy"}:
            errors.append("winrm_host_verification_policy_invalid")

    health_probe_contract = reference_request.get("health_probe_contract")
    if not isinstance(health_probe_contract, dict):
        errors.append("reference_request_health_probe_contract_invalid")
    else:
        probe_family = health_probe_contract.get("probe_family")
        if not probe_family:
            errors.append("reference_request_health_probe_family_required")
        if probe_family in {"linux_service_health", "windows_service_health"}:
            if not health_probe_contract.get("service"):
                errors.append("reference_request_health_probe_service_required")
            checks = health_probe_contract.get("checks")
            if not isinstance(checks, list) or not checks:
                errors.append("reference_request_health_probe_checks_required")
        elif probe_family in {"linux_generic", "windows_generic"}:
            checks = health_probe_contract.get("checks")
            if not isinstance(checks, list) or not checks:
                errors.append("reference_request_health_probe_checks_required")

    contract_items: dict[str, list[dict[str, Any]]] = {}
    for key, error_name in (
        ("post_check_contract", "reference_request_post_check_contract_invalid"),
        ("rollback_contract", "reference_request_rollback_contract_invalid"),
    ):
        items = reference_request.get(key)
        if not isinstance(items, list) or not items:
            errors.append(error_name)
            continue
        contract_items[key] = [item for item in items if isinstance(item, dict)]
        for item in items:
            if not isinstance(item, dict) or not item.get("kind"):
                errors.append(f"{key}_item_kind_required")
                break

    connection = reference_request.get("connection")
    if not isinstance(connection, dict):
        errors.append("reference_request_connection_required")
    else:
        if not connection.get("target"):
            errors.append("reference_request_connection_target_required")
        port = connection.get("port")
        if not isinstance(port, int) or port <= 0:
            errors.append("reference_request_connection_port_invalid")
        if transport == "ssh":
            if connection.get("auth_mode") != "ssh_key_or_agent":
                errors.append("ssh_connection_auth_mode_invalid")
            if connection.get("requires_known_host") is not True:
                errors.append("ssh_connection_requires_known_host_must_be_true")
            if connection.get("strict_host_key_checking") is not True:
                errors.append("ssh_connection_strict_host_key_checking_must_be_true")
        elif transport == "winrm":
            if connection.get("auth_mode") != "winrm_psremoting":
                errors.append("winrm_connection_auth_mode_invalid")
            if not connection.get("endpoint"):
                errors.append("winrm_connection_endpoint_required")
            if "https_recommended" not in connection:
                errors.append("winrm_connection_https_recommended_required")

    post_check_kinds = {str(item.get("kind")) for item in contract_items.get("post_check_contract", []) if item.get("kind")}
    rollback_kinds = {str(item.get("kind")) for item in contract_items.get("rollback_contract", []) if item.get("kind")}
    if action == "restart_service":
        if transport == "ssh":
            if health_probe_contract and health_probe_contract.get("probe_family") != "linux_service_health":
                errors.append("linux_restart_service_probe_family_invalid")
            if not {"service_status", "journal_tail"}.issubset(post_check_kinds):
                errors.append("linux_restart_service_post_check_contract_incomplete")
            if "new_approved_restart_plan" not in rollback_kinds:
                errors.append("linux_restart_service_rollback_contract_incomplete")
        elif transport == "winrm":
            if health_probe_contract and health_probe_contract.get("probe_family") != "windows_service_health":
                errors.append("winrm_restart_service_probe_family_invalid")
            if not {"service_status", "event_log_summary"}.issubset(post_check_kinds):
                errors.append("winrm_restart_service_post_check_contract_incomplete")
            if "new_approved_restart_plan" not in rollback_kinds:
                errors.append("winrm_restart_service_rollback_contract_incomplete")

    return (len(errors) == 0), errors


def validate_remote_reference_bundle(bundle: dict[str, Any]) -> tuple[bool, list[str]]:
    errors: list[str] = []

    def require_dict(key: str) -> dict[str, Any]:
        value = bundle.get(key)
        if not isinstance(value, dict):
            errors.append(f"{key}_must_be_object")
            return {}
        return value

    def require_list(key: str) -> list[Any]:
        value = bundle.get(key)
        if not isinstance(value, list):
            errors.append(f"{key}_must_be_list")
            return []
        return value

    for key in ("mode", "transport", "target", "platform", "next_stage"):
        if not bundle.get(key):
            errors.append(f"{key}_required")

    if bundle.get("mode") != "reference_only":
        errors.append("mode_must_be_reference_only")
    if bundle.get("can_execute_now") is not False:
        errors.append("can_execute_now_must_be_false")
    if bundle.get("structured_request_only") is not True:
        errors.append("structured_request_only_must_be_true")

    reference_request = require_dict("reference_request")
    reference_preflight = require_dict("reference_preflight")
    connection = require_dict("connection")
    approval_binding = require_dict("approval_binding")
    trace_binding = require_dict("trace_binding")
    execution_contract = require_dict("execution_contract")
    require_list("auth_requirements")
    require_list("post_check_plan")
    require_list("rollback_plan")
    require_list("requirements")

    if reference_request.get("transport") != bundle.get("transport"):
        errors.append("reference_request_transport_mismatch")
    if connection.get("transport") != bundle.get("transport"):
        errors.append("connection_transport_mismatch")
    if execution_contract.get("adapter_kind") != bundle.get("transport"):
        errors.append("execution_contract_adapter_kind_mismatch")
    if reference_request.get("target") != bundle.get("target"):
        errors.append("reference_request_target_mismatch")
    if reference_request.get("platform") != bundle.get("platform"):
        errors.append("reference_request_platform_mismatch")
    if approval_binding.get("required_for_real_execution") is not True:
        errors.append("approval_binding_required_for_real_execution_must_be_true")
    if approval_binding.get("approval_id_present") and not approval_binding.get("approval_id"):
        errors.append("approval_binding_approval_id_required_when_present")
    if approval_binding.get("scope_hash_present"):
        scope_hash = approval_binding.get("scope_hash")
        if not isinstance(scope_hash, str) or not scope_hash.startswith("sha256:"):
            errors.append("approval_binding_scope_hash_invalid")
    if trace_binding.get("trace_id_present") and not trace_binding.get("trace_id"):
        errors.append("trace_binding_trace_id_required_when_present")
    if trace_binding.get("session_id_present") and not trace_binding.get("session_id"):
        errors.append("trace_binding_session_id_required_when_present")
    if trace_binding.get("required_for_remote_audit") is not True:
        errors.append("trace_binding_required_for_remote_audit_must_be_true")
    if execution_contract.get("real_execution_enabled") is not False:
        errors.append("execution_contract_real_execution_enabled_must_be_false")
    if not reference_preflight.get("summary"):
        errors.append("reference_preflight_summary_required")

    reference_request_ok, reference_request_errors = validate_remote_reference_request_contract(
        reference_request,
        transport=str(bundle.get("transport") or ""),
    )
    if not reference_request_ok:
        errors.extend(reference_request_errors)

    return (len(errors) == 0), errors


def synchronize_remote_reference_bundle(
    bundle: dict[str, Any],
    *,
    tool_name: str,
    operation: str,
    target: str,
    approval_id: str | None = None,
    approval_scope_hash: str | None = None,
    approval_request: dict[str, Any] | None = None,
    trace_id: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    if not isinstance(bundle, dict):
        return {}

    approval_binding = bundle.get("approval_binding")
    if not isinstance(approval_binding, dict):
        approval_binding = {}
        bundle["approval_binding"] = approval_binding

    trace_binding = bundle.get("trace_binding")
    if not isinstance(trace_binding, dict):
        trace_binding = {}
        bundle["trace_binding"] = trace_binding

    reference_request = bundle.get("reference_request")
    if not isinstance(reference_request, dict):
        reference_request = {}
        bundle["reference_request"] = reference_request

    scope_hash = approval_scope_hash
    if not scope_hash and isinstance(approval_request, dict):
        approval_params = approval_request.get("params")
        if isinstance(approval_params, dict):
            scope_hash = build_approval_scope_hash(
                str(approval_request.get("tool_name") or tool_name),
                str(approval_request.get("operation") or operation),
                str(approval_request.get("target") or target or "local"),
                approval_params,
            )

    approval_binding["required_for_real_execution"] = True
    approval_binding["approval_id_present"] = bool(approval_id)
    approval_binding["approval_id"] = approval_id
    approval_binding["scope_hash_present"] = bool(scope_hash)
    approval_binding["scope_hash"] = scope_hash
    approval_binding.setdefault(
        "scope_hash_should_bind",
        ["tool_name", "operation", "target", "platform", "remote endpoint metadata"],
    )

    trace_binding["trace_id_present"] = bool(trace_id)
    trace_binding["trace_id"] = trace_id
    trace_binding["session_id_present"] = bool(session_id)
    trace_binding["session_id"] = session_id
    trace_binding["required_for_remote_audit"] = True

    if approval_id is not None:
        reference_request["approval_id"] = approval_id
    if scope_hash is not None:
        reference_request["scope_hash"] = scope_hash
    if trace_id is not None:
        reference_request["trace_id"] = trace_id
    if session_id is not None:
        reference_request["session_id"] = session_id

    request_ok, request_errors = validate_remote_reference_request_contract(
        reference_request,
        transport=str(bundle.get("transport") or ""),
    )
    bundle_ok, bundle_errors = validate_remote_reference_bundle(bundle)
    validation_state = {
        "ok": bundle_ok,
        "errors": bundle_errors,
        "request_contract_ok": request_ok,
        "request_contract_errors": request_errors,
    }
    handoff = build_remote_adapter_handoff_request(bundle, bundle_validation=validation_state)
    handoff_ok, handoff_errors = validate_remote_adapter_handoff_request(handoff)
    validation_state["handoff_ok"] = handoff_ok
    validation_state["handoff_errors"] = handoff_errors
    execute_request_preview = build_remote_adapter_execute_request_preview(
        bundle,
        handoff=handoff,
        bundle_validation=validation_state,
    )
    execute_request_ok, execute_request_errors = validate_remote_adapter_execute_request_preview(
        execute_request_preview
    )
    execute_schema = build_remote_adapter_execute_schema(execute_request_preview)
    execute_schema_ok, execute_schema_errors = validate_remote_adapter_execute_schema(execute_schema)
    execute_after_params = (approval_request.get("params") if isinstance(approval_request, dict) else None) or {}
    consume_request = build_remote_adapter_consume_request(
        execute_schema,
        execute_after_params=execute_after_params,
    )
    consume_request_ok, consume_request_errors = validate_remote_adapter_consume_request(
        consume_request
    )
    consumed_execution_agent_request = build_remote_consumed_execution_agent_request(consume_request)
    consumed_execution_agent_request_ok, consumed_execution_agent_request_errors = validate_remote_consumed_execution_agent_request(
        consumed_execution_agent_request
    )
    bundle["adapter_handoff"] = handoff
    bundle["execute_request_preview"] = execute_request_preview
    bundle["execute_schema"] = execute_schema
    bundle["consume_request"] = consume_request
    bundle["consumed_execution_agent_request"] = consumed_execution_agent_request
    bundle["bundle_validation"] = {
        "ok": bundle_ok,
        "errors": bundle_errors,
        "request_contract_ok": request_ok,
        "request_contract_errors": request_errors,
        "handoff_ok": handoff_ok,
        "handoff_errors": handoff_errors,
        "execute_request_preview_ok": execute_request_ok,
        "execute_request_preview_errors": execute_request_errors,
        "execute_schema_ok": execute_schema_ok,
        "execute_schema_errors": execute_schema_errors,
        "consume_request_ok": consume_request_ok,
        "consume_request_errors": consume_request_errors,
        "consumed_execution_agent_request_ok": consumed_execution_agent_request_ok,
        "consumed_execution_agent_request_errors": consumed_execution_agent_request_errors,
    }
    return bundle
