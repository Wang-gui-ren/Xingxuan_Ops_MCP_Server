from __future__ import annotations

from mcp_ops_server.models import RiskLevel


TOOL_BASE_RISK: dict[str, RiskLevel] = {
    "request_create_directory": "medium",
    "request_create_file": "high",
    "request_modify_file": "high",
    "request_delete_file": "high",
    "request_purge_quarantine_entry": "high",
    "request_restart_service": "high",
    "request_stop_process": "high",
    "request_change_permissions": "high",
    "request_manage_package": "high",
    "request_network_policy_change": "high",
    "request_log_cleanup": "high",
    "validate_operation_intent_tool": "low",
    "get_audit_events_tool": "low",
}

WRITE_TOOLS = {
    "request_create_directory",
    "request_create_file",
    "request_modify_file",
    "request_delete_file",
    "request_purge_quarantine_entry",
    "request_restart_service",
    "request_stop_process",
    "request_change_permissions",
    "request_manage_package",
    "request_network_policy_change",
    "request_log_cleanup",
}

SAFE_ALTERNATIVES = [
    "先调用只读诊断工具收集证据，例如 get_file_stat_tool、detect_large_logs_tool、get_service_status_tool。",
    "保持 dry_run=true 生成计划，不直接修改系统。",
    "对 high 风险操作补充 approval_id 后再考虑真实执行。",
    "critical 风险需要人工运维处理，不能由当前 Agent 自动执行。",
]
