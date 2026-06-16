from __future__ import annotations

import getpass
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ExecutionActionTemplate:
    """写操作固定模板的最小权限声明。

    这里不负责执行命令，而是描述某个动作在受控执行代理中应该怎样被约束。
    """

    template_id: str
    action: str
    summary: str
    platforms: tuple[str, ...]
    recommended_linux_account: str
    recommended_windows_identity: str
    requires_elevation: bool
    allowed_scopes: tuple[str, ...]
    denied_scopes: tuple[str, ...]
    pre_checks: tuple[str, ...]
    post_checks: tuple[str, ...]
    rollback_strategy: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "template_id": self.template_id,
            "action": self.action,
            "summary": self.summary,
            "platforms": list(self.platforms),
            "recommended_linux_account": self.recommended_linux_account,
            "recommended_windows_identity": self.recommended_windows_identity,
            "requires_elevation": self.requires_elevation,
            "allowed_scopes": list(self.allowed_scopes),
            "denied_scopes": list(self.denied_scopes),
            "pre_checks": list(self.pre_checks),
            "post_checks": list(self.post_checks),
            "rollback_strategy": list(self.rollback_strategy),
        }


ACTION_TEMPLATES: dict[str, ExecutionActionTemplate] = {
    "create_directory": ExecutionActionTemplate(
        template_id="TPL_DIRECTORY_CREATE_V1",
        action="create_directory",
        summary="受控目录创建模板，只允许显式目标路径和可选父目录创建。",
        platforms=("linux", "windows"),
        recommended_linux_account="ops-agent",
        recommended_windows_identity="xingxuan-mcp-ops constrained local account",
        requires_elevation=False,
        allowed_scopes=("explicit_directory_path", "create_missing_leaf_directory", "optional_parent_creation"),
        denied_scopes=("system_path", "wildcard_path", "arbitrary_shell", "root_level_sensitive_directory"),
        pre_checks=("path_explicit", "path_not_protected", "path_not_existing_file"),
        post_checks=("directory_exists_after_create", "directory_is_empty_or_new", "record_created_path"),
        rollback_strategy=("remove_created_empty_directory", "manual_review_if_directory_not_empty"),
    ),
    "create_file": ExecutionActionTemplate(
        template_id="TPL_FILE_CREATE_V1",
        action="create_file",
        summary="Create a text file with optional initial content using a fixed template.",
        platforms=("linux", "windows"),
        recommended_linux_account="ops-agent",
        recommended_windows_identity="xingxuan-mcp-ops constrained local account",
        requires_elevation=False,
        allowed_scopes=("explicit_file_path", "text_file_creation", "optional_parent_creation", "optional_existing_file_overwrite"),
        denied_scopes=("system_path", "wildcard_path", "binary_write", "arbitrary_shell"),
        pre_checks=("path_explicit", "path_not_protected", "parent_exists_or_creation_allowed", "existing_target_requires_explicit_overwrite"),
        post_checks=("file_exists_after_create", "file_is_regular_after_create", "optional_hash_after_write"),
        rollback_strategy=("remove_created_file", "restore_backup_if_overwritten", "manual_review_if_rollback_fails"),
    ),
    "modify_file": ExecutionActionTemplate(
        template_id="TPL_FILE_MODIFY_V1",
        action="modify_file",
        summary="受控文本修改模板，要求明确文件、明确操作、可选备份。",
        platforms=("linux", "windows"),
        recommended_linux_account="ops-agent",
        recommended_windows_identity="xingxuan-mcp-ops constrained local account",
        requires_elevation=False,
        allowed_scopes=("explicit_existing_file", "single_file_text_operation", "backup_before_write"),
        denied_scopes=("system_boot_files", "auth_files", "wildcard_path", "binary_overwrite", "arbitrary_shell"),
        pre_checks=("file_exists", "file_is_regular", "path_not_protected", "operation_in_allowlist"),
        post_checks=("record_new_size", "record_backup_path", "optional_hash_after_write"),
        rollback_strategy=("restore_backup_file", "compare_pre_post_hash", "manual_review_if_restore_fails"),
    ),
    "delete_file": ExecutionActionTemplate(
        template_id="TPL_FILE_CLEANUP_V1",
        action="delete_file",
        summary="文件清理模板，默认 quarantine/archive，永久 delete 需额外审批。",
        platforms=("linux", "windows"),
        recommended_linux_account="ops-agent",
        recommended_windows_identity="xingxuan-mcp-ops constrained local account",
        requires_elevation=False,
        allowed_scopes=("explicit_path", "quarantine", "archive", "single_log_truncate"),
        denied_scopes=("root_path", "system_path", "database_path", "wildcard_path", "recursive_without_approval"),
        pre_checks=("path_exists", "path_not_protected", "mode_in_allowlist", "directory_requires_recursive_flag"),
        post_checks=("record_result_path", "record_remaining_free_space", "verify_source_removed_or_truncated"),
        rollback_strategy=("restore_from_quarantine", "restore_from_archive", "truncate_is_not_fully_reversible"),
    ),
    "purge_quarantine_entry": ExecutionActionTemplate(
        template_id="TPL_QUARANTINE_PURGE_V1",
        action="purge_quarantine_entry",
        summary="Permanently remove an explicit entry from the managed xingxuan_mcp quarantine root only.",
        platforms=("linux", "windows"),
        recommended_linux_account="ops-agent",
        recommended_windows_identity="xingxuan-mcp-ops constrained local account",
        requires_elevation=False,
        allowed_scopes=("explicit_quarantine_entry", "managed_xingxuan_mcp_quarantine_root", "single_entry_or_approved_recursive_delete"),
        denied_scopes=("non_quarantine_path", "system_path", "wildcard_path", "arbitrary_shell"),
        pre_checks=("path_exists", "path_under_quarantine_root", "directory_requires_recursive_flag"),
        post_checks=("verify_quarantine_entry_removed", "record_purged_entry_path"),
        rollback_strategy=("purge_is_not_reversible", "restore_only_from_external_backup_or_archive"),
    ),
    "restart_service": ExecutionActionTemplate(
        template_id="TPL_SERVICE_RESTART_V1",
        action="restart_service",
        summary="单服务重启模板，优先要求状态检查和影响窗口说明。",
        platforms=("linux", "windows"),
        recommended_linux_account="ops-agent with limited sudo systemctl rule",
        recommended_windows_identity="PowerShell JEA endpoint for service control",
        requires_elevation=True,
        allowed_scopes=("single_service_name", "fixed_service_manager_command"),
        denied_scopes=("batch_restart", "remote_access_service_without_console", "security_service"),
        pre_checks=("service_name_valid", "service_status_before", "recent_error_log_optional"),
        post_checks=("service_status_after", "recent_error_log_after", "port_or_health_check_optional"),
        rollback_strategy=("service_restart_has_no_direct_rollback", "run_service_diagnostics_on_failure"),
    ),
    "stop_process": ExecutionActionTemplate(
        template_id="TPL_PROCESS_STOP_V1",
        action="stop_process",
        summary="单 PID 停止模板，优先建议通过服务管理工具处理。",
        platforms=("linux", "windows"),
        recommended_linux_account="ops-agent with limited process signal permission",
        recommended_windows_identity="xingxuan-mcp-ops process-control constrained account",
        requires_elevation=True,
        allowed_scopes=("single_pid", "expected_process_name", "terminate_or_kill_only"),
        denied_scopes=("pid_0_or_1", "security_process", "database_process_without_approval", "wildcard_process_name"),
        pre_checks=("pid_exists", "process_name_matches", "parent_process_recorded"),
        post_checks=("pid_absent_or_timeout_recorded", "service_owner_hint_if_detected"),
        rollback_strategy=("process_stop_not_reversible", "restart_owning_service_if_approved"),
    ),
    "change_permissions": ExecutionActionTemplate(
        template_id="TPL_PERMISSION_CHANGE_V1",
        action="change_permissions",
        summary="最小权限修复模板，禁止 777/000 和敏感目录递归。",
        platforms=("linux", "windows"),
        recommended_linux_account="ops-agent with limited chmod/chown sudo rule",
        recommended_windows_identity="PowerShell JEA endpoint for ACL repair",
        requires_elevation=True,
        allowed_scopes=("explicit_path", "single_file_or_approved_directory", "minimal_permission_mode"),
        denied_scopes=("chmod_777", "chmod_000", "protected_path_recursive", "everyone_full_control"),
        pre_checks=("path_exists", "permission_before_recorded", "mode_in_allowlist"),
        post_checks=("permission_after_recorded", "owner_after_recorded"),
        rollback_strategy=("restore_recorded_permission", "restore_recorded_owner_or_acl"),
    ),
    "manage_package": ExecutionActionTemplate(
        template_id="TPL_PACKAGE_MANAGE_V1",
        action="manage_package",
        summary="包管理模板，要求明确包名、包管理器和回滚说明。",
        platforms=("linux", "windows"),
        recommended_linux_account="ops-agent with package-manager sudo allowlist",
        recommended_windows_identity="software management endpoint with package allowlist",
        requires_elevation=True,
        allowed_scopes=("single_package", "trusted_package_manager", "version_recorded"),
        denied_scopes=("curl_pipe_shell", "unsigned_installer", "bulk_remove", "critical_system_package"),
        pre_checks=("package_name_valid", "manager_available", "current_version_recorded"),
        post_checks=("new_version_recorded", "package_manager_exit_code_recorded"),
        rollback_strategy=("reinstall_previous_version_if_available", "document_manual_rollback_for_remove"),
    ),
    "network_policy_change": ExecutionActionTemplate(
        template_id="TPL_NETWORK_POLICY_V1",
        action="network_policy_change",
        summary="防火墙端口策略模板，第一版只允许明确端口 allow/deny。",
        platforms=("linux", "windows"),
        recommended_linux_account="ops-agent with limited firewall-cmd sudo rule",
        recommended_windows_identity="PowerShell JEA endpoint for firewall rule management",
        requires_elevation=True,
        allowed_scopes=("single_port", "tcp_or_udp", "named_rule"),
        denied_scopes=("disable_firewall", "all_ports", "block_remote_admin_port", "clear_all_rules"),
        pre_checks=("port_valid", "protocol_valid", "existing_rule_snapshot"),
        post_checks=("rule_status_after", "port_policy_after"),
        rollback_strategy=("remove_created_rule", "restore_previous_rule_snapshot"),
    ),
}


def get_action_template(action: str) -> ExecutionActionTemplate | None:
    return ACTION_TEMPLATES.get(action)


def list_action_templates() -> list[dict[str, Any]]:
    return [template.to_dict() for template in ACTION_TEMPLATES.values()]


def build_least_privilege_context(action: str, platform_name: str, target: str, plan: dict[str, Any]) -> dict[str, Any]:
    template = get_action_template(action)
    if template is None:
        return {
            "template_id": "UNKNOWN",
            "action": action,
            "enforced": False,
            "reason": "No fixed action template was registered for this action.",
        }

    recommended_account = (
        template.recommended_windows_identity
        if platform_name == "windows"
        else template.recommended_linux_account
    )
    return {
        "template_id": template.template_id,
        "action": action,
        "enforced": True,
        "fixed_template_only": True,
        "target": target,
        "platform": platform_name,
        "current_runtime_user": _safe_current_user(),
        "recommended_runtime_account": recommended_account,
        "requires_elevation": template.requires_elevation,
        "allowed_scopes": list(template.allowed_scopes),
        "denied_scopes": list(template.denied_scopes),
        "pre_checks": list(template.pre_checks),
        "post_checks": list(template.post_checks),
        "rollback_strategy": list(template.rollback_strategy),
        "plan_subject": _plan_subject(plan),
        "notes": [
            "当前版本仍由 MCP 进程生成固定模板计划；生产部署应切换到受限执行账户。",
            "不允许模型传入任意 shell，只允许执行 template_id 对应的固定动作。",
        ],
    }


def _plan_subject(plan: dict[str, Any]) -> dict[str, Any]:
    keys = ("path", "service", "pid", "process_name", "package", "port", "protocol", "rule_name")
    return {key: plan.get(key) for key in keys if key in plan and plan.get(key) is not None}


def _safe_current_user() -> str:
    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001 - 用户名仅用于审计提示，失败不影响主流程
        return "unknown"
