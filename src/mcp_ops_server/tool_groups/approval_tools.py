from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from mcp_ops_server.approvals import (
    ApprovalStore,
    approval_identity_required,
    create_approval_anchor,
    create_approval_decision_token,
    enterprise_approval_token_issuer_enabled,
    verify_approval_anchor,
    verify_approval_chain,
    verify_approval_decision_token,
    verify_enterprise_identity_assertion,
)
from mcp_ops_server.audit import AuditEvent, AuditLogger
from mcp_ops_server.branding import WEB_GATEWAY_NAME
from mcp_ops_server.config import load_approval_identity_config
from mcp_ops_server.models import ToolEnvelope
from mcp_ops_server.presentation import attach_human_report, build_human_report
from mcp_ops_server.tracing import build_trace_context
from mcp_ops_server.web import build_approval_console_bundle


def register_approval_tools(
    mcp: FastMCP,
    approval_store: ApprovalStore | None = None,
    audit_logger: AuditLogger | None = None,
) -> None:
    """注册审批事件模型工具。"""

    approval_store = approval_store or ApprovalStore()
    audit_logger = audit_logger or AuditLogger()

    @mcp.tool()
    def request_operation_approval_tool(
        tool_name: str,
        operation: str,
        target: str = "local",
        params: dict[str, Any] | None = None,
        plan: dict[str, Any] | None = None,
        risk_level: str = "high",
        requester: str | None = None,
        reason: str | None = None,
        expires_in_minutes: int = 60,
        session_id: str | None = None,
        trace_id: str | None = None,
    ) -> dict:
        """创建审批申请。该工具只写审批账本，不执行运维动作。"""

        trace = build_trace_context(session_id=session_id, trace_id=trace_id)
        try:
            record = approval_store.request_approval(
                tool_name=tool_name,
                operation=operation,
                target=target,
                params=params or {},
                plan=plan or {},
                risk_level=risk_level,
                requester=requester,
                reason=reason,
                expires_in_minutes=expires_in_minutes,
                trace_id=trace.trace_id,
                session_id=trace.session_id,
            )
        except Exception as exc:
            audit_logger.append(
                AuditEvent(
                    event_type="approval_policy_denied",
                    tool_name=tool_name,
                    session_id=trace.session_id,
                    trace_id=trace.trace_id,
                    risk_level=risk_level if risk_level in {"low", "medium", "high", "critical"} else "high",
                    decision="deny_request",
                    params_summary={"operation": operation, "target": target, "requester": requester},
                    result_summary={"error": str(exc)},
                    error=str(exc),
                )
            )
            result = ToolEnvelope(
                ok=False,
                risk_level=risk_level if risk_level in {"low", "medium", "high", "critical"} else "high",
                summary="审批申请被策略拒绝。",
                data={"error": str(exc), "trace": trace.to_dict(), "trace_id": trace.trace_id, "session_id": trace.session_id},
                next_actions=[
                    "不要尝试用 approval_id 绕过策略拒绝。",
                    "如确需处理，请由人工运维在 MCP 外部评估风险。",
                ],
            ).model_dump()
            return attach_human_report(
                result,
                build_human_report(
                    title="运维审批申请被策略拒绝",
                    conclusion=result["summary"],
                    risk_level=result["risk_level"],
                    evidence=[f"tool={tool_name}", f"operation={operation}", f"target={target}", f"error={exc}"],
                    risk_explanation="审批策略拒绝代表该请求不能进入普通审批流；critical 风险不能通过审批放行。",
                    safe_next_steps=result["next_actions"],
                    trace_id=trace.trace_id,
                    session_id=trace.session_id,
                    audit_hint="本次策略拒绝已写入 approval_policy_denied 审计事件。",
                ),
            )
        audit_logger.append(
            AuditEvent(
                event_type="approval_requested",
                tool_name=tool_name,
                session_id=trace.session_id,
                trace_id=trace.trace_id,
                risk_level=risk_level,
                decision="require_approval",
                params_summary={"operation": operation, "target": target, "requester": requester},
                result_summary=record.to_dict(),
            )
        )
        result = ToolEnvelope(
            ok=True,
            risk_level=record.risk_level if record.risk_level in {"low", "medium", "high", "critical"} else "high",
            summary=f"审批申请已创建：{record.approval_id}。",
            data={"approval": record.to_dict(), "approval_id": record.approval_id, "trace": trace.to_dict()},
            next_actions=[
                f"由审批人通道调用 record_operation_approval_tool 记录 grant 或 reject；需要 {record.required_approvals} 个有效审批。",
                "审批通过后，将 approval_id 传给对应 request_* 工具执行真实动作。",
            ],
        ).model_dump()
        return attach_human_report(
            result,
            _approval_report(
                title="运维审批申请已创建",
                conclusion=result["summary"],
                risk_level="high",
                approval=record.to_dict(),
                next_actions=result["next_actions"],
                trace_id=trace.trace_id,
                session_id=trace.session_id,
            ),
        )

    @mcp.tool()
    def record_operation_approval_tool(
        approval_id: str,
        decision: str,
        approver: str,
        comment: str | None = None,
        expires_in_minutes: int | None = None,
        approval_token: dict[str, Any] | str | None = None,
    ) -> dict:
        """记录审批结论，decision 支持 grant/reject。

        approval_token 是外部审批系统或 B/S 管理端签发的可选身份凭证。
        当 TMP_MCP_REQUIRE_APPROVAL_IDENTITY=true 时必须提供并通过校验。
        """

        try:
            current = approval_store.get_latest(approval_id)
            identity = verify_approval_decision_token(
                approval_token,
                approval_id=approval_id,
                decision=decision,
                approver=approver,
                approval_record=current.to_dict() if current else None,
            )
            if not identity.ok:
                audit_logger.append(
                    AuditEvent(
                        event_type="approval_identity_denied",
                        tool_name=current.tool_name if current else "record_operation_approval_tool",
                        session_id=current.session_id if current else None,
                        trace_id=current.trace_id if current else None,
                        risk_level=current.risk_level if current else "high",
                        decision="identity_denied",
                        params_summary={"approval_id": approval_id, "approver": approver, "enforced": identity.enforced},
                        result_summary=identity.to_dict(),
                        error="; ".join(identity.errors),
                    )
                )
                result = ToolEnvelope(
                    ok=False,
                    risk_level=current.risk_level if current and current.risk_level in {"low", "medium", "high", "critical"} else "high",
                    summary="审批身份凭证校验失败。",
                    data={
                        "approval_id": approval_id,
                        "identity_verification": identity.to_dict(),
                        "error": "; ".join(identity.errors),
                    },
                    next_actions=[
                        "由受信审批通道重新签发 approval_token。",
                        "不要在普通会话中伪造 approver 字符串或手工拼接签名。",
                    ],
                ).model_dump()
                return attach_human_report(
                    result,
                    build_human_report(
                        title="审批身份凭证校验失败",
                        conclusion=result["summary"],
                        risk_level=result["risk_level"],
                        ok=False,
                        evidence=[
                            f"approval_id={approval_id}",
                            f"approver={approver}",
                            f"identity_enforced={identity.enforced}",
                            f"errors={identity.errors}",
                        ],
                        risk_explanation="启用外部审批身份通道后，审批结论必须来自可验证签名凭证，不能只相信 approver 字符串。",
                        safe_next_steps=result["next_actions"],
                        trace_id=current.trace_id if current else None,
                        session_id=current.session_id if current else None,
                        audit_hint="本次失败已写入 approval_identity_denied 审计事件。",
                    ),
                )
            record = approval_store.record_decision(
                approval_id=approval_id,
                decision=decision,
                approver=approver,
                comment=comment,
                expires_in_minutes=expires_in_minutes,
                identity_claims=identity.to_history_identity(),
            )
            if identity.verified:
                audit_logger.append(
                    AuditEvent(
                        event_type="approval_identity_verified",
                        tool_name=record.tool_name,
                        session_id=record.session_id,
                        trace_id=record.trace_id,
                        risk_level=record.risk_level,
                        decision="identity_verified",
                        params_summary={"approval_id": approval_id, "approver": approver},
                        result_summary=identity.to_dict(),
                    )
                )
            if record.status == "granted":
                event_type = "approval_granted"
            elif record.status == "partially_granted":
                event_type = "approval_partially_granted"
            else:
                event_type = "approval_rejected"
            audit_logger.append(
                AuditEvent(
                    event_type=event_type,
                    tool_name=record.tool_name,
                    session_id=record.session_id,
                    trace_id=record.trace_id,
                    risk_level=record.risk_level,
                    decision=record.status,
                    params_summary={"approval_id": approval_id, "approver": approver},
                    result_summary=record.to_dict(),
                )
            )
            result = ToolEnvelope(
                ok=True,
                risk_level=record.risk_level if record.risk_level in {"low", "medium", "high", "critical"} else "high",
                summary=f"审批结果已记录：{record.approval_id} -> {record.status}。",
                data={
                    "approval": record.to_dict(),
                    "approval_id": record.approval_id,
                    "identity_verification": identity.to_dict(),
                },
                next_actions=_decision_next_actions(record.to_dict()),
            ).model_dump()
            return attach_human_report(
                result,
                _approval_report(
                    title="运维审批结果",
                    conclusion=result["summary"],
                    risk_level=result["risk_level"],
                    approval=record.to_dict(),
                    next_actions=result["next_actions"],
                    trace_id=record.trace_id,
                    session_id=record.session_id,
                ),
            )
        except Exception as exc:
            return ToolEnvelope(
                ok=False,
                risk_level="high",
                summary="记录审批结果失败。",
                data={"approval_id": approval_id, "error": str(exc)},
                next_actions=["确认 approval_id 是否存在，decision 是否为 grant 或 reject。"],
            ).model_dump()

    @mcp.tool()
    def request_inline_approval_tool(
        tool_name: str,
        operation: str,
        approver: str,
        decision: str = "grant",
        target: str = "local",
        params: dict[str, Any] | None = None,
        risk_level: str = "high",
        reason: str | None = None,
        trace_id: str | None = None,
        session_id: str | None = None,
    ) -> dict:
        """在 LLM 对话中完成内联审批闭环，一次调用完成"创建审批 + 记录决定"。

        适用场景：操作被护栏阻断后，LLM 向用户展示操作摘要并获得明确口头/文字确认，
        再调用本工具获得可用的 approval_id，然后将该 approval_id 传入对应 request_* 工具重试。

        使用规范：
        1. 必须先向用户展示 tool_name、operation、target、params 摘要
        2. 获得用户明确确认（"批准"、"同意"、"yes" 等）后才能调用
        3. approver 填写用户对话中提供的名称或标识
        4. 不得在未经用户确认的情况下自动调用本工具执行高风险操作
        """
        trace = build_trace_context(session_id=session_id, trace_id=trace_id)
        try:
            record = approval_store.request_approval(
                tool_name=tool_name,
                operation=operation,
                target=target,
                params=params or {},
                risk_level=risk_level,
                reason=reason,
                trace_id=trace.trace_id,
                session_id=trace.session_id,
            )
        except Exception as exc:
            return ToolEnvelope(
                ok=False,
                risk_level="high",
                summary=f"内联审批请求被策略拒绝：{exc}",
                data={"error": str(exc)},
                next_actions=["检查操作是否属于 critical 风险（无法通过审批放行）。"],
            ).model_dump()
        try:
            record = approval_store.record_decision(
                approval_id=record.approval_id,
                decision=decision,
                approver=approver,
                comment="inline approval via LLM conversation",
            )
        except Exception as exc:
            return ToolEnvelope(
                ok=False,
                risk_level="high",
                summary=f"内联审批决定记录失败：{exc}",
                data={"approval_id": record.approval_id, "error": str(exc)},
                next_actions=["调用 record_operation_approval_tool 手动记录决定。"],
            ).model_dump()
        audit_logger.append(
            AuditEvent(
                event_type="approval_inline_granted",
                tool_name=tool_name,
                session_id=trace.session_id,
                trace_id=trace.trace_id,
                risk_level=record.risk_level if record.risk_level in {"low", "medium", "high", "critical"} else "high",
                decision=record.status,
                params_summary={"operation": operation, "target": target, "approver": approver},
                result_summary={"approval_id": record.approval_id, "status": record.status},
            )
        )
        return ToolEnvelope(
            ok=True,
            risk_level=record.risk_level if record.risk_level in {"low", "medium", "high", "critical"} else "high",
            summary=f"内联审批已完成：{record.approval_id} → {record.status}。",
            data={
                "approval_id": record.approval_id,
                "status": record.status,
                "trace": trace.to_dict(),
            },
            next_actions=[
                f"将 approval_id={record.approval_id!r} 传入对应 request_* 工具，设置 dry_run=false 执行真实动作。",
            ],
        ).model_dump()

    @mcp.tool()
    def issue_enterprise_approval_token_tool(
        approval_id: str,
        decision: str,
        approver: str,
        enterprise_assertion: dict[str, Any] | str | None,
        expires_in_minutes: int = 15,
        comment: str | None = None,
    ) -> dict:
        """Issue an approval_token from a signed enterprise identity assertion.

        This tool does not record the approval decision. The returned token must
        still be passed to record_operation_approval_tool so the approval ledger
        can append the actual decision record.
        """

        current = approval_store.get_latest(approval_id)
        if current is None:
            result = ToolEnvelope(
                ok=False,
                risk_level="low",
                summary=f"Approval not found: {approval_id}.",
                data={"approval_id": approval_id},
                next_actions=["Create the approval request before issuing an enterprise approval token."],
            ).model_dump()
            return attach_human_report(
                result,
                build_human_report(
                    title="Enterprise Approval Token Issue Failed",
                    conclusion=result["summary"],
                    risk_level="low",
                    ok=False,
                    evidence=[f"approval_id={approval_id}"],
                    risk_explanation="A token can only be issued for an existing approval ledger record.",
                    safe_next_steps=result["next_actions"],
                ),
            )

        risk_level = current.risk_level if current.risk_level in {"low", "medium", "high", "critical"} else "high"
        if current.status not in {"requested", "partially_granted"}:
            audit_logger.append(
                AuditEvent(
                    event_type="approval_enterprise_identity_denied",
                    tool_name=current.tool_name,
                    session_id=current.session_id,
                    trace_id=current.trace_id,
                    risk_level=risk_level,
                    decision="approval_not_open",
                    params_summary={"approval_id": approval_id, "approver": approver, "status": current.status},
                    result_summary={"error": "approval is not open for decision"},
                    error="approval is not open for decision",
                )
            )
            result = ToolEnvelope(
                ok=False,
                risk_level=risk_level,
                summary=f"Approval is not open for decision: {current.status}.",
                data={"approval_id": approval_id, "status": current.status},
                next_actions=["Create a new dry-run plan and approval request if another change is still needed."],
            ).model_dump()
            return attach_human_report(
                result,
                build_human_report(
                    title="Enterprise Approval Token Issue Failed",
                    conclusion=result["summary"],
                    risk_level=result["risk_level"],
                    ok=False,
                    evidence=[f"approval_id={approval_id}", f"status={current.status}"],
                    risk_explanation="Closed approval records must not receive fresh decision tokens.",
                    safe_next_steps=result["next_actions"],
                    trace_id=current.trace_id,
                    session_id=current.session_id,
                    audit_hint="The denial was written as approval_enterprise_identity_denied.",
                ),
            )

        if _approval_is_expired(current.to_dict()):
            audit_logger.append(
                AuditEvent(
                    event_type="approval_enterprise_identity_denied",
                    tool_name=current.tool_name,
                    session_id=current.session_id,
                    trace_id=current.trace_id,
                    risk_level=risk_level,
                    decision="approval_expired",
                    params_summary={"approval_id": approval_id, "approver": approver, "expires_at": current.expires_at},
                    result_summary={"error": "approval expired before token issue"},
                    error="approval expired before token issue",
                )
            )
            result = ToolEnvelope(
                ok=False,
                risk_level=risk_level,
                summary="Approval expired before enterprise token issue.",
                data={"approval_id": approval_id, "expires_at": current.expires_at},
                next_actions=["Renew the approval when policy allows it, or create a new approval request."],
            ).model_dump()
            return attach_human_report(
                result,
                build_human_report(
                    title="Enterprise Approval Token Issue Failed",
                    conclusion=result["summary"],
                    risk_level=result["risk_level"],
                    ok=False,
                    evidence=[f"approval_id={approval_id}", f"expires_at={current.expires_at}"],
                    risk_explanation="Expired approvals cannot receive fresh decision tokens.",
                    safe_next_steps=result["next_actions"],
                    trace_id=current.trace_id,
                    session_id=current.session_id,
                    audit_hint="The denial was written as approval_enterprise_identity_denied.",
                ),
            )

        enterprise_identity = verify_enterprise_identity_assertion(
            enterprise_assertion,
            approval_id=approval_id,
            decision=decision,
            approver=approver,
        )
        if not enterprise_identity.ok:
            audit_logger.append(
                AuditEvent(
                    event_type="approval_enterprise_identity_denied",
                    tool_name=current.tool_name,
                    session_id=current.session_id,
                    trace_id=current.trace_id,
                    risk_level=risk_level,
                    decision="enterprise_identity_denied",
                    params_summary={"approval_id": approval_id, "approver": approver, "decision": decision},
                    result_summary=enterprise_identity.to_dict(),
                    error="; ".join(enterprise_identity.errors),
                )
            )
            result = ToolEnvelope(
                ok=False,
                risk_level=risk_level,
                summary="Enterprise identity assertion verification failed.",
                data={
                    "approval_id": approval_id,
                    "enterprise_identity_verification": enterprise_identity.to_dict(),
                    "error": "; ".join(enterprise_identity.errors),
                },
                next_actions=[
                    "Re-issue the assertion from the trusted enterprise identity bridge.",
                    "Check issuer allowlist, approver role, approval_id, decision, approver and assertion expiry.",
                ],
            ).model_dump()
            return attach_human_report(
                result,
                build_human_report(
                    title="Enterprise Identity Verification Failed",
                    conclusion=result["summary"],
                    risk_level=result["risk_level"],
                    ok=False,
                    evidence=[
                        f"approval_id={approval_id}",
                        f"approver={approver}",
                        f"decision={decision}",
                        f"errors={enterprise_identity.errors}",
                    ],
                    risk_explanation="The MCP approval server only signs approval tokens after a trusted enterprise assertion verifies.",
                    safe_next_steps=result["next_actions"],
                    trace_id=current.trace_id,
                    session_id=current.session_id,
                    audit_hint="The denial was written as approval_enterprise_identity_denied.",
                    details={"enterprise_identity_verification": enterprise_identity.to_dict()},
                ),
            )

        try:
            claims = enterprise_identity.claims
            approval_token = create_approval_decision_token(
                approval_id=approval_id,
                decision=decision,
                approver=approver,
                issuer=str(claims.get("issuer") or "enterprise-identity-bridge"),
                subject=str(claims.get("subject") or approver),
                key_id=str(claims.get("key_id") or "enterprise-hmac"),
                expires_in_minutes=expires_in_minutes,
                scope_hash=current.scope_hash,
                record_event_hash=current.event_hash,
            )
        except Exception as exc:
            audit_logger.append(
                AuditEvent(
                    event_type="approval_identity_token_issue_failed",
                    tool_name=current.tool_name,
                    session_id=current.session_id,
                    trace_id=current.trace_id,
                    risk_level=risk_level,
                    decision="token_issue_failed",
                    params_summary={"approval_id": approval_id, "approver": approver, "decision": decision},
                    result_summary={"error": str(exc)},
                    error=str(exc),
                )
            )
            result = ToolEnvelope(
                ok=False,
                risk_level=risk_level,
                summary="Approval identity token issue failed.",
                data={"approval_id": approval_id, "error": str(exc)},
                next_actions=["Configure TMP_MCP_APPROVAL_IDENTITY_SECRET before enabling enterprise token issue."],
            ).model_dump()
            return attach_human_report(
                result,
                build_human_report(
                    title="Approval Identity Token Issue Failed",
                    conclusion=result["summary"],
                    risk_level=result["risk_level"],
                    ok=False,
                    evidence=[f"approval_id={approval_id}", f"error={exc}"],
                    risk_explanation="The enterprise assertion was valid, but the approval token signing key was unavailable.",
                    safe_next_steps=result["next_actions"],
                    trace_id=current.trace_id,
                    session_id=current.session_id,
                    audit_hint="The failure was written as approval_identity_token_issue_failed.",
                ),
            )

        audit_logger.append(
            AuditEvent(
                event_type="approval_identity_token_issued",
                tool_name=current.tool_name,
                session_id=current.session_id,
                trace_id=current.trace_id,
                risk_level=risk_level,
                decision="token_issued",
                params_summary={"approval_id": approval_id, "approver": approver, "decision": decision},
                result_summary={
                    "approval_id": approval_id,
                    "approval_identity": _token_public_claims(approval_token),
                    "enterprise_identity": enterprise_identity.to_dict(),
                    "comment": comment,
                },
            )
        )
        result = ToolEnvelope(
            ok=True,
            risk_level=risk_level,
            summary="Enterprise identity verified and approval token issued.",
            data={
                "approval_id": approval_id,
                "approval": current.to_dict(),
                "approval_token": approval_token,
                "approval_identity_claims": _token_public_claims(approval_token),
                "enterprise_identity_verification": enterprise_identity.to_dict(),
            },
            next_actions=[
                "Pass approval_token to record_operation_approval_tool with the same approval_id, decision and approver.",
                "Do not store the raw approval_token in chat logs or audit summaries.",
            ],
        ).model_dump()
        return attach_human_report(
            result,
            build_human_report(
                title="Enterprise Approval Token Issued",
                conclusion=result["summary"],
                risk_level=result["risk_level"],
                evidence=[
                    f"approval_id={approval_id}",
                    f"approver={approver}",
                    f"decision={decision}",
                    f"issuer={enterprise_identity.claims.get('issuer')}",
                    f"subject={enterprise_identity.claims.get('subject')}",
                    f"scope_hash={current.scope_hash}",
                    f"record_event_hash={current.event_hash}",
                ],
                risk_explanation="The issued token is bound to the approval ledger record hash and scope hash.",
                safe_next_steps=result["next_actions"],
                trace_id=current.trace_id,
                session_id=current.session_id,
                audit_hint="Only public token claims were written to approval_identity_token_issued.",
                details={
                    "approval_identity_claims": _token_public_claims(approval_token),
                    "enterprise_identity": enterprise_identity.to_dict(),
                },
            ),
        )

    @mcp.tool()
    def get_operation_approval_tool(approval_id: str) -> dict:
        """查询单个审批记录的最新状态。"""

        record = approval_store.get_latest(approval_id)
        if record is None:
            return ToolEnvelope(
                ok=False,
                risk_level="low",
                summary=f"审批记录不存在：{approval_id}。",
                data={"approval_id": approval_id},
            ).model_dump()
        result = ToolEnvelope(
            ok=True,
            risk_level=record.risk_level if record.risk_level in {"low", "medium", "high", "critical"} else "high",
            summary=f"审批记录状态：{record.approval_id} -> {record.status}。",
            data={"approval": record.to_dict(), "approval_id": record.approval_id},
            next_actions=["如需查看完整链路，可用 get_audit_events_tool 按 trace_id 查询。"],
        ).model_dump()
        return attach_human_report(
            result,
            _approval_report(
                title="运维审批记录查询",
                conclusion=result["summary"],
                risk_level=result["risk_level"],
                approval=record.to_dict(),
                next_actions=result["next_actions"],
                trace_id=record.trace_id,
                session_id=record.session_id,
            ),
        )

    @mcp.tool()
    def get_approval_review_packet_tool(
        approval_id: str,
        include_audit_events: bool = True,
        audit_limit: int = 50,
    ) -> dict:
        """查询 B/S 审批页可渲染的只读审核包。

        该工具不会写审批账本，也不会签发 approval_token；它只把最新审批状态、
        同一 approval_id 的账本历史和同 trace 审计事件整理成页面友好的时间线。
        """

        record = approval_store.get_latest(approval_id)
        if record is None:
            result = ToolEnvelope(
                ok=False,
                risk_level="low",
                summary=f"审批审核包不存在：{approval_id}。",
                data={"approval_id": approval_id, "review_packet": None},
                next_actions=["确认 approval_id 是否来自 request_operation_approval_tool。"],
            ).model_dump()
            return attach_human_report(
                result,
                build_human_report(
                    title="审批审核包查询失败",
                    conclusion=result["summary"],
                    risk_level="low",
                    ok=False,
                    evidence=[f"approval_id={approval_id}"],
                    risk_explanation="该工具只读审批账本；未找到记录时不能作为审批或执行依据。",
                    safe_next_steps=result["next_actions"],
                ),
            )

        approval = record.to_dict()
        ledger_history = approval_store.get_history(approval_id)
        audit_limit = max(1, min(int(audit_limit), 200))
        audit_events = (
            _chronological_events(audit_logger.read_recent(limit=audit_limit, trace_id=record.trace_id))
            if include_audit_events and record.trace_id
            else []
        )
        packet = _build_review_packet(
            approval=approval,
            ledger_history=ledger_history,
            audit_events=audit_events,
            include_audit_events=include_audit_events,
            audit_limit=audit_limit,
        )
        result = ToolEnvelope(
            ok=True,
            risk_level=record.risk_level if record.risk_level in {"low", "medium", "high", "critical"} else "high",
            summary=(
                f"审批审核包已生成：{record.approval_id}，"
                f"包含 {len(ledger_history)} 条账本记录和 {len(audit_events)} 条 trace 审计事件。"
            ),
            data={
                "approval": approval,
                "approval_id": record.approval_id,
                "trace_id": record.trace_id,
                "session_id": record.session_id,
                "ledger_history": ledger_history,
                "ledger_history_count": len(ledger_history),
                "audit_events": audit_events,
                "audit_event_count": len(audit_events),
                "timeline": packet["timeline"],
                "timeline_count": len(packet["timeline"]),
                "review_packet": packet,
            },
            next_actions=_review_next_actions(approval),
        ).model_dump()
        return attach_human_report(
            result,
            _review_packet_report(
                approval=approval,
                packet=packet,
                conclusion=result["summary"],
                risk_level=result["risk_level"],
                next_actions=result["next_actions"],
            ),
        )

    @mcp.tool()
    def get_approval_console_bundle_tool(
        approval_id: str | None = None,
        limit: int = 20,
        status: str | None = None,
        include_audit_events: bool = True,
        audit_limit: int = 50,
        include_html: bool = True,
        session_approver: str | None = None,
    ) -> dict:
        """Return a self-contained B/S approval console bundle.

        The bundle is read-only: it contains page state, an embeddable HTML
        shell and MCP payload previews. Approval token issue and decision
        recording still go through dedicated MCP tools.
        """

        safe_limit = max(1, min(int(limit), 200))
        safe_audit_limit = max(1, min(int(audit_limit), 200))
        approvals = approval_store.list_recent(limit=safe_limit, status=status)
        record = None
        if approval_id:
            record = approval_store.get_latest(approval_id)
            if record is None:
                result = ToolEnvelope(
                    ok=False,
                    risk_level="low",
                    summary=f"Approval console target not found: {approval_id}.",
                    data={"approval_id": approval_id, "approvals": approvals},
                    next_actions=["Use list_operation_approvals_tool or omit approval_id to load the latest approval."],
                ).model_dump()
                return attach_human_report(
                    result,
                    build_human_report(
                        title="Approval Console Bundle Failed",
                        conclusion=result["summary"],
                        risk_level="low",
                        ok=False,
                        evidence=[f"approval_id={approval_id}", f"approval_count={len(approvals)}"],
                        risk_explanation="The B/S console bundle can only focus an approval that exists in the ledger.",
                        safe_next_steps=result["next_actions"],
                    ),
                )
        elif approvals:
            record = approval_store.get_latest(str(approvals[0].get("approval_id") or ""))

        selected_packet: dict[str, Any] | None = None
        audit_events: list[dict[str, Any]] = []
        if record is not None:
            approval = record.to_dict()
            ledger_history = approval_store.get_history(record.approval_id)
            audit_events = (
                _chronological_events(audit_logger.read_recent(limit=safe_audit_limit, trace_id=record.trace_id))
                if include_audit_events and record.trace_id
                else []
            )
            selected_packet = _build_review_packet(
                approval=approval,
                ledger_history=ledger_history,
                audit_events=audit_events,
                include_audit_events=include_audit_events,
                audit_limit=safe_audit_limit,
            )

        bundle = build_approval_console_bundle(
            approvals=approvals,
            selected_packet=selected_packet,
            audit_events=audit_events,
            identity_mode=_approval_identity_mode(),
            include_html=include_html,
            session_approver=session_approver,
        )
        selected_id = bundle["state"].get("selected_approval_id")
        result = ToolEnvelope(
            ok=True,
            risk_level="low",
            summary=f"Approval console bundle generated with {len(approvals)} approval record(s).",
            data={
                "console_bundle": bundle,
                "approval_id": selected_id,
                "approval_count": len(approvals),
                "include_html": include_html,
            },
            next_actions=[
                "Render console_bundle.html in a trusted browser surface when include_html=true.",
                "Use issue_enterprise_approval_token_tool before record_operation_approval_tool when identity is enforced.",
            ],
        ).model_dump()
        return attach_human_report(
            result,
            build_human_report(
                title="Approval Console Bundle",
                conclusion=result["summary"],
                risk_level="low",
                evidence=[
                    f"schema={bundle.get('schema_version')}",
                    f"approval_count={len(approvals)}",
                    f"selected_approval_id={selected_id}",
                    f"enterprise_issuer_enabled={bundle['state']['identity_mode'].get('enterprise_token_issuer_enabled')}",
                    f"include_html={include_html}",
                ],
                risk_explanation="The console bundle is read-only; ledger writes and token issue remain separate auditable MCP tools.",
                safe_next_steps=result["next_actions"],
                trace_id=record.trace_id if record else None,
                session_id=record.session_id if record else None,
                details={
                    "console_schema": bundle.get("schema_version"),
                    "metrics": bundle["state"].get("metrics"),
                    "mcp_contract": bundle["state"].get("mcp_contract"),
                },
            ),
        )

    @mcp.tool()
    def revoke_operation_approval_tool(
        approval_id: str,
        revoked_by: str,
        comment: str | None = None,
    ) -> dict:
        """撤销尚未终止的审批记录。撤销后该 approval_id 不能再进入真实执行。"""

        try:
            record = approval_store.revoke_approval(
                approval_id=approval_id,
                revoked_by=revoked_by,
                comment=comment,
            )
            audit_logger.append(
                AuditEvent(
                    event_type="approval_revoked",
                    tool_name=record.tool_name,
                    session_id=record.session_id,
                    trace_id=record.trace_id,
                    risk_level=record.risk_level,
                    decision=record.status,
                    params_summary={"approval_id": approval_id, "revoked_by": revoked_by},
                    result_summary=record.to_dict(),
                )
            )
            result = ToolEnvelope(
                ok=True,
                risk_level=record.risk_level if record.risk_level in {"low", "medium", "high", "critical"} else "high",
                summary=f"审批已撤销：{record.approval_id}。",
                data={"approval": record.to_dict(), "approval_id": record.approval_id},
                next_actions=[
                    "不要继续使用该 approval_id 执行真实变更。",
                    "如仍需操作，请重新从 dry-run 计划创建审批申请。",
                ],
            ).model_dump()
            return attach_human_report(
                result,
                _approval_report(
                    title="运维审批已撤销",
                    conclusion=result["summary"],
                    risk_level=result["risk_level"],
                    approval=record.to_dict(),
                    next_actions=result["next_actions"],
                    trace_id=record.trace_id,
                    session_id=record.session_id,
                ),
            )
        except Exception as exc:
            return ToolEnvelope(
                ok=False,
                risk_level="high",
                summary="撤销审批失败。",
                data={"approval_id": approval_id, "error": str(exc)},
                next_actions=["确认 approval_id 是否存在，且状态不是 rejected/revoked/expired。"],
            ).model_dump()

    @mcp.tool()
    def renew_operation_approval_tool(
        approval_id: str,
        renewed_by: str,
        expires_in_minutes: int = 60,
        comment: str | None = None,
    ) -> dict:
        """续期已通过且未过期的审批记录。续期不改变审批范围。"""

        try:
            record = approval_store.renew_approval(
                approval_id=approval_id,
                renewed_by=renewed_by,
                expires_in_minutes=expires_in_minutes,
                comment=comment,
            )
            audit_logger.append(
                AuditEvent(
                    event_type="approval_renewed",
                    tool_name=record.tool_name,
                    session_id=record.session_id,
                    trace_id=record.trace_id,
                    risk_level=record.risk_level,
                    decision=record.status,
                    params_summary={
                        "approval_id": approval_id,
                        "renewed_by": renewed_by,
                        "expires_in_minutes": expires_in_minutes,
                    },
                    result_summary=record.to_dict(),
                )
            )
            result = ToolEnvelope(
                ok=True,
                risk_level=record.risk_level if record.risk_level in {"low", "medium", "high", "critical"} else "high",
                summary=f"审批已续期：{record.approval_id}，当前过期时间 {record.expires_at}。",
                data={"approval": record.to_dict(), "approval_id": record.approval_id},
                next_actions=["审批范围未变化；真实执行仍必须匹配原 scope_hash。"],
            ).model_dump()
            return attach_human_report(
                result,
                _approval_report(
                    title="运维审批已续期",
                    conclusion=result["summary"],
                    risk_level=result["risk_level"],
                    approval=record.to_dict(),
                    next_actions=result["next_actions"],
                    trace_id=record.trace_id,
                    session_id=record.session_id,
                ),
            )
        except Exception as exc:
            return ToolEnvelope(
                ok=False,
                risk_level="high",
                summary="续期审批失败。",
                data={"approval_id": approval_id, "error": str(exc)},
                next_actions=["确认 approval_id 已 granted、未过期且未被撤销。"],
            ).model_dump()

    @mcp.tool()
    def cleanup_expired_operation_approvals_tool(
        limit: int = 200,
        dry_run: bool = True,
    ) -> dict:
        """扫描已过期审批。dry_run=false 时追加 expired 状态记录。"""

        expired = approval_store.mark_expired_approvals(limit=limit, dry_run=dry_run)
        for record in expired:
            if dry_run:
                continue
            audit_logger.append(
                AuditEvent(
                    event_type="approval_expired",
                    tool_name=record.tool_name,
                    session_id=record.session_id,
                    trace_id=record.trace_id,
                    risk_level=record.risk_level,
                    decision=record.status,
                    params_summary={"approval_id": record.approval_id, "cleanup": True},
                    result_summary=record.to_dict(),
                )
            )
        audit_logger.append(
            AuditEvent(
                event_type="approval_cleanup",
                tool_name="cleanup_expired_operation_approvals_tool",
                risk_level="low" if dry_run else "medium",
                decision="dry_run" if dry_run else "expired_marked",
                params_summary={"limit": limit, "dry_run": dry_run},
                result_summary={"expired_count": len(expired), "approval_ids": [record.approval_id for record in expired]},
            )
        )
        result = ToolEnvelope(
            ok=True,
            risk_level="low" if dry_run else "medium",
            summary=(
                f"发现 {len(expired)} 条过期审批候选，未修改账本。"
                if dry_run
                else f"已将 {len(expired)} 条过期审批标记为 expired。"
            ),
            data={
                "approvals": [record.to_dict() for record in expired],
                "expired_count": len(expired),
                "limit": limit,
                "dry_run": dry_run,
            },
            next_actions=(
                ["确认候选审批无误后，可用 dry_run=false 写入 expired 状态。"]
                if dry_run
                else ["使用 list_operation_approvals_tool(status='expired') 查看清理结果。"]
            ),
        ).model_dump()
        return attach_human_report(
            result,
            build_human_report(
                title="过期审批清理",
                conclusion=result["summary"],
                risk_level=result["risk_level"],
                evidence=[f"expired_count={len(expired)}", f"dry_run={dry_run}", f"limit={limit}"],
                risk_explanation="该工具只更新审批账本状态，不执行系统变更；dry_run=false 会追加 expired 记录。",
                safe_next_steps=result["next_actions"],
                details={"approval_ids": [record.approval_id for record in expired[:20]]},
            ),
        )

    @mcp.tool()
    def verify_approval_chain_tool(approval_file: str | None = None) -> dict:
        """校验审批 JSONL 账本的哈希链完整性。"""

        path = Path(approval_file) if approval_file else approval_store.ledger_path()
        verification = verify_approval_chain(path)
        audit_logger.append(
            AuditEvent(
                event_type="approval_chain_verification",
                tool_name="verify_approval_chain_tool",
                risk_level="low" if verification.ok else "medium",
                decision="valid" if verification.ok else "invalid",
                params_summary={"approval_file": str(path)},
                result_summary=verification.to_dict(),
            )
        )
        result = ToolEnvelope(
            ok=verification.ok,
            risk_level="low" if verification.ok else "medium",
            summary=verification.summary,
            data={"verification": verification.to_dict()},
            next_actions=(
                ["审批账本哈希链可信，可继续按 approval_id 校验真实执行。"]
                if verification.ok
                else ["停止依赖该审批账本放行真实执行；检查 first_bad_line、expected_hash 和 actual_hash。"]
            ),
        ).model_dump()
        return attach_human_report(
            result,
            build_human_report(
                title="审批账本哈希链校验",
                conclusion=result["summary"],
                risk_level=result["risk_level"],
                evidence=[
                    f"ok={verification.ok}",
                    f"checked_records={verification.checked_records}",
                    f"first_bad_line={verification.first_bad_line}",
                    f"file={verification.file}",
                ],
                risk_explanation="该工具只读取审批账本并重新计算哈希链；校验失败代表账本可能缺少链字段、被截断或被篡改。",
                safe_next_steps=result["next_actions"],
                audit_hint="本次校验会写入 approval_chain_verification 审计事件，可继续用 get_audit_events_tool 查询。",
                details={"verification": verification.to_dict()},
            ),
        )

    @mcp.tool()
    def anchor_approval_chain_tool(
        approval_file: str | None = None,
        signer: str = "xingxuan-mcp-local",
        transparency_log_hint: str = "local-jsonl-anchor",
    ) -> dict:
        """为审批 JSONL 账本创建外部锚点。

        如果设置环境变量 XINGXUAN_MCP_APPROVAL_ANCHOR_SECRET，会追加 HMAC-SHA256 签名。
        """

        path = Path(approval_file) if approval_file else approval_store.ledger_path()
        try:
            anchor = create_approval_anchor(
                path,
                signer=signer,
                transparency_log_hint=transparency_log_hint,
            )
            audit_logger.append(
                AuditEvent(
                    event_type="approval_anchor_created",
                    tool_name="anchor_approval_chain_tool",
                    risk_level="low",
                    decision="anchored",
                    params_summary={"approval_file": str(path), "signer": signer},
                    result_summary=anchor.to_dict(),
                )
            )
            signature_enabled = anchor.signature_algorithm != "unsigned"
            result = ToolEnvelope(
                ok=True,
                risk_level="low",
                summary=(
                    "审批账本外部锚点已创建，并已使用 HMAC 签名。"
                    if signature_enabled
                    else "审批账本外部锚点已创建；当前未配置签名密钥。"
                ),
                data={
                    "anchor": anchor.to_dict(),
                    "signature_enabled": signature_enabled,
                    "anchor_model": "local-jsonl-anchor",
                },
                next_actions=[
                    "调用 verify_approval_anchor_tool 验证审批账本是否仍与锚点一致。",
                    "生产环境建议设置 XINGXUAN_MCP_APPROVAL_ANCHOR_SECRET，或把 anchor payload 上传到主机外的只追加存储。",
                ],
            ).model_dump()
            return attach_human_report(
                result,
                build_human_report(
                    title="审批账本外部锚点创建结果",
                    conclusion=result["summary"],
                    risk_level="low",
                    evidence=[
                        f"anchor_id={anchor.anchor_id}",
                        f"checked_records={anchor.checked_records}",
                        f"head_hash={anchor.head_hash}",
                        f"signature_algorithm={anchor.signature_algorithm}",
                    ],
                    risk_explanation="锚点用于冻结某个时间点的审批账本链尾 hash 和文件摘要，便于发现后续整体重算、替换或截断。",
                    safe_next_steps=result["next_actions"],
                    audit_hint="本次锚点创建已写入 approval_anchor_created 审计事件；可继续用 verify_approval_anchor_tool 校验。",
                    details={"anchor": anchor.to_dict(), "signature_enabled": signature_enabled},
                ),
            )
        except Exception as exc:
            audit_logger.append(
                AuditEvent(
                    event_type="approval_anchor_failed",
                    tool_name="anchor_approval_chain_tool",
                    risk_level="medium",
                    decision="failed",
                    params_summary={"approval_file": str(path), "signer": signer},
                    result_summary={"error": str(exc)},
                    error=str(exc),
                )
            )
            result = ToolEnvelope(
                ok=False,
                risk_level="medium",
                summary="创建审批账本外部锚点失败。",
                data={"approval_file": str(path), "error": str(exc)},
                next_actions=["先调用 verify_approval_chain_tool 确认审批账本哈希链有效，再重新创建锚点。"],
            ).model_dump()
            return attach_human_report(
                result,
                build_human_report(
                    title="审批账本外部锚点创建失败",
                    conclusion=result["summary"],
                    risk_level=result["risk_level"],
                    ok=False,
                    evidence=[f"approval_file={path}", f"error={exc}"],
                    risk_explanation="无法创建锚点通常意味着审批账本不存在、哈希链无效，或锚点目录不可写。",
                    safe_next_steps=result["next_actions"],
                ),
            )

    @mcp.tool()
    def verify_approval_anchor_tool(approval_file: str | None = None) -> dict:
        """验证审批 JSONL 账本是否仍匹配外部锚点。"""

        path = Path(approval_file) if approval_file else approval_store.ledger_path()
        verification = verify_approval_anchor(path)
        audit_logger.append(
            AuditEvent(
                event_type="approval_anchor_verification",
                tool_name="verify_approval_anchor_tool",
                risk_level="low" if verification.ok else "medium",
                decision="valid" if verification.ok else "invalid",
                params_summary={"approval_file": str(path)},
                result_summary=verification.to_dict(),
            )
        )
        result = ToolEnvelope(
            ok=verification.ok,
            risk_level="low" if verification.ok else "medium",
            summary=verification.summary,
            data={"verification": verification.to_dict()},
            next_actions=(
                ["审批账本仍匹配锚点，可继续结合 approval_id 校验真实执行。"]
                if verification.ok
                else ["停止依赖该审批账本放行真实执行；检查 head_hash、file_sha256、签名密钥和 anchor_file。"]
            ),
        ).model_dump()
        return attach_human_report(
            result,
            build_human_report(
                title="审批账本外部锚点校验",
                conclusion=result["summary"],
                risk_level=result["risk_level"],
                ok=result["ok"],
                evidence=[
                    f"ok={verification.ok}",
                    f"checked_records={verification.checked_records}",
                    f"anchor_id={verification.anchor_id}",
                    f"head_hash={verification.head_hash}",
                    f"anchored_head_hash={verification.anchored_head_hash}",
                    f"signature_ok={verification.signature_ok}",
                ],
                risk_explanation="锚点校验失败通常意味着审批账本被整体重算、截断、替换，或 HMAC 签名密钥不匹配。",
                safe_next_steps=result["next_actions"],
                audit_hint="本次校验会写入 approval_anchor_verification 审计事件，可继续用 get_audit_events_tool 查询。",
                details={"verification": verification.to_dict()},
            ),
        )

    @mcp.tool()
    def list_operation_approvals_tool(
        limit: int = 20,
        status: str | None = None,
        trace_id: str | None = None,
    ) -> dict:
        """查询最近审批记录。"""

        approvals = approval_store.list_recent(limit=limit, status=status, trace_id=trace_id)
        result = ToolEnvelope(
            ok=True,
            risk_level="low",
            summary=f"Loaded {len(approvals)} approval record(s).",
            data={"approvals": approvals, "limit": limit, "status": status, "trace_id": trace_id},
            next_actions=["使用 get_operation_approval_tool 查看单个 approval_id 的完整状态。"],
        ).model_dump()
        return attach_human_report(
            result,
            build_human_report(
                title="运维审批记录列表",
                conclusion=result["summary"],
                risk_level="low",
                evidence=[f"approvals={len(approvals)}", f"status_filter={status}", f"trace_id={trace_id}"],
                risk_explanation="审批记录查询是只读操作，不会修改系统。",
                safe_next_steps=result["next_actions"],
                trace_id=trace_id,
                details={"approval_ids": [item.get("approval_id") for item in approvals[:10]]},
            ),
        )

    @mcp.tool()
    def get_bs_gateway_approver_tool(
        gateway_url: str = "http://127.0.0.1:8765",
    ) -> dict:
        """查询本地 B/S 审批网关的已登录审批人。

        操作被护栏阻断、需要内联审批时，先调用本工具：
        - 若有已登录审批人，将其名称作为 approver 传入 request_inline_approval_tool。
        - 若无已登录审批人，返回登录页 URL，引导用户先完成注册/登录再批准。
        """
        import json as _json
        import urllib.request
        import urllib.error

        sessions_url = f"{gateway_url.rstrip('/')}/api/auth/sessions"
        login_url = f"{gateway_url.rstrip('/')}/login"
        try:
            with urllib.request.urlopen(sessions_url, timeout=3) as resp:
                data = _json.loads(resp.read().decode())
            approvers = data.get("data", {}).get("approvers", [])
        except Exception as exc:
            return ToolEnvelope(
                ok=False,
                risk_level="low",
                summary=f"B/S 审批网关不可达（{exc}）。请先启动网关。",
                data={"gateway_url": gateway_url, "login_url": login_url},
                next_actions=[
                    f"运行 {WEB_GATEWAY_NAME} 启动 B/S 网关。",
                    f"启动后访问 {login_url} 注册/登录，再重新调用本工具。",
                ],
            ).model_dump()
        if not approvers:
            return ToolEnvelope(
                ok=False,
                risk_level="low",
                summary="当前无已登录审批人，请先在 B/S 控制台完成注册/登录。",
                data={"approvers": [], "login_url": login_url},
                next_actions=[
                    f"请在浏览器打开并注册/登录：{login_url}",
                    "登录后重新调用本工具获取审批人名称。",
                ],
            ).model_dump()
        return ToolEnvelope(
            ok=True,
            risk_level="low",
            summary=f"已登录审批人：{', '.join(approvers)}",
            data={"approvers": approvers, "login_url": login_url},
            next_actions=[
                f"将 approver={approvers[0]!r} 传入 request_inline_approval_tool 完成内联审批。",
            ],
        ).model_dump()


def _approval_identity_mode() -> dict[str, Any]:
    config = load_approval_identity_config()
    secret_status = config.secret_status()
    return {
        "approval_identity_required": approval_identity_required(),
        "scope_binding_required": config.require_approval_identity_scope,
        "enterprise_token_issuer_enabled": enterprise_approval_token_issuer_enabled(),
        "enterprise_approver_role": config.enterprise_required_approver_role,
        "enterprise_allowed_issuers": list(config.enterprise_allowed_issuers),
        "approval_identity_secret_configured": bool(
            secret_status.get("approval_identity_secret", {}).get("configured")
        ),
        "enterprise_assertion_secret_configured": bool(
            secret_status.get("enterprise_identity_assertion_secret", {}).get("configured")
        ),
        "secret_status": secret_status,
        "config_sources": config.source_map,
    }


def _token_public_claims(token: dict[str, Any]) -> dict[str, Any]:
    return {
        key: token.get(key)
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
        if token.get(key) is not None
    }


def _approval_is_expired(approval: dict[str, Any]) -> bool:
    expires_at = _parse_utc(approval.get("expires_at"))
    return bool(expires_at and expires_at <= datetime.now(timezone.utc))


def _parse_utc(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _approval_report(
    *,
    title: str,
    conclusion: str,
    risk_level: str,
    approval: dict[str, Any],
    next_actions: list[str],
    trace_id: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    identity = _latest_approval_identity(approval)
    evidence = [
        f"approval_id={approval.get('approval_id')}",
        f"status={approval.get('status')}",
        f"last_action={approval.get('last_action')}",
        f"tool={approval.get('tool_name')}",
        f"operation={approval.get('operation')}",
        f"target={approval.get('target')}",
        f"expires_at={approval.get('expires_at')}",
        f"scope_hash={approval.get('scope_hash')}",
        f"renewal_count={approval.get('renewal_count')}",
        f"required_approvals={approval.get('required_approvals')}",
        f"granted_approvals={approval.get('granted_approvals')}",
        f"max_renewals={approval.get('max_renewals')}",
        f"policy_rule_ids={approval.get('policy_rule_ids')}",
        f"approver_history_count={len(approval.get('approver_history') or [])}",
        f"identity_verified={identity.get('verified')}" if identity else None,
        f"identity_provider={identity.get('provider')}" if identity else None,
        f"identity_token_id={identity.get('token_id')}" if identity else None,
        f"prev_hash={approval.get('prev_hash')}",
        f"event_hash={approval.get('event_hash')}",
    ]
    return build_human_report(
        title=title,
        conclusion=conclusion,
        risk_level=risk_level,
        evidence=[item for item in evidence if item and not item.endswith("=None")],
        risk_explanation="审批只对匹配 tool、operation、target 和 scope_hash 的操作生效；多级审批必须达到 required_approvals，且不能放行 critical 风险；启用外部身份通道时还必须校验签名凭证。",
        safe_next_steps=next_actions,
        trace_id=trace_id,
        session_id=session_id,
        audit_hint="可用 verify_approval_chain_tool 校验审批账本哈希链，也可用 get_audit_events_tool 按 trace_id 查询审批与身份事件。",
        details={"approval": approval},
    )


def _latest_approval_identity(approval: dict[str, Any]) -> dict[str, Any] | None:
    history = approval.get("approver_history") or []
    if not isinstance(history, list):
        return None
    for item in reversed(history):
        if not isinstance(item, dict):
            continue
        identity = item.get("identity")
        if isinstance(identity, dict):
            return identity
    return None


def _decision_next_actions(approval: dict[str, Any]) -> list[str]:
    status = approval.get("status")
    if status == "granted":
        return ["审批已通过，可在未过期前将 approval_id 传给匹配的 request_* 工具。"]
    if status == "partially_granted":
        required = int(approval.get("required_approvals") or 1)
        granted = int(approval.get("granted_approvals") or 0)
        remaining = max(0, required - granted)
        return [
            f"当前仍是 partially_granted，还差 {remaining} 个有效审批人。",
            "必须由不同且被策略允许的审批人继续 grant，真实执行前仍会被 approval_validation 阻断。",
        ]
    return ["审批已拒绝，不应继续执行真实变更。"]


def _build_review_packet(
    *,
    approval: dict[str, Any],
    ledger_history: list[dict[str, Any]],
    audit_events: list[dict[str, Any]],
    include_audit_events: bool,
    audit_limit: int,
) -> dict[str, Any]:
    required = int(approval.get("required_approvals") or 1)
    granted = int(approval.get("granted_approvals") or 0)
    remaining = max(0, required - granted)
    audit_event_types = sorted({str(item.get("event_type")) for item in audit_events if item.get("event_type")})
    identities = _approval_identities(ledger_history)
    timeline = _build_review_timeline(ledger_history, audit_events)
    return {
        "schema_version": "approval-review-packet-v1",
        "approval_id": approval.get("approval_id"),
        "status": approval.get("status"),
        "risk_level": approval.get("risk_level"),
        "trace_id": approval.get("trace_id"),
        "session_id": approval.get("session_id"),
        "operation": {
            "tool_name": approval.get("tool_name"),
            "operation": approval.get("operation"),
            "target": approval.get("target"),
            "scope_hash": approval.get("scope_hash"),
        },
        "policy": {
            "required_approvals": required,
            "granted_approvals": granted,
            "remaining_approvals": remaining,
            "require_distinct_approvers": approval.get("require_distinct_approvers"),
            "allow_self_approval": approval.get("allow_self_approval"),
            "max_renewals": approval.get("max_renewals"),
            "policy_ttl_minutes": approval.get("policy_ttl_minutes"),
            "policy_rule_ids": list(approval.get("policy_rule_ids") or []),
            "policy_reasons": list(approval.get("policy_reasons") or []),
            "allowed_approver_ids": list(approval.get("allowed_approver_ids") or []),
            "allowed_approver_roles": list(approval.get("allowed_approver_roles") or []),
        },
        "lineage": {
            "ledger_history_count": len(ledger_history),
            "prev_hash": approval.get("prev_hash"),
            "event_hash": approval.get("event_hash"),
            "created_at": approval.get("created_at"),
            "updated_at": approval.get("updated_at"),
            "expires_at": approval.get("expires_at"),
            "last_action": approval.get("last_action"),
        },
        "identity": {
            "verified_identity_count": len(identities),
            "identities": identities,
            "latest_identity": identities[-1] if identities else None,
        },
        "audit": {
            "included": include_audit_events,
            "limit": audit_limit,
            "event_count": len(audit_events),
            "event_types": audit_event_types,
        },
        "timeline": timeline,
    }


def _build_review_timeline(
    ledger_history: list[dict[str, Any]],
    audit_events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    timeline: list[dict[str, Any]] = []
    for index, record in enumerate(ledger_history, start=1):
        actor = (
            record.get("approver")
            or record.get("renewed_by")
            or record.get("revoked_by")
            or record.get("expired_by")
            or record.get("requester")
        )
        action = record.get("last_action") or record.get("status")
        timeline.append(
            {
                "source": "approval_ledger",
                "sequence": index,
                "timestamp": record.get("updated_at") or record.get("created_at"),
                "event_type": f"approval_{action}",
                "approval_id": record.get("approval_id"),
                "status": record.get("status"),
                "actor": actor,
                "decision": action,
                "summary": f"{record.get('approval_id')} -> {record.get('status')}",
                "prev_hash": record.get("prev_hash"),
                "event_hash": record.get("event_hash"),
            }
        )
    for index, event in enumerate(audit_events, start=1):
        event_type = event.get("event_type")
        timeline.append(
            {
                "source": "audit",
                "sequence": index,
                "timestamp": event.get("timestamp"),
                "event_type": event_type,
                "tool_name": event.get("tool_name"),
                "risk_level": event.get("risk_level"),
                "decision": event.get("decision"),
                "summary": _audit_timeline_summary(event),
                "prev_hash": event.get("prev_hash"),
                "event_hash": event.get("event_hash"),
            }
        )
    return sorted(
        timeline,
        key=lambda item: (
            str(item.get("timestamp") or ""),
            str(item.get("source") or ""),
            int(item.get("sequence") or 0),
        ),
    )


def _approval_identities(ledger_history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    identities: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for record in ledger_history:
        history = record.get("approver_history") or []
        if not isinstance(history, list):
            continue
        for item in history:
            if not isinstance(item, dict):
                continue
            identity = item.get("identity")
            if not isinstance(identity, dict):
                continue
            summary = {
                "approver": item.get("approver"),
                "decision": item.get("decision"),
                "recorded_at": item.get("recorded_at"),
                "verified": identity.get("verified"),
                "provider": identity.get("provider"),
                "subject": identity.get("subject"),
                "token_id": identity.get("token_id"),
                "key_id": identity.get("key_id"),
            }
            dedupe_key = (
                str(summary.get("approver") or ""),
                str(summary.get("decision") or ""),
                str(summary.get("token_id") or summary.get("recorded_at") or ""),
            )
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            identities.append({key: value for key, value in summary.items() if value is not None})
    return identities


def _chronological_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(events, key=lambda item: str(item.get("timestamp") or ""))


def _audit_timeline_summary(event: dict[str, Any]) -> str:
    event_type = str(event.get("event_type") or "audit_event")
    decision = event.get("decision")
    tool_name = event.get("tool_name")
    parts = [event_type]
    if decision:
        parts.append(str(decision))
    if tool_name:
        parts.append(str(tool_name))
    return " / ".join(parts)


def _review_next_actions(approval: dict[str, Any]) -> list[str]:
    status = approval.get("status")
    if status == "granted":
        return [
            "在 B/S 页面展示 scope_hash、expires_at 和身份摘要，确认真实执行参数完全匹配后再调用 request_* 工具。",
            "不要直接写 approvals.jsonl；所有状态变化仍必须通过 MCP 审批工具追加落账。",
        ]
    if status == "partially_granted":
        required = int(approval.get("required_approvals") or 1)
        granted = int(approval.get("granted_approvals") or 0)
        return [
            f"当前还差 {max(0, required - granted)} 个有效审批人，B/S 页面应继续显示待审批状态。",
            "后续审批仍应通过 record_operation_approval_tool，并在强身份模式下携带 approval_token。",
        ]
    if status == "requested":
        return [
            "在 B/S 页面展示待审批详情、策略命中原因和 trace 时间线。",
            "由受信审批通道签发 approval_token 后再调用 record_operation_approval_tool。",
        ]
    return [
        "该审批已经终止或不可放行，B/S 页面应展示为不可执行状态。",
        "如仍需变更，请重新生成 dry-run 计划并创建新的审批申请。",
    ]


def _review_packet_report(
    *,
    approval: dict[str, Any],
    packet: dict[str, Any],
    conclusion: str,
    risk_level: str,
    next_actions: list[str],
) -> dict[str, Any]:
    audit = packet.get("audit") if isinstance(packet.get("audit"), dict) else {}
    policy = packet.get("policy") if isinstance(packet.get("policy"), dict) else {}
    identity = packet.get("identity") if isinstance(packet.get("identity"), dict) else {}
    lineage = packet.get("lineage") if isinstance(packet.get("lineage"), dict) else {}
    event_types = list(audit.get("event_types") or [])
    evidence = [
        f"approval_id={approval.get('approval_id')}",
        f"status={approval.get('status')}",
        f"tool={approval.get('tool_name')}",
        f"operation={approval.get('operation')}",
        f"scope_hash={approval.get('scope_hash')}",
        f"required_approvals={policy.get('required_approvals')}",
        f"granted_approvals={policy.get('granted_approvals')}",
        f"remaining_approvals={policy.get('remaining_approvals')}",
        f"ledger_history_count={lineage.get('ledger_history_count')}",
        f"audit_event_count={audit.get('event_count')}",
        f"timeline_count={len(packet.get('timeline') or [])}",
        f"verified_identity_count={identity.get('verified_identity_count')}",
        f"event_hash={lineage.get('event_hash')}",
    ]
    evidence.extend(f"audit_event_type={item}" for item in event_types[:6])
    return build_human_report(
        title="B/S 审批审核包",
        conclusion=conclusion,
        risk_level=risk_level,
        evidence=[item for item in evidence if item and not item.endswith("=None")],
        risk_explanation="该工具只读聚合审批账本和 trace 审计事件，供 B/S 审批页展示；真正落账仍必须走审批工具、哈希链和外部身份校验。",
        safe_next_steps=next_actions,
        trace_id=approval.get("trace_id"),
        session_id=approval.get("session_id"),
        audit_hint="页面可继续调用 verify_approval_chain_tool / verify_approval_anchor_tool 证明账本完整性。",
        details={
            "review_packet_schema": packet.get("schema_version"),
            "operation": packet.get("operation"),
            "policy": policy,
            "identity": identity,
            "audit_event_types": event_types,
            "timeline_preview": list(packet.get("timeline") or [])[:12],
        },
    )
