from __future__ import annotations

from typing import Any


REPLY_SECTIONS = ("结论", "证据", "风险", "下一步", "trace_id")


def attach_human_report(envelope: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    """把给 AstrBot 复述用的可读报告放入 data.human_report。"""

    data = envelope.setdefault("data", {})
    if isinstance(data, dict):
        data["human_report"] = report
    return envelope


def build_human_report(
    *,
    title: str,
    conclusion: str,
    risk_level: str,
    ok: bool = True,
    evidence: list[str] | None = None,
    risk_explanation: str | None = None,
    safe_next_steps: list[str] | None = None,
    trace_id: str | None = None,
    session_id: str | None = None,
    audit_hint: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "title": title,
        "status": "success" if ok else "attention",
        "conclusion": conclusion,
        "risk_level": risk_level,
        "risk_explanation": risk_explanation or _default_risk_explanation(risk_level),
        "evidence": evidence or [],
        "safe_next_steps": safe_next_steps or [],
        "trace_id": trace_id,
        "session_id": session_id,
        "audit_hint": audit_hint,
        "reply_sections": list(REPLY_SECTIONS),
        "details": details or {},
    }


def build_guardrail_report(
    *,
    tool_name: str,
    operation: str,
    decision: dict[str, Any],
    context: dict[str, Any],
    trace: dict[str, Any],
) -> dict[str, Any]:
    risk_level = str(decision.get("risk_level") or "low")
    decision_text = str(decision.get("decision") or "allow")
    conclusion = str(decision.get("summary") or "安全校验已完成。")
    evidence = [
        f"tool={tool_name}",
        f"operation={operation}",
        f"decision={decision_text}",
        f"dry_run={context.get('dry_run')}",
        f"target={context.get('target')}",
    ]
    if context.get("command"):
        evidence.append(f"command={context.get('command')}")
    if context.get("path"):
        evidence.append(f"path={context.get('path')}")
    findings = decision.get("findings") or []
    if findings:
        evidence.extend(f"rule={item.get('rule_id')}:{item.get('risk_level')}" for item in findings[:5])
    return build_human_report(
        title=f"{tool_name} 安全意图校验",
        conclusion=conclusion,
        risk_level=risk_level,
        ok=bool(decision.get("allowed", decision_text != "deny")),
        evidence=evidence,
        risk_explanation=conclusion,
        safe_next_steps=list(decision.get("safe_alternatives") or []),
        trace_id=trace.get("trace_id"),
        session_id=trace.get("session_id"),
        audit_hint="可用 get_audit_events_tool 按 trace_id 查询本次校验审计事件。",
    )


def build_execution_report(
    *,
    tool_name: str,
    operation: str,
    envelope: dict[str, Any],
) -> dict[str, Any]:
    data = envelope.get("data") if isinstance(envelope.get("data"), dict) else {}
    guard = data.get("guardrail_decision") if isinstance(data, dict) else None
    approval_validation = data.get("approval_validation") if isinstance(data.get("approval_validation"), dict) else {}
    execution_validation = data.get("execution_validation") if isinstance(data.get("execution_validation"), dict) else {}
    trace = data.get("trace") if isinstance(data.get("trace"), dict) else {}
    plan = data.get("plan") if isinstance(data.get("plan"), dict) else {}
    least_privilege = data.get("least_privilege") if isinstance(data.get("least_privilege"), dict) else {}
    approval_request = data.get("approval_request") if isinstance(data.get("approval_request"), dict) else {}
    post_checks = data.get("post_checks") if isinstance(data.get("post_checks"), dict) else {}
    rollback_hint = data.get("rollback_hint") if isinstance(data.get("rollback_hint"), list) else []
    remote_execution = data.get("remote_execution") if isinstance(data.get("remote_execution"), dict) else {}
    dry_run = data.get("dry_run")
    blocked = bool(data.get("blocked"))
    status = data.get("status") or ("blocked" if blocked else "unknown")
    risk_level = str(envelope.get("risk_level") or (guard.get("risk_level") if isinstance(guard, dict) else "low"))

    if blocked:
        conclusion = f"{tool_name} 已被安全护栏阻断，未生成真实执行动作。"
    elif dry_run:
        conclusion = f"{tool_name} 已生成 dry-run 计划，没有真实修改系统。"
    else:
        conclusion = f"{tool_name} 已按固定模板执行，需核对后置检查结果。"

    evidence = [
        f"tool={tool_name}",
        f"operation={operation}",
        f"action={data.get('action')}",
        f"status={status}",
        f"dry_run={dry_run}",
        f"target={data.get('target')}",
        f"platform={data.get('platform')}",
    ]
    evidence.extend(_plan_evidence(plan))
    if isinstance(guard, dict):
        evidence.append(f"guardrail_decision={guard.get('decision')}")
    if approval_validation:
        evidence.append(f"approval_ok={approval_validation.get('ok')}")
        evidence.append(f"approval_id={approval_validation.get('approval_id')}")
    if execution_validation:
        evidence.append(f"execution_policy={execution_validation.get('decision')}")
        evidence.append(f"execution_template={execution_validation.get('template_id')}")
        evidence.append(f"execution_identity_ok={execution_validation.get('identity_ok')}")
        evidence.append(f"execution_scope_ok={execution_validation.get('scope_ok')}")
    if approval_request:
        evidence.append("approval_request=copyable")
        evidence.append(f"approval_scope_hash={data.get('approval_scope_hash')}")
    if remote_execution:
        evidence.append(f"remote_mode={remote_execution.get('mode')}")
        evidence.append(f"remote_transport={remote_execution.get('transport')}")
        evidence.append(f"remote_profile={remote_execution.get('profile_id')}")
        bundle_validation = remote_execution.get("bundle_validation")
        if isinstance(bundle_validation, dict):
            evidence.append(f"remote_bundle_ok={bundle_validation.get('ok')}")
            evidence.append(f"remote_request_contract_ok={bundle_validation.get('request_contract_ok')}")
    if least_privilege:
        evidence.append(f"template_id={least_privilege.get('template_id')}")
        evidence.append(f"recommended_account={least_privilege.get('recommended_runtime_account')}")
    if post_checks:
        evidence.append(f"post_checks_ok={post_checks.get('ok')}")
        evidence.append(f"post_checks_count={len(post_checks.get('checks') or [])}")

    return build_human_report(
        title=f"{tool_name} 运维计划说明",
        conclusion=conclusion,
        risk_level=risk_level,
        ok=bool(envelope.get("ok")),
        evidence=[item for item in evidence if item and not item.endswith("=None")],
        risk_explanation=_execution_risk_explanation(guard, risk_level),
        safe_next_steps=list(envelope.get("next_actions") or []),
        trace_id=data.get("trace_id") or trace.get("trace_id"),
        session_id=data.get("session_id") or trace.get("session_id"),
        audit_hint="可用 get_audit_events_tool 按 trace_id 查询 guardrail_decision 与 tool_result。",
        details={
            "approval_validation": approval_validation,
            "execution_validation": execution_validation,
            "approval_request": approval_request,
            "execute_after_approval": data.get("execute_after_approval") if isinstance(data.get("execute_after_approval"), dict) else {},
            "remote_execution": remote_execution,
            "remote_contract_binding": {
                "approval_binding": remote_execution.get("approval_binding") if isinstance(remote_execution, dict) else {},
                "trace_binding": remote_execution.get("trace_binding") if isinstance(remote_execution, dict) else {},
                "bundle_validation": remote_execution.get("bundle_validation") if isinstance(remote_execution, dict) else {},
                "request_contract_validation": (
                    {
                        "ok": remote_execution.get("bundle_validation", {}).get("request_contract_ok"),
                        "errors": remote_execution.get("bundle_validation", {}).get("request_contract_errors"),
                    }
                    if isinstance(remote_execution.get("bundle_validation"), dict)
                    else {}
                ),
            },
            "least_privilege_summary": _least_privilege_summary(least_privilege),
            "post_checks": post_checks,
            "rollback_hint": rollback_hint,
            "plan_subject": least_privilege.get("plan_subject") if least_privilege else {},
        },
    )


def build_action_templates_report(templates: list[dict[str, Any]], platform_filter: str) -> dict[str, Any]:
    actions = [str(item.get("action")) for item in templates[:8]]
    evidence = [f"count={len(templates)}", f"platform_filter={platform_filter}"]
    evidence.extend(f"template={item.get('template_id')}:{item.get('action')}" for item in templates[:5])
    return build_human_report(
        title="最小权限执行模板清单",
        conclusion=f"已返回 {len(templates)} 个固定执行模板，可用于解释写操作的权限边界。",
        risk_level="low",
        evidence=evidence,
        risk_explanation="这是只读模板查询，不修改系统；真实执行仍需要 guardrail、审批和审计。",
        safe_next_steps=[
            "选择一个 action 后生成 request_* dry-run 计划。",
            "检查模板中的 allowed_scopes、denied_scopes 和 rollback_strategy。",
        ],
        details={"actions": actions},
    )


def build_execution_agent_profiles_report(profiles: list[dict[str, Any]], platform_filter: str) -> dict[str, Any]:
    profile_ids = [str(item.get("profile_id")) for item in profiles[:8]]
    deployable = [item for item in profiles if item.get("can_execute_privileged_templates")]
    evidence = [f"count={len(profiles)}", f"platform_filter={platform_filter}"]
    evidence.extend(f"profile={item.get('profile_id')}:{item.get('deployment_state')}" for item in profiles[:5])
    return build_human_report(
        title="受限执行代理档案清单",
        conclusion=f"已返回 {len(profiles)} 个执行代理能力档案；当前可真实放开提权模板的档案数为 {len(deployable)}。",
        risk_level="low",
        evidence=evidence,
        risk_explanation="这是只读代理档案查询，不安装服务、不写 sudoers、不执行系统命令。",
        safe_next_steps=[
            "先确认 deployment_state 是否为 deployed。",
            "再检查 allowed_template_ids、denied_capabilities 和 deployment_artifacts。",
        ],
        details={"profile_ids": profile_ids, "deployed_profile_count": len(deployable)},
    )


def build_sop_list_report(sops: list[dict[str, Any]]) -> dict[str, Any]:
    scenarios = [str(item.get("scenario")) for item in sops]
    return build_human_report(
        title="内置运维 SOP 清单",
        conclusion=f"已返回 {len(sops)} 条 SOP，适合先按场景选择排障流程。",
        risk_level="low",
        evidence=[f"scenario={item}" for item in scenarios[:8]],
        risk_explanation="SOP 查询只描述排障流程，不执行系统修改。",
        safe_next_steps=[
            "调用 get_ops_sop_tool 查询具体场景。",
            "按 read_only_steps 先采集证据，再生成 request_* dry-run 计划。",
        ],
        details={"scenarios": scenarios},
    )


def build_sop_detail_report(sop: dict[str, Any]) -> dict[str, Any]:
    scenario = str(sop.get("scenario") or "unknown")
    steps = sop.get("read_only_steps") or []
    write_templates = list(sop.get("recommended_write_templates") or [])
    evidence = [
        f"scenario={scenario}",
        f"read_only_steps={len(steps)}",
        f"decision_points={len(sop.get('decision_points') or [])}",
    ]
    evidence.extend(f"write_template={item}" for item in write_templates[:5])
    return build_human_report(
        title=f"{scenario} 标准排障 SOP",
        conclusion=str(sop.get("summary") or f"已返回 {scenario} 的 SOP。"),
        risk_level="low",
        evidence=evidence,
        risk_explanation="该 SOP 只描述排障顺序；修复动作必须走 request_* dry-run、护栏和审批。",
        safe_next_steps=[
            "先按 read_only_steps 调用只读工具收集证据。",
            "如果需要修复，只生成 recommended_write_templates 中的 dry-run 计划。",
        ],
        details={"recommended_write_templates": write_templates},
    )


def build_pipeline_report(
    *,
    scenario: str,
    envelope: dict[str, Any],
    sop: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = envelope.get("data") if isinstance(envelope.get("data"), dict) else {}
    steps = data.get("steps") if isinstance(data.get("steps"), list) else []
    failed = [str(step.get("name")) for step in steps if not step.get("ok")]
    scenario_id = str(data.get("scenario") or scenario)
    evidence = [f"scenario={scenario_id}", f"steps={len(steps)}", f"failed_checks={len(failed)}"]
    evidence.extend(f"failed={item}" for item in failed[:5])
    if sop:
        evidence.append(f"sop_id={sop.get('scenario')}")
    conclusion = str(envelope.get("summary") or f"{scenario_id} 排障流水线已完成。")
    return build_human_report(
        title=f"{scenario_id} 排障结果说明",
        conclusion=conclusion,
        risk_level=str(envelope.get("risk_level") or "medium"),
        ok=bool(envelope.get("ok")),
        evidence=evidence,
        risk_explanation="流水线只做只读诊断；如需修复，应根据 SOP 生成 request_* dry-run 计划。",
        safe_next_steps=list(envelope.get("next_actions") or []),
        details={
            "sop_id": sop.get("scenario") if sop else None,
            "sop_summary": sop.get("summary") if sop else None,
            "failed_checks": failed,
        },
    )


def build_audit_events_report(events: list[dict[str, Any]], limit: int, trace_id: str | None = None) -> dict[str, Any]:
    evidence = [f"events={len(events)}", f"limit={limit}"]
    if trace_id:
        evidence.append(f"trace_id={trace_id}")
    event_types = sorted({str(item.get("event_type")) for item in events if item.get("event_type")})
    evidence.extend(f"event_type={item}" for item in event_types[:5])
    return build_human_report(
        title="审计事件查询结果",
        conclusion=f"已读取 {len(events)} 条审计事件。",
        risk_level="low",
        evidence=evidence,
        risk_explanation="这是只读审计查询，可用于回放 guardrail_decision 和 tool_result。",
        safe_next_steps=["如需串联一次对话，请用 trace_id 过滤查询。"],
        trace_id=trace_id,
        audit_hint="审计事件已包含 prev_hash/event_hash，可继续用 verify_audit_chain_tool 校验。",
        details={"event_types": event_types},
    )


def build_audit_verification_report(title: str, envelope: dict[str, Any]) -> dict[str, Any]:
    data = envelope.get("data") if isinstance(envelope.get("data"), dict) else {}
    verification = data.get("verification") if isinstance(data.get("verification"), dict) else {}
    evidence = [
        f"ok={verification.get('ok')}",
        f"checked_events={verification.get('checked_events')}",
    ]
    if verification.get("anchor_id"):
        evidence.append(f"anchor_id={verification.get('anchor_id')}")
    if verification.get("first_bad_line"):
        evidence.append(f"first_bad_line={verification.get('first_bad_line')}")
    return build_human_report(
        title=title,
        conclusion=str(envelope.get("summary") or "审计校验已完成。"),
        risk_level=str(envelope.get("risk_level") or "low"),
        ok=bool(envelope.get("ok")),
        evidence=[item for item in evidence if not item.endswith("=None")],
        risk_explanation="校验失败通常意味着审计文件被修改、截断、替换，或锚点签名不匹配。",
        safe_next_steps=list(envelope.get("next_actions") or []),
        details={"verification": verification},
    )


def _default_risk_explanation(risk_level: str) -> str:
    mapping = {
        "low": "低风险，只读或信息展示类操作。",
        "medium": "中风险，可能涉及较多系统上下文或诊断扫描。",
        "high": "高风险，真实执行前需要审批和审计。",
        "critical": "严重风险，应默认拒绝，不能通过普通审批绕过。",
    }
    return mapping.get(risk_level, "未知风险等级，需要人工确认。")


def _execution_risk_explanation(guard: Any, risk_level: str) -> str:
    if isinstance(guard, dict) and guard.get("summary"):
        return str(guard["summary"])
    return _default_risk_explanation(risk_level)


def _plan_evidence(plan: dict[str, Any]) -> list[str]:
    keys = ("path", "service", "pid", "process_name", "package", "manager", "port", "protocol", "rule_name", "mode")
    return [f"{key}={plan[key]}" for key in keys if key in plan and plan[key] is not None]


def _least_privilege_summary(least_privilege: dict[str, Any]) -> dict[str, Any]:
    if not least_privilege:
        return {}
    return {
        "template_id": least_privilege.get("template_id"),
        "fixed_template_only": least_privilege.get("fixed_template_only"),
        "recommended_runtime_account": least_privilege.get("recommended_runtime_account"),
        "requires_elevation": least_privilege.get("requires_elevation"),
        "allowed_scopes": list(least_privilege.get("allowed_scopes") or [])[:6],
        "denied_scopes": list(least_privilege.get("denied_scopes") or [])[:6],
        "rollback_strategy": list(least_privilege.get("rollback_strategy") or [])[:4],
    }
