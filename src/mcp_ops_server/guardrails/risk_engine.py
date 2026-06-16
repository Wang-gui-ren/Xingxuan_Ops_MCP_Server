from __future__ import annotations

import json
import re
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any

from mcp_ops_server.guardrails.models import GuardrailDecision, GuardrailFinding, OperationContext
from mcp_ops_server.guardrails.rule_loader import load_guardrail_rules
from mcp_ops_server.guardrails.rule_schema import CompiledGuardrailRule
from mcp_ops_server.guardrails.rules import SAFE_ALTERNATIVES, TOOL_BASE_RISK, WRITE_TOOLS
from mcp_ops_server.models import RiskLevel


RISK_SCORE: dict[RiskLevel, int] = {
    "low": 1,
    "medium": 2,
    "high": 3,
    "critical": 4,
}


def validate_intent(context: OperationContext) -> GuardrailDecision:
    """对 MCP 工具调用进行确定性风险校验。"""

    findings: list[GuardrailFinding] = []
    params_text = _json_dumps(context.params)
    combined_text = "\n".join(
        part
        for part in (
            context.user_intent,
            context.command,
            context.path,
            params_text,
        )
        if part
    )
    rule_set = load_guardrail_rules()

    findings.extend(_scan_configured_text_rules(combined_text, rule_set.text_rules()))
    findings.extend(_scan_paths(context, rule_set.path_rules()))
    findings.extend(_scan_tool_params(context))
    findings.extend(_scan_external_guard(context))
    findings.extend(_scan_tool_base_risk(context))

    highest = _highest_risk(findings)
    if highest == "critical":
        return GuardrailDecision(
            allowed=False,
            decision="deny",
            risk_level="critical",
            requires_approval=False,
            summary="安全校验拒绝：检测到 critical 风险，不能通过审批绕过。",
            findings=findings,
            safe_alternatives=SAFE_ALTERNATIVES,
        )

    if highest == "high":
        if context.approval_id:
            return GuardrailDecision(
                allowed=True,
                decision="allow",
                risk_level="high",
                requires_approval=False,
                summary="安全校验通过：高风险操作已提供 approval_id。",
                findings=findings,
                safe_alternatives=SAFE_ALTERNATIVES,
            )
        if context.dry_run:
            return GuardrailDecision(
                allowed=True,
                decision="require_approval",
                risk_level="high",
                requires_approval=True,
                summary="安全校验提示：允许生成 dry-run 计划，但真实执行前需要 approval_id。",
                findings=findings,
                safe_alternatives=SAFE_ALTERNATIVES,
            )
        return GuardrailDecision(
            allowed=False,
            decision="require_approval",
            risk_level="high",
            requires_approval=True,
            summary="安全校验阻断：高风险真实执行缺少 approval_id。",
            findings=findings,
            safe_alternatives=SAFE_ALTERNATIVES,
        )

    if highest == "medium":
        return GuardrailDecision(
            allowed=True,
            decision="allow",
            risk_level="medium",
            requires_approval=False,
            summary="安全校验通过：检测到 medium 风险，请限制范围并保留审计。",
            findings=findings,
            safe_alternatives=SAFE_ALTERNATIVES[:2],
        )

    return GuardrailDecision(
        allowed=True,
        decision="allow",
        risk_level="low",
        requires_approval=False,
        summary="安全校验通过：未检测到高风险意图。",
        findings=findings,
        safe_alternatives=[],
    )


def _scan_configured_text_rules(text: str, rules: tuple[CompiledGuardrailRule, ...]) -> list[GuardrailFinding]:
    findings: list[GuardrailFinding] = []
    for rule in rules:
        for match in rule.pattern.finditer(text):
            findings.append(
                GuardrailFinding(
                    rule_id=rule.id,
                    category=rule.category,
                    risk_level=rule.risk_level,
                    message=_rule_message(rule),
                    evidence=_clip(match.group(0)),
                    recommendation=rule.recommendation,
                )
            )
    return findings


def _scan_paths(context: OperationContext, rules: tuple[CompiledGuardrailRule, ...]) -> list[GuardrailFinding]:
    paths = _extract_candidate_paths(context)
    findings: list[GuardrailFinding] = []
    for path in paths:
        normalized = _normalize_path(path)
        if not normalized:
            continue
        for rule in rules:
            for match in rule.pattern.finditer(normalized):
                findings.append(
                    GuardrailFinding(
                        rule_id=rule.id,
                        category=rule.category,
                        risk_level=rule.risk_level,
                        message=_rule_message(rule),
                        evidence=_clip(match.group(0) or path),
                        recommendation=rule.recommendation,
                    )
                )
    return findings


def _scan_tool_params(context: OperationContext) -> list[GuardrailFinding]:
    params = context.params
    findings: list[GuardrailFinding] = []
    tool_name = context.tool_name

    if tool_name == "request_delete_file":
        mode = str(params.get("mode") or "")
        recursive = bool(params.get("recursive"))
        if mode == "delete":
            findings.append(_finding("TOOL_DELETE_MODE", "destructive_command", "high", "请求永久删除文件。", mode, "优先使用 quarantine 或 archive。"))
        if recursive:
            findings.append(_finding("TOOL_RECURSIVE_DELETE", "scope_expansion", "high", "请求递归删除或清理。", str(params), "递归操作必须审批并限制路径。"))
        # 删除前应先读取文件内容以便审批人评估影响
        findings.append(_finding("READ_BEFORE_DELETE", "content_risk", "medium", "删除操作：审批前应先读取目标文件内容，评估数据丢失影响。", str(params.get("path") or ""), "调用 get_file_stat_tool 或 read_file_tool 读取内容后再提交审批。"))

    if tool_name == "request_modify_file":
        replacement = params.get("replacement") or params.get("content") or params.get("line") or params.get("value") or ""
        if replacement:
            findings.append(_finding("CONTENT_REVIEW_REQUIRED", "content_risk", "medium", "写入操作包含内容，需对写入内容进行安全审查。", str(replacement)[:120], "审批人或 LLM 应检查写入内容是否包含敏感数据、恶意代码或越权配置。"))

    if tool_name == "request_create_file":
        content = params.get("content") or ""
        if content:
            findings.append(
                _finding(
                    "CREATE_FILE_CONTENT_REVIEW_REQUIRED",
                    "content_risk",
                    "medium",
                    "Request creates a file with initial content that should be reviewed before approval.",
                    str(content)[:120],
                    "Confirm the initial content does not include secrets, malicious code, or unsafe configuration.",
                )
            )
        if bool(params.get("create_parents")):
            findings.append(
                _finding(
                    "CREATE_FILE_PARENT_SCOPE_EXPANSION",
                    "scope_expansion",
                    "high",
                    "Request may create missing parent directories before writing the file.",
                    str(params),
                    "Review the full target path and confirm the parent directory expansion is intended.",
                )
            )
        if bool(params.get("overwrite_if_exists")):
            findings.append(
                _finding(
                    "CREATE_FILE_OVERWRITE",
                    "destructive_command",
                    "high",
                    "Request may overwrite an existing file.",
                    str(params.get("path") or ""),
                    "Confirm rollback expectations and whether a backup will be retained before approval.",
                )
            )

    if tool_name == "request_purge_quarantine_entry":
        recursive = bool(params.get("recursive"))
        findings.append(
            _finding(
                "TOOL_QUARANTINE_PURGE",
                "destructive_command",
                "high",
                "Request to permanently purge a quarantine entry.",
                str(params.get("path") or ""),
                "Confirm the entry is already quarantined and no longer needed before approval.",
            )
        )
        if recursive:
            findings.append(
                _finding(
                    "TOOL_RECURSIVE_QUARANTINE_PURGE",
                    "scope_expansion",
                    "high",
                    "Request to recursively purge a quarantine directory.",
                    str(params),
                    "Review directory contents carefully before approving recursive purge.",
                )
            )

    if tool_name == "request_create_directory":
        create_parents = bool(params.get("create_parents"))
        if create_parents:
            findings.append(
                _finding(
                    "TOOL_CREATE_DIRECTORY_PARENTS",
                    "scope_expansion",
                    "high",
                    "请求自动创建缺失父目录。",
                    str(params),
                    "确认目标路径范围，并避免在受保护目录下自动扩展层级。",
                )
            )

    if tool_name == "request_log_cleanup":
        mode = str(params.get("mode") or "")
        if mode == "truncate":
            findings.append(_finding("TOOL_LOG_TRUNCATE", "destructive_command", "high", "请求截断日志文件。", mode, "优先 archive，并确认不是数据库或审计日志。"))

    if tool_name == "request_change_permissions":
        mode = str(params.get("mode") or "")
        recursive = bool(params.get("recursive"))
        if mode in {"777", "0777", "000", "0000"}:
            findings.append(_finding("TOOL_UNSAFE_PERMISSION_MODE", "permission_escalation", "critical", "请求危险权限模式。", mode, "使用最小权限模式，例如 0640。"))
        if recursive:
            findings.append(_finding("TOOL_RECURSIVE_PERMISSION", "permission_escalation", "high", "请求递归修改权限。", str(params), "递归权限变更必须审批。"))

    if tool_name == "request_stop_process":
        pid = _int_or_none(params.get("pid"))
        if pid is not None and pid <= 1:
            findings.append(_finding("TOOL_STOP_CRITICAL_PID", "service_disruption", "critical", "请求停止关键 PID。", str(pid), "不能停止 PID 0 或 PID 1。"))

    if tool_name == "request_network_policy_change":
        port = _int_or_none(params.get("port"))
        action = str(params.get("action") or "").lower()
        if port in {22, 3389, 5985, 5986} and action in {"deny", "block", "close", "remove", "deny_port", "block_port"}:
            findings.append(_finding("TOOL_BLOCK_ADMIN_PORT", "service_disruption", "critical", "请求阻断远程管理端口。", f"{action}:{port}", "远程管理端口变更必须人工处理。"))

    if tool_name == "request_manage_package" and str(params.get("action") or "") == "remove":
        findings.append(_finding("TOOL_PACKAGE_REMOVE", "service_disruption", "high", "请求卸载软件包。", str(params.get("package")), "卸载前需要确认依赖和回滚方案。"))

    return findings


def _scan_external_guard(context: OperationContext) -> list[GuardrailFinding]:
    guard = context.external_guard
    if not guard:
        return []
    if guard.action == "block":
        return [
            GuardrailFinding(
                rule_id="EXTERNAL_GUARD_BLOCK",
                category="external_guard",
                risk_level="critical",
                message="上游护栏已要求阻断该操作。",
                evidence=guard.reason or guard.provider,
                recommendation="保持阻断，并关联上游审计记录。",
            )
        ]
    if guard.action in {"confirm", "review"} or guard.risk_level == "high":
        return [
            GuardrailFinding(
                rule_id="EXTERNAL_GUARD_REVIEW",
                category="external_guard",
                risk_level="high",
                message="上游护栏建议人工确认或审批。",
                evidence=guard.reason or guard.provider,
                recommendation="要求 approval_id 或仅允许 dry-run。",
            )
        ]
    return []


def _scan_tool_base_risk(context: OperationContext) -> list[GuardrailFinding]:
    risk = TOOL_BASE_RISK.get(context.tool_name)
    if not risk:
        return []
    if context.tool_name in WRITE_TOOLS:
        return [
            GuardrailFinding(
                rule_id="TOOL_BASE_RISK",
                category="tool_risk",
                risk_level=risk,
                message="该 MCP 工具属于写操作申请工具。",
                evidence=context.tool_name,
                recommendation="默认 dry-run；真实执行需要审批与审计。",
            )
        ]
    return []


def _extract_candidate_paths(context: OperationContext) -> list[str]:
    candidates: list[str] = []
    if context.path:
        candidates.append(context.path)
    for key in ("path", "root_path", "log_path", "file", "target_path"):
        value = context.params.get(key)
        if isinstance(value, str):
            candidates.append(value)
    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = _normalize_path(candidate)
        if normalized and normalized not in seen:
            seen.add(normalized)
            deduped.append(candidate)
    return deduped


def _normalize_path(path: str) -> str:
    text = path.strip().strip("'\"")
    if not text:
        return ""
    if re.match(r"^[A-Za-z]:[\\/]", text):
        return str(PureWindowsPath(text)).lower()
    if text.startswith("/") or text.startswith("~"):
        return str(PurePosixPath(text))
    return text.replace("/", "\\").lower() if "\\" in text else text


def _highest_risk(findings: list[GuardrailFinding]) -> RiskLevel:
    if not findings:
        return "low"
    return max((finding.risk_level for finding in findings), key=lambda risk: RISK_SCORE[risk])


def _finding(rule_id: str, category: str, risk: RiskLevel, message: str, evidence: str, recommendation: str) -> GuardrailFinding:
    return GuardrailFinding(rule_id=rule_id, category=category, risk_level=risk, message=message, evidence=_clip(evidence), recommendation=recommendation)


def _json_dumps(payload: dict[str, Any]) -> str:
    try:
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    except TypeError:
        return str(payload)


def _clip(text: str, limit: int = 240) -> str:
    compact = " ".join(str(text).split())
    return compact if len(compact) <= limit else compact[:limit] + "...<truncated>"


def _rule_message(rule: CompiledGuardrailRule) -> str:
    description = rule.definition.description or f"命中配置化安全规则 {rule.id}。"
    return f"{description} source={rule.source}; version={rule.version}"


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
