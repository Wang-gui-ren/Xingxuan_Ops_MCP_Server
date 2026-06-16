from __future__ import annotations

import json
import os
from collections.abc import Callable
from typing import Any

from mcp.server.fastmcp import FastMCP

from mcp_ops_server.approvals import ApprovalStore, build_approval_scope_hash
from mcp_ops_server.audit import AuditEvent, AuditLogger, summarize_result
from mcp_ops_server.branding import get_prefixed_env
from mcp_ops_server.execution import (
    ExecutionPolicy,
    ExecutionProxy,
    get_execution_agent_profile,
    get_action_template,
    list_execution_agent_profiles,
    list_action_templates,
)
from mcp_ops_server.execution.agents.contracts import synchronize_remote_reference_bundle
from mcp_ops_server.guardrails import ExternalGuardContext, OperationContext, validate_intent
from mcp_ops_server.models import ToolEnvelope
from mcp_ops_server.presentation import (
    attach_human_report,
    build_action_templates_report,
    build_execution_agent_profiles_report,
    build_execution_report,
)
from mcp_ops_server.tracing import build_trace_context


def register_execution_tools(
    mcp: FastMCP,
    proxy: ExecutionProxy | None = None,
    audit_logger: AuditLogger | None = None,
    approval_store: ApprovalStore | None = None,
    execution_policy: ExecutionPolicy | None = None,
) -> None:
    """注册写操作申请工具。

    这一组工具统一走 `ExecutionProxy` 的固定模板，不暴露任意 shell。
    当前版本默认 `dry_run=True`，后续安全意图校验、审批和审计也应在这里接入。
    """

    proxy = proxy or ExecutionProxy()
    audit_logger = audit_logger or AuditLogger()
    approval_store = approval_store or ApprovalStore()
    execution_policy = execution_policy or ExecutionPolicy()

    @mcp.tool()
    def get_execution_action_templates_tool(action: str | None = None, platform_hint: str = "auto") -> dict:
        """查询写操作固定模板和最小权限声明。

        这是只读工具，用于让 AstrBot/评委看到每类写操作被哪些权限、路径和回滚策略约束。
        """
        platform_filter = platform_hint.strip().lower() if platform_hint else "auto"
        if action:
            template = get_action_template(action)
            if template is None:
                return ToolEnvelope(
                    ok=False,
                    risk_level="low",
                    summary=f"Execution action template not found: {action}.",
                    data={"action": action, "available_actions": [item["action"] for item in list_action_templates()]},
                ).model_dump()
            templates = [template.to_dict()]
        else:
            templates = list_action_templates()

        if platform_filter in {"linux", "windows"}:
            templates = [item for item in templates if platform_filter in item.get("platforms", [])]

        result = ToolEnvelope(
            risk_level="low",
            summary=f"Returned {len(templates)} execution action template(s).",
            data={
                "templates": templates,
                "count": len(templates),
                "platform_filter": platform_filter,
                "safety_boundary": "fixed_template_only_no_arbitrary_shell",
            },
            next_actions=[
                "Use request_* tools with dry_run=true to generate a concrete plan from a template.",
                "Real execution still requires guardrail approval and audit logging.",
            ],
        ).model_dump()
        return attach_human_report(result, build_action_templates_report(templates, platform_filter))

    @mcp.tool()
    def get_execution_agent_profiles_tool(profile_id: str | None = None, platform_hint: str = "auto") -> dict:
        """查询受限执行代理能力档案。

        这是只读工具，用于展示 Linux/麒麟 ops-agent 和 Windows JEA 的部署边界。
        """
        platform_filter = platform_hint.strip().lower() if platform_hint else "auto"
        if profile_id:
            profile = get_execution_agent_profile(profile_id)
            if profile is None:
                return ToolEnvelope(
                    ok=False,
                    risk_level="low",
                    summary=f"Execution agent profile not found: {profile_id}.",
                    data={
                        "profile_id": profile_id,
                        "available_profiles": [
                            item["profile_id"] for item in list_execution_agent_profiles(platform_hint="auto")
                        ],
                    },
                ).model_dump()
            profiles = [profile.to_dict()]
        else:
            profiles = list_execution_agent_profiles(platform_hint=platform_filter)

        result = ToolEnvelope(
            risk_level="low",
            summary=f"Returned {len(profiles)} execution agent profile(s).",
            data={
                "profiles": profiles,
                "count": len(profiles),
                "platform_filter": platform_filter,
                "configured_profile": get_prefixed_env("TMP_MCP_EXECUTION_AGENT_PROFILE"),
                "safety_boundary": "profile_metadata_only_no_arbitrary_shell",
            },
            next_actions=[
                "部署真实代理前，保持 deployment_state=reference_only 且不要开启提权模板执行。",
                "真实执行仍必须经过 guardrail、approval、ExecutionPolicy 和 audit trace。",
            ],
        ).model_dump()
        return attach_human_report(result, build_execution_agent_profiles_report(profiles, platform_filter))

    def guarded_execute(
        *,
        tool_name: str,
        operation: str,
        params: dict[str, Any],
        executor: Callable[[], ToolEnvelope],
    ) -> dict:
        trace = build_trace_context(session_id=params.get("session_id"), trace_id=params.get("trace_id"))
        params = dict(params)
        params["session_id"] = trace.session_id
        params["trace_id"] = trace.trace_id
        context = OperationContext(
            tool_name=tool_name,
            operation=operation,
            user_intent=params.get("reason"),
            target=str(params.get("target") or "local"),
            platform_hint=str(params.get("platform_hint") or "auto"),
            params=params,
            path=_extract_path(params),
            dry_run=bool(params.get("dry_run", True)),
            approval_id=params.get("approval_id"),
            session_id=trace.session_id,
            trace_id=trace.trace_id,
            external_guard=ExternalGuardContext.from_dict(params.get("guard_context")),
        )
        decision = validate_intent(context)
        audit_logger.append(
            AuditEvent(
                event_type="guardrail_decision",
                tool_name=tool_name,
                session_id=context.session_id,
                trace_id=context.trace_id,
                risk_level=decision.risk_level,
                decision=decision.decision,
                params_summary=context.to_dict(),
                result_summary=decision.to_dict(),
            )
        )
        if not decision.allowed:
            result = ToolEnvelope(
                ok=False,
                risk_level=decision.risk_level,
                summary=decision.summary,
                data={
                    "operation": operation,
                    "guardrail_decision": decision.to_dict(),
                    "blocked": True,
                    "trace": trace.to_dict(),
                    "trace_id": trace.trace_id,
                    "session_id": trace.session_id,
                    "approval_hint": {
                        "tool_name": tool_name,
                        "operation": operation,
                        "target": str(context.target),
                        "risk_level": decision.risk_level,
                        "trace_id": trace.trace_id,
                        "session_id": trace.session_id,
                    },
                },
                next_actions=[
                    *decision.safe_alternatives,
                    "向用户展示操作摘要，获得明确确认后调用 request_inline_approval_tool 完成内联审批，再用返回的 approval_id 重试。",
                ],
            ).model_dump()
            attach_human_report(result, build_execution_report(tool_name=tool_name, operation=operation, envelope=result))
            audit_logger.append(
                AuditEvent(
                    event_type="tool_result",
                    tool_name=tool_name,
                    session_id=context.session_id,
                    trace_id=context.trace_id,
                    risk_level=decision.risk_level,
                    decision=decision.decision,
                    params_summary=context.to_dict(),
                    result_summary=summarize_result(result),
                    error=result.get("summary"),
                )
            )
            return result

        approval_validation = None
        if not context.dry_run and context.approval_id:
            approval_validation = approval_store.validate_approval(
                approval_id=context.approval_id,
                tool_name=tool_name,
                operation=operation,
                target=context.target,
                params=params,
            )
            if not approval_validation.ok:
                result = ToolEnvelope(
                    ok=False,
                    risk_level="high",
                    summary=approval_validation.summary,
                    data={
                        "operation": operation,
                        "guardrail_decision": decision.to_dict(),
                        "approval_validation": approval_validation.to_dict(),
                        "blocked": True,
                        "trace": trace.to_dict(),
                        "trace_id": trace.trace_id,
                        "session_id": trace.session_id,
                    },
                    next_actions=[
                        "调用 request_operation_approval_tool 创建审批申请。",
                        "调用 record_operation_approval_tool 记录 grant 后再执行真实动作。",
                    ],
                ).model_dump()
                attach_human_report(result, build_execution_report(tool_name=tool_name, operation=operation, envelope=result))
                audit_logger.append(
                    AuditEvent(
                        event_type="tool_result",
                        tool_name=tool_name,
                        session_id=context.session_id,
                        trace_id=context.trace_id,
                        risk_level="high",
                        decision="approval_validation_failed",
                        params_summary=context.to_dict(),
                        result_summary=summarize_result(result),
                        error=result.get("summary"),
                    )
                )
                return result

        execution_validation = None
        if not context.dry_run:
            execution_validation = execution_policy.validate(
                tool_name=tool_name,
                operation=operation,
                target=context.target,
                platform_hint=context.platform_hint,
                params=params,
                dry_run=context.dry_run,
                approval_validation=approval_validation,
            )
            audit_logger.append(
                AuditEvent(
                    event_type="execution_validation",
                    tool_name=tool_name,
                    session_id=context.session_id,
                    trace_id=context.trace_id,
                    risk_level=execution_validation.risk_level,
                    decision=execution_validation.decision,
                    params_summary=context.to_dict(),
                    result_summary=execution_validation.to_dict(),
                    error=None if execution_validation.ok else execution_validation.summary,
                )
            )
            if not execution_validation.ok:
                result = ToolEnvelope(
                    ok=False,
                    risk_level=execution_validation.risk_level,
                    summary=execution_validation.summary,
                    data={
                        "operation": operation,
                        "guardrail_decision": decision.to_dict(),
                        "approval_validation": approval_validation.to_dict() if approval_validation else None,
                        "execution_validation": execution_validation.to_dict(),
                        "blocked": True,
                        "trace": trace.to_dict(),
                        "trace_id": trace.trace_id,
                        "session_id": trace.session_id,
                    },
                    next_actions=[
                        "先确认 data.execution_validation.errors 中的阻断原因。",
                        "需要提权的真实动作必须先部署 Linux ops-agent/sudoers allowlist 或 Windows JEA。",
                        "如只是演示或排查，请保持 dry_run=true 生成计划，不要真实修改系统。",
                    ],
                ).model_dump()
                attach_human_report(result, build_execution_report(tool_name=tool_name, operation=operation, envelope=result))
                audit_logger.append(
                    AuditEvent(
                        event_type="tool_result",
                        tool_name=tool_name,
                        session_id=context.session_id,
                        trace_id=context.trace_id,
                        risk_level=execution_validation.risk_level,
                        decision="execution_validation_failed",
                        params_summary=context.to_dict(),
                        result_summary=summarize_result(result),
                        error=result.get("summary"),
                    )
                )
                return result

        result = executor().model_dump()
        result.setdefault("data", {})
        if isinstance(result["data"], dict):
            result["data"]["guardrail_decision"] = decision.to_dict()
            if approval_validation:
                result["data"]["approval_validation"] = approval_validation.to_dict()
            if execution_validation:
                result["data"]["execution_validation"] = execution_validation.to_dict()
            result["data"]["trace"] = trace.to_dict()
            result["data"]["trace_id"] = trace.trace_id
            result["data"]["session_id"] = trace.session_id
            if decision.requires_approval and context.dry_run and result.get("ok", False):
                approval_payload = _build_approval_request_payload(
                    tool_name=tool_name,
                    operation=operation,
                    target=context.target,
                    risk_level=decision.risk_level,
                    params=params,
                    plan=result["data"].get("plan"),
                    reason=context.user_intent,
                    session_id=trace.session_id,
                    trace_id=trace.trace_id,
                )
                result["data"]["approval_request"] = approval_payload
                result["data"]["approval_scope_hash"] = build_approval_scope_hash(
                    tool_name,
                    operation,
                    context.target,
                    approval_payload["params"],
                )
                result["data"]["execute_after_approval"] = {
                    "tool_name": tool_name,
                    "params": _build_execute_after_approval_params(params),
                }
            _synchronize_remote_reference_bundle(
                result,
                tool_name=tool_name,
                operation=operation,
                target=context.target,
            )
        if decision.requires_approval:
            result["summary"] = f"{result.get('summary', '')} Guardrail: {decision.summary}".strip()
            result.setdefault("next_actions", [])
            result["next_actions"] = list(result["next_actions"]) + [
                "复制 data.approval_request 调用 request_operation_approval_tool 创建审批申请。",
                "审批通过后，将 approval_id 填入 data.execute_after_approval.params 再执行真实固定模板。",
            ] + decision.safe_alternatives
        attach_human_report(result, build_execution_report(tool_name=tool_name, operation=operation, envelope=result))
        audit_logger.append(
            AuditEvent(
                event_type="tool_result",
                tool_name=tool_name,
                session_id=context.session_id,
                trace_id=context.trace_id,
                risk_level=result.get("risk_level", decision.risk_level),
                decision=decision.decision,
                params_summary=context.to_dict(),
                result_summary=summarize_result(result),
                error=None if result.get("ok", False) else result.get("summary"),
            )
        )
        return result

    @mcp.tool()
    def request_create_directory(
        path: str,
        create_parents: bool = True,
        target: str = "local",
        platform_hint: str = "auto",
        remote_username: str | None = None,
        remote_port: int | None = None,
        remote_auth_ref: str | None = None,
        remote_endpoint: str | None = None,
        dry_run: bool = True,
        reason: str | None = None,
        approval_id: str | None = None,
        session_id: str | None = None,
        trace_id: str | None = None,
        guard_context: dict[str, Any] | None = None,
    ) -> dict:
        params = _tool_params(locals())
        return guarded_execute(
            tool_name="request_create_directory",
            operation="create_directory",
            params=params,
            executor=lambda: proxy.request_create_directory(
                path=path,
                create_parents=create_parents,
                target=target,
                platform_hint=platform_hint,
                remote_username=remote_username,
                remote_port=remote_port,
                remote_auth_ref=remote_auth_ref,
                remote_endpoint=remote_endpoint,
                dry_run=dry_run,
                reason=reason,
                approval_id=approval_id,
            ),
        )

    @mcp.tool()
    def request_create_file(
        path: str,
        content: str = "",
        overwrite_if_exists: bool = False,
        create_parents: bool = False,
        target: str = "local",
        platform_hint: str = "auto",
        remote_username: str | None = None,
        remote_port: int | None = None,
        remote_auth_ref: str | None = None,
        remote_endpoint: str | None = None,
        dry_run: bool = True,
        reason: str | None = None,
        approval_id: str | None = None,
        session_id: str | None = None,
        trace_id: str | None = None,
        guard_context: dict[str, Any] | None = None,
    ) -> dict:
        params = _tool_params(locals())
        return guarded_execute(
            tool_name="request_create_file",
            operation="create_file",
            params=params,
            executor=lambda: proxy.request_create_file(
                path=path,
                content=content,
                overwrite_if_exists=overwrite_if_exists,
                create_parents=create_parents,
                target=target,
                platform_hint=platform_hint,
                remote_username=remote_username,
                remote_port=remote_port,
                remote_auth_ref=remote_auth_ref,
                remote_endpoint=remote_endpoint,
                dry_run=dry_run,
                reason=reason,
                approval_id=approval_id,
            ),
        )

    @mcp.tool()
    def request_modify_file(
        path: str,
        operation: str,
        content: str,
        match: str | None = None,
        backup: bool = True,
        target: str = "local",
        platform_hint: str = "auto",
        remote_username: str | None = None,
        remote_port: int | None = None,
        remote_auth_ref: str | None = None,
        remote_endpoint: str | None = None,
        dry_run: bool = True,
        reason: str | None = None,
        approval_id: str | None = None,
        session_id: str | None = None,
        trace_id: str | None = None,
        guard_context: dict[str, Any] | None = None,
    ) -> dict:
        params = _tool_params(locals())
        return guarded_execute(
            tool_name="request_modify_file",
            operation="modify_file",
            params=params,
            executor=lambda: proxy.request_modify_file(
                path=path,
                operation=operation,
                content=content,
                match=match,
                backup=backup,
                target=target,
                platform_hint=platform_hint,
                remote_username=remote_username,
                remote_port=remote_port,
                remote_auth_ref=remote_auth_ref,
                remote_endpoint=remote_endpoint,
                dry_run=dry_run,
                reason=reason,
                approval_id=approval_id,
            ),
        )

    @mcp.tool()
    def request_delete_file(
        path: str,
        mode: str = "quarantine",
        recursive: bool = False,
        target: str = "local",
        platform_hint: str = "auto",
        remote_username: str | None = None,
        remote_port: int | None = None,
        remote_auth_ref: str | None = None,
        remote_endpoint: str | None = None,
        dry_run: bool = True,
        reason: str | None = None,
        approval_id: str | None = None,
        session_id: str | None = None,
        trace_id: str | None = None,
        guard_context: dict[str, Any] | None = None,
    ) -> dict:
        params = _tool_params(locals())
        return guarded_execute(
            tool_name="request_delete_file",
            operation="delete_file",
            params=params,
            executor=lambda: proxy.request_delete_file(
                path=path,
                mode=mode,
                recursive=recursive,
                target=target,
                platform_hint=platform_hint,
                remote_username=remote_username,
                remote_port=remote_port,
                remote_auth_ref=remote_auth_ref,
                remote_endpoint=remote_endpoint,
                dry_run=dry_run,
                reason=reason,
                approval_id=approval_id,
            ),
        )

    @mcp.tool()
    def request_purge_quarantine_entry(
        path: str,
        recursive: bool = False,
        target: str = "local",
        platform_hint: str = "auto",
        remote_username: str | None = None,
        remote_port: int | None = None,
        remote_auth_ref: str | None = None,
        remote_endpoint: str | None = None,
        dry_run: bool = True,
        reason: str | None = None,
        approval_id: str | None = None,
        session_id: str | None = None,
        trace_id: str | None = None,
        guard_context: dict[str, Any] | None = None,
    ) -> dict:
        params = _tool_params(locals())
        return guarded_execute(
            tool_name="request_purge_quarantine_entry",
            operation="purge_quarantine_entry",
            params=params,
            executor=lambda: proxy.request_purge_quarantine_entry(
                path=path,
                recursive=recursive,
                target=target,
                platform_hint=platform_hint,
                remote_username=remote_username,
                remote_port=remote_port,
                remote_auth_ref=remote_auth_ref,
                remote_endpoint=remote_endpoint,
                dry_run=dry_run,
                reason=reason,
                approval_id=approval_id,
            ),
        )

    @mcp.tool()
    def request_restart_service(
        service: str,
        target: str = "local",
        platform_hint: str = "auto",
        remote_username: str | None = None,
        remote_port: int | None = None,
        remote_auth_ref: str | None = None,
        remote_endpoint: str | None = None,
        dry_run: bool = True,
        reason: str | None = None,
        approval_id: str | None = None,
        timeout_seconds: int = 60,
        session_id: str | None = None,
        trace_id: str | None = None,
        guard_context: dict[str, Any] | None = None,
    ) -> dict:
        params = _tool_params(locals())
        return guarded_execute(
            tool_name="request_restart_service",
            operation="restart_service",
            params=params,
            executor=lambda: proxy.request_restart_service(
                service=service,
                target=target,
                platform_hint=platform_hint,
                remote_username=remote_username,
                remote_port=remote_port,
                remote_auth_ref=remote_auth_ref,
                remote_endpoint=remote_endpoint,
                dry_run=dry_run,
                reason=reason,
                approval_id=approval_id,
                timeout_seconds=timeout_seconds,
            ),
        )

    @mcp.tool()
    def request_stop_process(
        pid: int,
        process_name: str | None = None,
        signal_name: str = "terminate",
        target: str = "local",
        platform_hint: str = "auto",
        remote_username: str | None = None,
        remote_port: int | None = None,
        remote_auth_ref: str | None = None,
        remote_endpoint: str | None = None,
        dry_run: bool = True,
        reason: str | None = None,
        approval_id: str | None = None,
        timeout_seconds: int = 10,
        session_id: str | None = None,
        trace_id: str | None = None,
        guard_context: dict[str, Any] | None = None,
    ) -> dict:
        params = _tool_params(locals())
        return guarded_execute(
            tool_name="request_stop_process",
            operation="stop_process",
            params=params,
            executor=lambda: proxy.request_stop_process(
                pid=pid,
                process_name=process_name,
                signal_name=signal_name,
                target=target,
                platform_hint=platform_hint,
                remote_username=remote_username,
                remote_port=remote_port,
                remote_auth_ref=remote_auth_ref,
                remote_endpoint=remote_endpoint,
                dry_run=dry_run,
                reason=reason,
                approval_id=approval_id,
                timeout_seconds=timeout_seconds,
            ),
        )

    @mcp.tool()
    def request_change_permissions(
        path: str,
        mode: str | None = None,
        owner: str | None = None,
        group: str | None = None,
        recursive: bool = False,
        target: str = "local",
        platform_hint: str = "auto",
        remote_username: str | None = None,
        remote_port: int | None = None,
        remote_auth_ref: str | None = None,
        remote_endpoint: str | None = None,
        dry_run: bool = True,
        reason: str | None = None,
        approval_id: str | None = None,
        timeout_seconds: int = 60,
        session_id: str | None = None,
        trace_id: str | None = None,
        guard_context: dict[str, Any] | None = None,
    ) -> dict:
        params = _tool_params(locals())
        return guarded_execute(
            tool_name="request_change_permissions",
            operation="change_permissions",
            params=params,
            executor=lambda: proxy.request_change_permissions(
                path=path,
                mode=mode,
                owner=owner,
                group=group,
                recursive=recursive,
                target=target,
                platform_hint=platform_hint,
                remote_username=remote_username,
                remote_port=remote_port,
                remote_auth_ref=remote_auth_ref,
                remote_endpoint=remote_endpoint,
                dry_run=dry_run,
                reason=reason,
                approval_id=approval_id,
                timeout_seconds=timeout_seconds,
            ),
        )

    @mcp.tool()
    def request_manage_package(
        package: str,
        action: str,
        manager: str = "auto",
        version: str | None = None,
        target: str = "local",
        platform_hint: str = "auto",
        remote_username: str | None = None,
        remote_port: int | None = None,
        remote_auth_ref: str | None = None,
        remote_endpoint: str | None = None,
        dry_run: bool = True,
        reason: str | None = None,
        approval_id: str | None = None,
        timeout_seconds: int = 300,
        session_id: str | None = None,
        trace_id: str | None = None,
        guard_context: dict[str, Any] | None = None,
    ) -> dict:
        params = _tool_params(locals())
        return guarded_execute(
            tool_name="request_manage_package",
            operation="manage_package",
            params=params,
            executor=lambda: proxy.request_manage_package(
                package=package,
                action=action,
                manager=manager,
                version=version,
                target=target,
                platform_hint=platform_hint,
                remote_username=remote_username,
                remote_port=remote_port,
                remote_auth_ref=remote_auth_ref,
                remote_endpoint=remote_endpoint,
                dry_run=dry_run,
                reason=reason,
                approval_id=approval_id,
                timeout_seconds=timeout_seconds,
            ),
        )

    @mcp.tool()
    def request_network_policy_change(
        action: str,
        protocol: str,
        port: int,
        source: str = "",
        rule_name: str | None = None,
        target: str = "local",
        platform_hint: str = "auto",
        remote_username: str | None = None,
        remote_port: int | None = None,
        remote_auth_ref: str | None = None,
        remote_endpoint: str | None = None,
        dry_run: bool = True,
        reason: str | None = None,
        approval_id: str | None = None,
        timeout_seconds: int = 60,
        session_id: str | None = None,
        trace_id: str | None = None,
        guard_context: dict[str, Any] | None = None,
    ) -> dict:
        params = _tool_params(locals())
        return guarded_execute(
            tool_name="request_network_policy_change",
            operation="network_policy_change",
            params=params,
            executor=lambda: proxy.request_network_policy_change(
                action=action,
                protocol=protocol,
                port=port,
                source=source,
                rule_name=rule_name,
                target=target,
                platform_hint=platform_hint,
                remote_username=remote_username,
                remote_port=remote_port,
                remote_auth_ref=remote_auth_ref,
                remote_endpoint=remote_endpoint,
                dry_run=dry_run,
                reason=reason,
                approval_id=approval_id,
                timeout_seconds=timeout_seconds,
            ),
        )

    @mcp.tool()
    def request_log_cleanup(
        path: str,
        mode: str = "archive",
        target: str = "local",
        platform_hint: str = "auto",
        remote_username: str | None = None,
        remote_port: int | None = None,
        remote_auth_ref: str | None = None,
        remote_endpoint: str | None = None,
        dry_run: bool = True,
        reason: str | None = None,
        approval_id: str | None = None,
        session_id: str | None = None,
        trace_id: str | None = None,
        guard_context: dict[str, Any] | None = None,
    ) -> dict:
        params = _tool_params(locals())
        return guarded_execute(
            tool_name="request_log_cleanup",
            operation="log_cleanup",
            params=params,
            executor=lambda: proxy.request_log_cleanup(
                path=path,
                mode=mode,
                target=target,
                platform_hint=platform_hint,
                remote_username=remote_username,
                remote_port=remote_port,
                remote_auth_ref=remote_auth_ref,
                remote_endpoint=remote_endpoint,
                dry_run=dry_run,
                reason=reason,
                approval_id=approval_id,
            ),
        )


def _extract_path(params: dict[str, Any]) -> str | None:
    value = params.get("path") or params.get("log_path") or params.get("target_path")
    return str(value) if value else None


def _tool_params(local_vars: dict[str, Any]) -> dict[str, Any]:
    """只保留 MCP 工具的业务入参，避免闭包函数等对象进入审计 JSON。"""

    return {
        key: value
        for key, value in local_vars.items()
        if not key.startswith("_") and not callable(value) and _is_json_serializable(value)
    }


def _synchronize_remote_reference_bundle(
    result: dict[str, Any],
    *,
    tool_name: str,
    operation: str,
    target: str,
) -> None:
    data = result.get("data")
    if not isinstance(data, dict):
        return
    remote_execution = data.get("remote_execution")
    if not isinstance(remote_execution, dict):
        return
    synchronized = synchronize_remote_reference_bundle(
        remote_execution,
        tool_name=tool_name,
        operation=operation,
        target=target,
        approval_id=data.get("approval_id"),
        approval_scope_hash=data.get("approval_scope_hash"),
        approval_request=data.get("approval_request") if isinstance(data.get("approval_request"), dict) else None,
        trace_id=data.get("trace_id"),
        session_id=data.get("session_id"),
    )
    if data.get("approval_scope_hash") is None:
        approval_binding = synchronized.get("approval_binding")
        if isinstance(approval_binding, dict) and approval_binding.get("scope_hash"):
            data["approval_scope_hash"] = approval_binding.get("scope_hash")


def _build_approval_request_payload(
    *,
    tool_name: str,
    operation: str,
    target: str,
    risk_level: str,
    params: dict[str, Any],
    plan: Any,
    reason: str | None,
    session_id: str | None,
    trace_id: str | None,
) -> dict[str, Any]:
    """生成可直接传给 request_operation_approval_tool 的参数包。"""

    return {
        "tool_name": tool_name,
        "operation": operation,
        "target": target,
        "params": _strip_none_values(params),
        "plan": plan if isinstance(plan, dict) else {},
        "risk_level": risk_level,
        "requester": "astrbot",
        "reason": reason or f"Approve {tool_name}.{operation} fixed-template execution.",
        "expires_in_minutes": 60,
        "session_id": session_id,
        "trace_id": trace_id,
    }


def _build_execute_after_approval_params(params: dict[str, Any]) -> dict[str, Any]:
    payload = _strip_none_values(params)
    payload["dry_run"] = False
    payload["approval_id"] = "<填入 record_operation_approval_tool 返回的 approval_id>"
    return payload


def _strip_none_values(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}


def _is_json_serializable(value: Any) -> bool:
    try:
        json.dumps(value, ensure_ascii=False)
        return True
    except (TypeError, ValueError):
        return False
