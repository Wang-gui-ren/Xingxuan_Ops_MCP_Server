from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from mcp_ops_server.execution.action_templates import ACTION_TEMPLATES
from mcp_ops_server.execution.agents.contracts import (
    build_remote_reference_bundle,
)


LOCAL_AGENT_TARGETS = {"", "local", "localhost", "127.0.0.1", "::1"}
DENIED_AGENT_REQUEST_KEYS = {
    "argv",
    "bash",
    "cmd",
    "command",
    "powershell",
    "raw_command",
    "script",
    "shell",
}


@dataclass(frozen=True)
class ExecutionAgentProfile:
    """真实执行代理的能力档案。

    该档案只描述受限代理能接收哪些固定模板，不负责执行命令。
    """

    profile_id: str
    platform: str
    runtime_account: str
    deployment_state: str
    can_execute_privileged_templates: bool
    summary: str
    allowed_template_ids: tuple[str, ...]
    denied_capabilities: tuple[str, ...]
    controls: tuple[str, ...]
    deployment_artifacts: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def supports_platform(self, platform_name: str) -> bool:
        return self.platform == platform_name

    def supports_template(self, template_id: str | None) -> bool:
        return bool(template_id and template_id in self.allowed_template_ids)

    def identity_matches(self, runtime_identity: str, trusted_identities: set[str]) -> bool:
        current = runtime_identity.strip().lower()
        expected = self.runtime_account.strip().lower()
        return current == expected or current in trusted_identities

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "platform": self.platform,
            "runtime_account": self.runtime_account,
            "deployment_state": self.deployment_state,
            "can_execute_privileged_templates": self.can_execute_privileged_templates,
            "summary": self.summary,
            "allowed_template_ids": list(self.allowed_template_ids),
            "denied_capabilities": list(self.denied_capabilities),
            "controls": list(self.controls),
            "deployment_artifacts": list(self.deployment_artifacts),
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class ExecutionAgentRequest:
    """受限执行代理只接受的结构化模板请求。

    该请求对象用于稳定后续 Linux sudoers / Windows JEA 适配器契约。
    它不会保存任意 shell 命令，也不会把参数值作为审计摘要直接外泄。
    """

    template_id: str
    action: str
    platform: str
    target: str = "local"
    params: dict[str, Any] | None = None
    profile_id: str | None = None
    approval_id: str | None = None
    scope_hash: str | None = None
    trace_id: str | None = None
    session_id: str | None = None
    raw_command: str | None = None
    transport: str | None = None
    connection: dict[str, Any] | None = None
    identity_source: str | None = None
    endpoint_profile: str | None = None
    host_verification_policy: str | None = None
    health_probe_contract: dict[str, Any] | None = None
    post_check_contract: list[dict[str, Any]] | None = None
    rollback_contract: list[dict[str, Any]] | None = None

    def to_dict(self) -> dict[str, Any]:
        params = self.params or {}
        denied_keys = _find_denied_request_keys(params)
        payload = {
            "template_id": self.template_id,
            "action": self.action,
            "platform": self.platform,
            "target": self.target,
            "profile_id": self.profile_id,
            "approval_id": self.approval_id,
            "scope_hash": self.scope_hash,
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "params_keys": sorted(str(key) for key in params.keys()),
            "raw_command_present": bool(self.raw_command),
            "denied_request_keys": denied_keys,
            "fixed_template_only": True,
        }
        if self.transport:
            payload["transport"] = self.transport
        if self.connection is not None:
            payload["connection"] = self.connection
        if self.identity_source:
            payload["identity_source"] = self.identity_source
        if self.endpoint_profile:
            payload["endpoint_profile"] = self.endpoint_profile
        if self.host_verification_policy:
            payload["host_verification_policy"] = self.host_verification_policy
        if self.health_probe_contract is not None:
            payload["health_probe_contract"] = self.health_probe_contract
        if self.post_check_contract is not None:
            payload["post_check_contract"] = self.post_check_contract
        if self.rollback_contract is not None:
            payload["rollback_contract"] = self.rollback_contract
        return payload

    def denied_request_keys(self) -> list[str]:
        keys = _find_denied_request_keys(self.params or {})
        if self.raw_command:
            keys.append("raw_command")
        return sorted(set(keys))


@dataclass(frozen=True)
class ExecutionAgentPreflight:
    """真实受限执行代理调用前的预检结果。"""

    ok: bool
    decision: str
    summary: str
    profile_id: str | None
    deployment_state: str | None
    template_id: str
    action: str
    platform: str
    target: str
    runtime_identity: str
    fixed_template_only: bool
    errors: list[str]
    warnings: list[str]
    checks: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "decision": self.decision,
            "summary": self.summary,
            "profile_id": self.profile_id,
            "deployment_state": self.deployment_state,
            "template_id": self.template_id,
            "action": self.action,
            "platform": self.platform,
            "target": self.target,
            "runtime_identity": self.runtime_identity,
            "fixed_template_only": self.fixed_template_only,
            "errors": self.errors,
            "warnings": self.warnings,
            "checks": self.checks,
        }


@dataclass(frozen=True)
class ExecutionAgentResult:
    """真实执行代理返回契约。

    reference_only 阶段不会执行 sudo/JEA，只返回结构化阻断结果。
    """

    ok: bool
    status: str
    summary: str
    preflight: ExecutionAgentPreflight
    errors: list[str]
    warnings: list[str]
    data: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "status": self.status,
            "summary": self.summary,
            "preflight": self.preflight.to_dict(),
            "errors": self.errors,
            "warnings": self.warnings,
            "data": self.data,
        }


class ExecutionAgentAdapter:
    """受限执行代理适配器基类。

    当前实现只做预检和安全阻断；后续 Linux / Windows 子类必须继续只接受
    `ExecutionAgentRequest`，不能新增任意 shell 或 PowerShell 字符串入口。
    """

    def __init__(self, profile: ExecutionAgentProfile | None) -> None:
        self.profile = profile

    def preflight(
        self,
        request: ExecutionAgentRequest,
        *,
        runtime_identity: str,
        trusted_identities: set[str] | None = None,
    ) -> ExecutionAgentPreflight:
        trusted = {item.lower() for item in (trusted_identities or set())}
        errors: list[str] = []
        warnings: list[str] = []
        profile = self.profile
        template = _get_template_by_id(request.template_id)
        denied_keys = request.denied_request_keys()
        platform_name = (request.platform or "auto").strip().lower()
        target_text = str(request.target or "local")

        checks: dict[str, Any] = {
            "request": request.to_dict(),
            "profile_configured": profile is not None,
            "fixed_template_only": True,
            "arbitrary_shell_allowed": False,
            "template_found": template is not None,
            "local_target_only": target_text in LOCAL_AGENT_TARGETS,
        }

        if denied_keys:
            errors.append(f"execution_agent_request_not_structured: denied_keys={','.join(denied_keys)}")

        if profile is None:
            errors.append("execution_agent_profile_missing")
            warnings.append("请先配置受限执行代理档案，并完成 ops-agent/sudoers 或 Windows JEA 部署验证。")
        else:
            checks["profile"] = profile.to_dict()
            if request.profile_id and request.profile_id != profile.profile_id:
                errors.append(
                    f"execution_agent_profile_mismatch: requested={request.profile_id}, configured={profile.profile_id}"
                )
            if not profile.supports_platform(platform_name):
                errors.append(
                    f"execution_agent_profile_platform_mismatch: profile={profile.profile_id}, "
                    f"profile_platform={profile.platform}, requested_platform={platform_name}"
                )
            if not profile.supports_template(request.template_id):
                errors.append(
                    f"execution_agent_template_not_allowed: profile={profile.profile_id}, "
                    f"template_id={request.template_id}"
                )
            if not profile.can_execute_privileged_templates or profile.deployment_state != "deployed":
                errors.append(
                    f"execution_agent_profile_not_deployed: profile={profile.profile_id}, "
                    f"state={profile.deployment_state}"
                )
                warnings.append("当前档案仍是 reference_only，不声明目标主机已安装受限执行代理。")
            if not profile.identity_matches(runtime_identity, trusted):
                errors.append(
                    f"runtime_identity_not_profile_account: current={runtime_identity}, "
                    f"expected={profile.runtime_account}"
                )
                warnings.append("真实执行应由受限代理身份运行，或通过 XINGXUAN_MCP_TRUSTED_EXECUTION_IDENTITIES 显式列入受信身份。")

        if template is None:
            errors.append(f"execution_agent_template_not_found: template_id={request.template_id}")
        elif request.action and request.action != template.action:
            errors.append(
                f"execution_agent_template_action_mismatch: template_id={request.template_id}, "
                f"request_action={request.action}, template_action={template.action}"
            )

        if target_text not in LOCAL_AGENT_TARGETS:
            errors.append(f"remote_target_not_supported: target={target_text}")

        ok = not errors
        decision = "allow_preflight" if ok else "block"
        summary = (
            "受限执行代理预检通过：请求为固定模板结构且代理档案允许。"
            if ok
            else "受限执行代理预检阻断：请求、档案、平台、身份或部署状态不满足最小权限条件。"
        )
        return ExecutionAgentPreflight(
            ok=ok,
            decision=decision,
            summary=summary,
            profile_id=profile.profile_id if profile else None,
            deployment_state=profile.deployment_state if profile else None,
            template_id=request.template_id,
            action=request.action,
            platform=platform_name,
            target=target_text,
            runtime_identity=runtime_identity,
            fixed_template_only=True,
            errors=errors,
            warnings=warnings,
            checks=checks,
        )

    def execute(
        self,
        request: ExecutionAgentRequest,
        *,
        runtime_identity: str,
        trusted_identities: set[str] | None = None,
    ) -> ExecutionAgentResult:
        preflight = self.preflight(
            request,
            runtime_identity=runtime_identity,
            trusted_identities=trusted_identities,
        )
        errors = list(preflight.errors)
        errors.append("execution_agent_execute_not_implemented: reference adapter refuses real sudo/JEA execution.")
        return ExecutionAgentResult(
            ok=False,
            status="blocked",
            summary="reference_only 执行代理适配器不执行真实系统动作，只返回预检和阻断结果。",
            preflight=preflight,
            errors=errors,
            warnings=list(preflight.warnings),
            data={"safety_boundary": "reference_adapter_no_real_execution"},
        )


class ReferenceExecutionAgentAdapter(ExecutionAgentAdapter):
    """reference_only 代理适配器，用于本地开发和自动化验证。"""


class RemoteReferenceExecutionAgentAdapter(ExecutionAgentAdapter):
    """远程 reference-only 代理适配器。

    该适配器用于“远程写操作受限执行链”的第一阶段：允许生成结构化请求、
    允许给出 preflight 解释，但不允许进入任何真实 SSH / WinRM / JEA 执行。
    """

    def build_contract_request(self, request: ExecutionAgentRequest) -> ExecutionAgentRequest:
        return replace(
            request,
            transport=self.transport(),
            connection=self.connection_plan(request),
            identity_source=self.identity_source(request),
            endpoint_profile=self.endpoint_profile(request),
            host_verification_policy=self.host_verification_policy(request),
            health_probe_contract=self.health_probe_contract(request),
            post_check_contract=self.post_check_contract_structured(request),
            rollback_contract=self.rollback_contract_structured(request),
        )

    def preflight(
        self,
        request: ExecutionAgentRequest,
        *,
        runtime_identity: str,
        trusted_identities: set[str] | None = None,
    ) -> ExecutionAgentPreflight:
        del trusted_identities
        request = self.build_contract_request(request)
        errors: list[str] = []
        warnings: list[str] = []
        profile = self.profile
        template = _get_template_by_id(request.template_id)
        denied_keys = request.denied_request_keys()
        platform_name = (request.platform or "auto").strip().lower()
        target_text = str(request.target or "local")

        checks: dict[str, Any] = {
            "request": request.to_dict(),
            "profile_configured": profile is not None,
            "fixed_template_only": True,
            "arbitrary_shell_allowed": False,
            "template_found": template is not None,
            "remote_target_required": target_text not in LOCAL_AGENT_TARGETS,
            "identity_deferred_to_remote_endpoint": True,
        }

        if denied_keys:
            errors.append(f"execution_agent_request_not_structured: denied_keys={','.join(denied_keys)}")

        if profile is None:
            errors.append("execution_agent_profile_missing")
            warnings.append("请先配置远程受限执行代理档案，再继续生成 reference-only 远程执行计划。")
        else:
            checks["profile"] = profile.to_dict()
            if request.profile_id and request.profile_id != profile.profile_id:
                errors.append(
                    f"execution_agent_profile_mismatch: requested={request.profile_id}, configured={profile.profile_id}"
                )
            if not profile.supports_platform(platform_name):
                errors.append(
                    f"execution_agent_profile_platform_mismatch: profile={profile.profile_id}, "
                    f"profile_platform={profile.platform}, requested_platform={platform_name}"
                )
            if not profile.supports_template(request.template_id):
                errors.append(
                    f"execution_agent_template_not_allowed: profile={profile.profile_id}, "
                    f"template_id={request.template_id}"
                )
            if profile.deployment_state != "deployed":
                warnings.append("当前远程执行档案仍是 reference_only，只用于生成结构化请求和 preflight 说明。")
            if runtime_identity:
                warnings.append(
                    f"当前运行用户为 {runtime_identity}；远程真实执行应由目标端受限身份 {profile.runtime_account} 接管。"
                )

        if template is None:
            errors.append(f"execution_agent_template_not_found: template_id={request.template_id}")
        elif request.action and request.action != template.action:
            errors.append(
                f"execution_agent_template_action_mismatch: template_id={request.template_id}, "
                f"request_action={request.action}, template_action={template.action}"
            )

        if target_text in LOCAL_AGENT_TARGETS:
            errors.append("remote_reference_target_required")

        ok = not errors
        decision = "allow_reference_plan" if ok else "block"
        summary = (
            "远程 reference-only 预检通过：请求已被收敛为固定模板结构，可进入远程执行链规划阶段。"
            if ok
            else "远程 reference-only 预检阻断：请求结构、模板、平台或远程目标不满足要求。"
        )
        return ExecutionAgentPreflight(
            ok=ok,
            decision=decision,
            summary=summary,
            profile_id=profile.profile_id if profile else None,
            deployment_state=profile.deployment_state if profile else None,
            template_id=request.template_id,
            action=request.action,
            platform=platform_name,
            target=target_text,
            runtime_identity=runtime_identity,
            fixed_template_only=True,
            errors=errors,
            warnings=warnings,
            checks=checks,
        )

    def execute(
        self,
        request: ExecutionAgentRequest,
        *,
        runtime_identity: str,
        trusted_identities: set[str] | None = None,
    ) -> ExecutionAgentResult:
        preflight = self.preflight(
            request,
            runtime_identity=runtime_identity,
            trusted_identities=trusted_identities,
        )
        errors = list(preflight.errors)
        errors.append("execution_agent_execute_not_implemented_remote_reference: remote reference adapter refuses real SSH/WinRM/JEA execution.")
        return ExecutionAgentResult(
            ok=False,
            status="blocked",
            summary="远程 reference-only 执行代理不执行真实系统动作，只返回结构化请求和预检结果。",
            preflight=preflight,
            errors=errors,
            warnings=list(preflight.warnings),
            data={"safety_boundary": "remote_reference_adapter_no_real_execution"},
        )

    def build_reference_bundle(
        self,
        request: ExecutionAgentRequest,
        *,
        runtime_identity: str,
        trusted_identities: set[str] | None = None,
    ) -> dict[str, Any]:
        contract_request = self.build_contract_request(request)
        preflight = self.preflight(
            contract_request,
            runtime_identity=runtime_identity,
            trusted_identities=trusted_identities,
        )
        profile = self.profile
        connection = contract_request.connection or self.connection_plan(request)
        return build_remote_reference_bundle(
            transport=self.transport(),
            target=request.target,
            platform=request.platform,
            profile_id=profile.profile_id if profile else None,
            deployment_state=profile.deployment_state if profile else None,
            remote_runtime_account=profile.runtime_account if profile else None,
            reference_request=contract_request.to_dict(),
            reference_preflight=preflight.to_dict(),
            connection=connection,
            auth_requirements=self.auth_requirements(request),
            approval_binding=self.approval_binding(request),
            trace_binding=self.trace_binding(request),
            execution_contract=self.execution_contract(request),
            post_check_plan=self.post_check_plan(request),
            rollback_plan=self.rollback_plan(request),
            requirements=self.requirements(request),
            next_stage=f"remote_{request.action}_execution_chain",
        )

    def transport(self) -> str:
        return "unknown"

    def connection_plan(self, request: ExecutionAgentRequest) -> dict[str, Any]:
        return {"target": request.target}

    def auth_requirements(self, request: ExecutionAgentRequest) -> list[str]:
        del request
        return []

    def identity_source(self, request: ExecutionAgentRequest) -> str:
        del request
        return "remote_endpoint_managed"

    def endpoint_profile(self, request: ExecutionAgentRequest) -> str:
        del request
        return "reference_only"

    def host_verification_policy(self, request: ExecutionAgentRequest) -> str:
        del request
        return "endpoint_default"

    def health_probe_contract(self, request: ExecutionAgentRequest) -> dict[str, Any]:
        return {
            "probe_family": "generic",
            "target": request.target,
            "required_after_real_execution": True,
        }

    def approval_binding(self, request: ExecutionAgentRequest) -> dict[str, Any]:
        return {
            "required_for_real_execution": True,
            "approval_id_present": bool(request.approval_id),
            "approval_id": request.approval_id,
            "scope_hash_present": bool(request.scope_hash),
            "scope_hash": request.scope_hash,
            "scope_hash_should_bind": [
                "tool_name",
                "operation",
                "target",
                "platform",
                "remote endpoint metadata",
            ],
        }

    def trace_binding(self, request: ExecutionAgentRequest) -> dict[str, Any]:
        return {
            "trace_id_present": bool(request.trace_id),
            "trace_id": request.trace_id,
            "session_id_present": bool(request.session_id),
            "session_id": request.session_id,
            "required_for_remote_audit": True,
        }

    def execution_contract(self, request: ExecutionAgentRequest) -> dict[str, Any]:
        return {
            "adapter_kind": self.transport(),
            "fixed_template_only": True,
            "target": request.target,
            "platform": request.platform,
            "real_execution_enabled": False,
            "expected_execute_stage": f"remote_{request.action}_execute",
        }

    def post_check_plan(self, request: ExecutionAgentRequest) -> list[str]:
        del request
        return []

    def rollback_plan(self, request: ExecutionAgentRequest) -> list[str]:
        del request
        return []

    def post_check_contract_structured(self, request: ExecutionAgentRequest) -> list[dict[str, Any]]:
        return [{"kind": "generic_post_check", "required_after_real_execution": True, "target": request.target}]

    def rollback_contract_structured(self, request: ExecutionAgentRequest) -> list[dict[str, Any]]:
        return [{"kind": "new_approved_inverse_plan", "target": request.target, "action": request.action}]

    def requirements(self, request: ExecutionAgentRequest) -> list[str]:
        del request
        return [
            "Prepare remote authentication and target reachability.",
            "Deploy a constrained execution adapter for the target platform.",
            "Keep real remote execution blocked until deployment_state changes from reference_only to deployed.",
        ]


class LinuxSSHReferenceExecutionAgentAdapter(RemoteReferenceExecutionAgentAdapter):
    def transport(self) -> str:
        return "ssh"

    def connection_plan(self, request: ExecutionAgentRequest) -> dict[str, Any]:
        params = request.params or {}
        return {
            "target": request.target,
            "port": int(params.get("remote_port") or params.get("port") or 22),
            "username": params.get("remote_username") or params.get("username"),
            "auth_ref": params.get("remote_auth_ref"),
            "auth_mode": "ssh_key_or_agent",
            "requires_known_host": True,
            "strict_host_key_checking": True,
        }

    def identity_source(self, request: ExecutionAgentRequest) -> str:
        del request
        return "ssh_remote_username_or_host_mapping"

    def endpoint_profile(self, request: ExecutionAgentRequest) -> str:
        del request
        return "linux-ssh-reference-v1"

    def host_verification_policy(self, request: ExecutionAgentRequest) -> str:
        del request
        return "known_hosts_strict"

    def health_probe_contract(self, request: ExecutionAgentRequest) -> dict[str, Any]:
        if request.action == "restart_service":
            return {
                "probe_family": "linux_service_health",
                "service": (request.params or {}).get("service"),
                "checks": ["systemctl status", "recent service logs", "optional port/http probe"],
            }
        return {
            "probe_family": "linux_generic",
            "checks": ["collect remote post-check evidence after implementation"],
        }

    def auth_requirements(self, request: ExecutionAgentRequest) -> list[str]:
        params = request.params or {}
        return [
            "Prepare SSH reachability from the MCP host to the target.",
            f"Use username={params.get('remote_username') or params.get('username') or '<ssh-account>'} or host-level default mapping.",
            "Use SSH key or agent authentication; do not embed passwords in the MCP request.",
            "Prefer remote_auth_ref or host-level credential mapping over inline secrets.",
        ]

    def post_check_plan(self, request: ExecutionAgentRequest) -> list[str]:
        action = request.action
        if action == "restart_service":
            return [
                "Run remote service status check after restart.",
                "Collect recent journal/service log summary from the target host.",
                "Optionally verify bound port or HTTP health probe from the target service.",
            ]
        if action == "network_policy_change":
            return [
                "Query effective firewall rule on the remote host.",
                "Verify target port state from the remote host after rule application.",
            ]
        return [
            "Collect remote post-check evidence after real execution is implemented.",
        ]

    def rollback_plan(self, request: ExecutionAgentRequest) -> list[str]:
        if request.action == "restart_service":
            return [
                "Prepare a new approved remote restart/rollback plan if service health degrades.",
            ]
        if request.action == "network_policy_change":
            return [
                "Prepare a new approved inverse firewall rule plan on the remote host.",
            ]
        return [
            "Prepare a new approved inverse action plan on the remote host.",
        ]

    def post_check_contract_structured(self, request: ExecutionAgentRequest) -> list[dict[str, Any]]:
        if request.action == "restart_service":
            return [
                {"kind": "service_status", "service": (request.params or {}).get("service"), "required": True},
                {"kind": "journal_tail", "service": (request.params or {}).get("service"), "required": True},
                {"kind": "optional_health_probe", "service": (request.params or {}).get("service"), "required": False},
            ]
        return super().post_check_contract_structured(request)

    def rollback_contract_structured(self, request: ExecutionAgentRequest) -> list[dict[str, Any]]:
        if request.action == "restart_service":
            return [
                {"kind": "new_approved_restart_plan", "service": (request.params or {}).get("service"), "target": request.target},
            ]
        return super().rollback_contract_structured(request)


class WindowsWinRMReferenceExecutionAgentAdapter(RemoteReferenceExecutionAgentAdapter):
    def transport(self) -> str:
        return "winrm"

    def connection_plan(self, request: ExecutionAgentRequest) -> dict[str, Any]:
        params = request.params or {}
        return {
            "target": request.target,
            "port": int(params.get("remote_port") or params.get("port") or 5985),
            "username": params.get("remote_username") or params.get("username"),
            "auth_ref": params.get("remote_auth_ref"),
            "auth_mode": "winrm_psremoting",
            "https_recommended": True,
            "endpoint": params.get("remote_endpoint") or "Microsoft.PowerShell",
        }

    def identity_source(self, request: ExecutionAgentRequest) -> str:
        del request
        return "winrm_remote_username_or_endpoint_mapping"

    def endpoint_profile(self, request: ExecutionAgentRequest) -> str:
        return str((request.params or {}).get("remote_endpoint") or "windows-winrm-reference-v1")

    def host_verification_policy(self, request: ExecutionAgentRequest) -> str:
        del request
        return "winrm_listener_and_tls_policy"

    def health_probe_contract(self, request: ExecutionAgentRequest) -> dict[str, Any]:
        if request.action == "restart_service":
            return {
                "probe_family": "windows_service_health",
                "service": (request.params or {}).get("service"),
                "checks": ["Get-Service", "recent event log summary"],
            }
        return {
            "probe_family": "windows_generic",
            "checks": ["collect remote windows post-check evidence after implementation"],
        }

    def auth_requirements(self, request: ExecutionAgentRequest) -> list[str]:
        params = request.params or {}
        return [
            "Prepare WinRM / PowerShell Remoting reachability from the MCP host to the target.",
            f"Use username={params.get('remote_username') or params.get('username') or '<remote-account>'} or endpoint-side default mapping.",
            "Use constrained remoting / JEA endpoint identity; do not embed plaintext passwords in the MCP request.",
            "Prefer remote_auth_ref or host-level credential mapping over inline secrets.",
        ]

    def post_check_plan(self, request: ExecutionAgentRequest) -> list[str]:
        if request.action == "restart_service":
            return [
                "Run remote Windows service status check after restart.",
                "Collect recent service event log summary from the remote host.",
            ]
        if request.action == "network_policy_change":
            return [
                "Query effective Windows Firewall rule on the remote host.",
                "Verify target port state after rule application.",
            ]
        return [
            "Collect remote Windows post-check evidence after real execution is implemented.",
        ]

    def rollback_plan(self, request: ExecutionAgentRequest) -> list[str]:
        if request.action == "network_policy_change":
            return [
                "Prepare a new approved inverse Windows Firewall rule plan on the remote host.",
            ]
        return [
            "Prepare a new approved inverse remote action plan on the Windows host.",
        ]

    def post_check_contract_structured(self, request: ExecutionAgentRequest) -> list[dict[str, Any]]:
        if request.action == "restart_service":
            return [
                {"kind": "service_status", "service": (request.params or {}).get("service"), "required": True},
                {"kind": "event_log_summary", "service": (request.params or {}).get("service"), "required": True},
            ]
        return super().post_check_contract_structured(request)

    def rollback_contract_structured(self, request: ExecutionAgentRequest) -> list[dict[str, Any]]:
        if request.action == "restart_service":
            return [
                {"kind": "new_approved_restart_plan", "service": (request.params or {}).get("service"), "target": request.target},
            ]
        return super().rollback_contract_structured(request)


_LINUX_KYLIN_OPS_AGENT = ExecutionAgentProfile(
    profile_id="linux-kylin-ops-agent-v1",
    platform="linux",
    runtime_account="ops-agent",
    deployment_state="reference_only",
    can_execute_privileged_templates=False,
    summary="Linux/麒麟 V11 受限 ops-agent 档案草案，要求 sudoers allowlist 与 systemd 服务实机部署后才能放开。",
    allowed_template_ids=(
        "TPL_SERVICE_RESTART_V1",
        "TPL_PROCESS_STOP_V1",
        "TPL_PERMISSION_CHANGE_V1",
        "TPL_PACKAGE_MANAGE_V1",
        "TPL_NETWORK_POLICY_V1",
    ),
    denied_capabilities=(
        "arbitrary_shell",
        "wildcard_systemctl",
        "interactive_login",
        "root_default_runtime",
        "script_interpreters_in_sudoers",
    ),
    controls=(
        "fixed_template_only",
        "sudoers_command_allowlist",
        "no_interactive_shell",
        "approval_scope_hash_required",
        "audit_trace_required",
    ),
    deployment_artifacts=(
        "packaging/sudoers/xingxuan-mcp-ops-agent",
        "packaging/systemd/xingxuan-mcp-ops.service",
        "docs/deployment/DEPLOY_KYLIN_V11.md",
    ),
    notes=(
        "reference_only 表示当前仓库提供部署样例和校验契约，但未声明目标主机已完成安装。",
        "只有部署态档案才能配合 XINGXUAN_MCP_ENABLE_PRIVILEGED_EXECUTION=true 进入真实提权模板。",
    ),
)

_WINDOWS_JEA_AGENT = ExecutionAgentProfile(
    profile_id="windows-jea-endpoint-v1",
    platform="windows",
    runtime_account="xingxuan-mcp-ops constrained endpoint",
    deployment_state="reference_only",
    can_execute_privileged_templates=False,
    summary="Windows PowerShell JEA 受限端点档案草案，当前仅用于说明服务、防火墙和 ACL 模板边界。",
    allowed_template_ids=(
        "TPL_SERVICE_RESTART_V1",
        "TPL_PROCESS_STOP_V1",
        "TPL_PERMISSION_CHANGE_V1",
        "TPL_PACKAGE_MANAGE_V1",
        "TPL_NETWORK_POLICY_V1",
    ),
    denied_capabilities=(
        "Invoke-Expression",
        "arbitrary_powershell_command",
        "administrator_default_runtime",
        "unbounded_filesystem_write",
    ),
    controls=(
        "jea_visible_functions_only",
        "fixed_template_only",
        "parameter_allowlist",
        "approval_scope_hash_required",
        "audit_trace_required",
    ),
    notes=(
        "该档案是后续 Windows JEA 实机验证入口，不代表当前 Windows 已放开真实提权动作。",
    ),
)

PREDEFINED_AGENT_PROFILES: dict[str, ExecutionAgentProfile] = {
    _LINUX_KYLIN_OPS_AGENT.profile_id: _LINUX_KYLIN_OPS_AGENT,
    _WINDOWS_JEA_AGENT.profile_id: _WINDOWS_JEA_AGENT,
}


def list_execution_agent_profiles(platform_hint: str = "auto") -> list[dict[str, Any]]:
    platform_filter = (platform_hint or "auto").strip().lower()
    profiles = list(PREDEFINED_AGENT_PROFILES.values())
    if platform_filter in {"linux", "windows"}:
        profiles = [profile for profile in profiles if profile.platform == platform_filter]
    return [profile.to_dict() for profile in profiles]


def get_execution_agent_profile(profile_id: str) -> ExecutionAgentProfile | None:
    return PREDEFINED_AGENT_PROFILES.get((profile_id or "").strip())


def resolve_execution_agent_profile(profile_id: str | None) -> ExecutionAgentProfile | None:
    if not profile_id:
        return None
    return get_execution_agent_profile(profile_id)


def validate_agent_profile_for_template(
    *,
    profile: ExecutionAgentProfile | None,
    template_id: str | None,
    action: str | None = None,
    platform_name: str,
    params: dict[str, Any] | None = None,
    runtime_identity: str,
    trusted_identities: set[str],
) -> tuple[bool, list[str], list[str], dict[str, Any]]:
    request = ExecutionAgentRequest(
        template_id=template_id or "",
        action=action or "",
        platform=platform_name,
        target="local",
        params=params,
        profile_id=profile.profile_id if profile else None,
    )
    preflight = ReferenceExecutionAgentAdapter(profile).preflight(
        request,
        runtime_identity=runtime_identity,
        trusted_identities=trusted_identities,
    )
    checks: dict[str, Any] = {
        "required": True,
        "configured": profile is not None,
        "profile": profile.to_dict() if profile else None,
        "template_id": template_id,
        "platform": platform_name,
        "runtime_identity": runtime_identity,
        "adapter_preflight": preflight.to_dict(),
    }
    if profile is None:
        errors = ["execution_agent_profile_missing"]
        warnings = ["请先配置 XINGXUAN_MCP_EXECUTION_AGENT_PROFILE，并完成受限 ops-agent/sudoers 或 Windows JEA 部署验证。"]
        for error in preflight.errors:
            if error not in errors:
                errors.append(error)
        for warning in preflight.warnings:
            if warning not in warnings:
                warnings.append(warning)
        return False, errors, warnings, checks

    errors: list[str] = []
    warnings: list[str] = []
    if not profile.supports_platform(platform_name):
        errors.append(
            f"execution_agent_profile_platform_mismatch: profile={profile.profile_id}, "
            f"profile_platform={profile.platform}, requested_platform={platform_name}"
        )
    if not profile.supports_template(template_id):
        errors.append(f"execution_agent_template_not_allowed: profile={profile.profile_id}, template_id={template_id}")
    if not profile.can_execute_privileged_templates or profile.deployment_state != "deployed":
        errors.append(
            f"execution_agent_profile_not_deployed: profile={profile.profile_id}, state={profile.deployment_state}"
        )
        warnings.append("当前档案仍是 reference_only，不声明目标主机已安装受限执行代理。")
    if not profile.identity_matches(runtime_identity, trusted_identities):
        errors.append(
            f"runtime_identity_not_profile_account: current={runtime_identity}, expected={profile.runtime_account}"
        )
        warnings.append("真实执行应由受限代理身份运行，或通过 XINGXUAN_MCP_TRUSTED_EXECUTION_IDENTITIES 显式列入受信身份。")

    for error in preflight.errors:
        if error not in errors:
            errors.append(error)
    for warning in preflight.warnings:
        if warning not in warnings:
            warnings.append(warning)

    return not errors, errors, warnings, checks


def _get_template_by_id(template_id: str) -> Any | None:
    return next((template for template in ACTION_TEMPLATES.values() if template.template_id == template_id), None)


def _find_denied_request_keys(value: Any, *, prefix: str = "params", depth: int = 0) -> list[str]:
    if depth > 4:
        return []
    findings: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            key_path = f"{prefix}.{key_text}"
            if key_text.strip().lower() in DENIED_AGENT_REQUEST_KEYS:
                findings.append(key_path)
            findings.extend(_find_denied_request_keys(child, prefix=key_path, depth=depth + 1))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(_find_denied_request_keys(child, prefix=f"{prefix}[{index}]", depth=depth + 1))
    return findings
