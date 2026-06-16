from __future__ import annotations

import getpass
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mcp_ops_server.branding import DEFAULT_LINUX_MANAGED_ROOT, DEFAULT_WINDOWS_MANAGED_ROOT, get_prefixed_env
from mcp_ops_server.execution.action_templates import ExecutionActionTemplate, get_action_template
from mcp_ops_server.execution.agents import (
    DENIED_AGENT_REQUEST_KEYS,
    ExecutionAgentProfile,
    resolve_execution_agent_profile,
    validate_agent_profile_for_template,
)
from mcp_ops_server.models import RiskLevel
from mcp_ops_server.utils.platform import current_platform


LOCAL_TARGETS = {"", "local", "localhost", "127.0.0.1", "::1"}
OPERATION_ACTION_ALIASES = {
    # 日志清理复用文件清理模板，避免为同一类动作维护两套权限边界。
    "log_cleanup": "delete_file",
}
SAFE_FILE_MODIFY_OPERATIONS = {"replace_text", "append_line", "set_key_value", "comment_line", "overwrite"}
SAFE_FILE_CLEANUP_MODES = {"archive", "quarantine", "truncate"}
NETWORK_ACTION_ALIASES = {
    "allow": "allow_port",
    "open": "allow_port",
    "add": "allow_port",
    "permit": "allow_port",
    "enable": "allow_port",
    "allow_port": "allow_port",
    "open_port": "allow_port",
    "deny": "deny_port",
    "block": "deny_port",
    "close": "deny_port",
    "remove": "deny_port",
    "drop": "deny_port",
    "disable": "deny_port",
    "deny_port": "deny_port",
    "block_port": "deny_port",
    "close_port": "deny_port",
}
AGENT_REQUEST_PARAM_KEYS = {
    "create_directory": frozenset({"path", "create_parents"}),
    "create_file": frozenset({"path", "content", "overwrite_if_exists", "create_parents"}),
    "modify_file": frozenset({"path", "operation", "match", "replacement", "line", "key", "value"}),
    "delete_file": frozenset({"path", "mode", "recursive"}),
    "purge_quarantine_entry": frozenset({"path", "recursive"}),
    "restart_service": frozenset({"service"}),
    "stop_process": frozenset({"pid", "signal_name"}),
    "change_permissions": frozenset({"path", "mode", "recursive"}),
    "manage_package": frozenset({"package", "action", "manager"}),
    "network_policy_change": frozenset({"action", "protocol", "port", "rule_name"}),
}
REMOTE_REFERENCE_PARAM_KEYS = frozenset({"remote_username", "remote_port", "remote_auth_ref", "remote_endpoint"})
REMOTE_ADMIN_PORTS = {22, 3389, 5985, 5986}
SERVICE_NAME_RE = re.compile(r"^[A-Za-z0-9_.@:-]{1,128}$")
PACKAGE_NAME_RE = re.compile(r"^[A-Za-z0-9_.+:-]{1,160}$")
RULE_NAME_RE = re.compile(r"^[A-Za-z0-9_.@(): -]{0,160}$")
WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]*$")
PROTECTED_POSIX_PATHS = (
    "/",
    "/bin",
    "/boot",
    "/dev",
    "/etc",
    "/lib",
    "/lib64",
    "/proc",
    "/root",
    "/sbin",
    "/sys",
    "/usr",
    "/var/lib",
    "/var/log/audit",
)
PROTECTED_WINDOWS_PREFIXES = (
    "c:\\windows",
    "c:\\program files",
    "c:\\program files (x86)",
    "c:\\programdata\\microsoft",
)


def _managed_tmp_mcp_root(platform_name: str) -> Path:
    configured = get_prefixed_env("TMP_MCP_MANAGED_ROOT")
    if configured:
        return Path(configured)
    return DEFAULT_WINDOWS_MANAGED_ROOT if platform_name == "windows" else DEFAULT_LINUX_MANAGED_ROOT


def _quarantine_root(platform_name: str) -> Path:
    return (_managed_tmp_mcp_root(platform_name) / "quarantine").resolve()


def _is_within_root(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


@dataclass(frozen=True)
class ExecutionValidation:
    """真实执行前的最小权限校验结果。"""

    ok: bool
    decision: str
    risk_level: RiskLevel
    summary: str
    action: str
    template_id: str | None
    platform: str
    target: str
    dry_run: bool
    runtime_identity: str
    recommended_runtime_account: str | None
    template_ok: bool
    platform_ok: bool
    target_ok: bool
    approval_ok: bool
    identity_ok: bool
    scope_ok: bool
    pre_checks_ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checks: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "decision": self.decision,
            "risk_level": self.risk_level,
            "summary": self.summary,
            "action": self.action,
            "template_id": self.template_id,
            "platform": self.platform,
            "target": self.target,
            "dry_run": self.dry_run,
            "runtime_identity": self.runtime_identity,
            "recommended_runtime_account": self.recommended_runtime_account,
            "template_ok": self.template_ok,
            "platform_ok": self.platform_ok,
            "target_ok": self.target_ok,
            "approval_ok": self.approval_ok,
            "identity_ok": self.identity_ok,
            "scope_ok": self.scope_ok,
            "pre_checks_ok": self.pre_checks_ok,
            "errors": self.errors,
            "warnings": self.warnings,
            "checks": self.checks,
        }


class ExecutionPolicy:
    """真实执行前的固定模板、审批、身份和范围校验闸门。

    当前版本只做本地、固定模板、保守执行前校验，不开放任意 shell。
    需要提权的模板默认阻断，直到部署 Linux sudoers allowlist 或 Windows JEA。
    """

    def __init__(
        self,
        *,
        allow_privileged_execution: bool | None = None,
        trusted_identities: set[str] | None = None,
        execution_agent_profile: ExecutionAgentProfile | None = None,
    ) -> None:
        self.allow_privileged_execution = (
            _env_flag("TMP_MCP_ENABLE_PRIVILEGED_EXECUTION")
            if allow_privileged_execution is None
            else allow_privileged_execution
        )
        self.trusted_identities = (
            {item.lower() for item in trusted_identities}
            if trusted_identities is not None
            else _trusted_identities_from_env()
        )
        self.execution_agent_profile = (
            execution_agent_profile
            if execution_agent_profile is not None
            else resolve_execution_agent_profile(get_prefixed_env("TMP_MCP_EXECUTION_AGENT_PROFILE"))
        )

    def validate(
        self,
        *,
        tool_name: str,
        operation: str,
        target: str,
        platform_hint: str,
        params: dict[str, Any],
        dry_run: bool,
        approval_validation: Any | None = None,
    ) -> ExecutionValidation:
        action = OPERATION_ACTION_ALIASES.get(operation, operation)
        platform_name = _normalize_platform(platform_hint)
        target_text = str(target or "local")
        runtime_identity = _safe_current_user()
        template = get_action_template(action)
        template_ok = template is not None
        platform_ok = bool(template and platform_name in template.platforms)
        target_ok = target_text in LOCAL_TARGETS
        approval_ok, approval_errors = _validate_approval(dry_run=dry_run, approval_validation=approval_validation)

        errors: list[str] = []
        warnings: list[str] = []
        checks: dict[str, Any] = {
            "tool_name": tool_name,
            "operation": operation,
            "normalized_action": action,
            "approval_required_for_real_execution": not dry_run,
        }
        errors.extend(approval_errors)

        if template is None:
            errors.append(f"template_not_found: action={action}")
            recommended_runtime_account = None
            identity_ok = False
            scope_ok = False
            pre_checks_ok = False
        else:
            recommended_runtime_account = _recommended_identity(template, platform_name)
            if not platform_ok:
                errors.append(f"platform_not_supported: action={action}, platform={platform_name}")
            if not target_ok:
                errors.append(f"remote_target_not_supported: target={target_text}")

            identity_ok, identity_errors, identity_warnings, identity_checks = self._validate_identity(
                template=template,
                platform_name=platform_name,
                params=params,
                runtime_identity=runtime_identity,
                dry_run=dry_run,
            )
            scope_ok, scope_errors, scope_warnings, scope_checks = _validate_scope(
                action=action,
                operation=operation,
                params=params,
                platform_name=platform_name,
            )
            pre_checks_ok, pre_check_errors, pre_check_warnings, pre_checks = _validate_pre_checks(
                action=action,
                operation=operation,
                params=params,
                dry_run=dry_run,
            )
            errors.extend(identity_errors)
            errors.extend(scope_errors)
            errors.extend(pre_check_errors)
            warnings.extend(identity_warnings)
            warnings.extend(scope_warnings)
            warnings.extend(pre_check_warnings)
            checks["identity"] = identity_checks
            checks["scope"] = scope_checks
            checks["pre_checks"] = pre_checks

        ok = all((template_ok, platform_ok, target_ok, approval_ok, identity_ok, scope_ok, pre_checks_ok))
        if dry_run:
            decision = "allow_dry_run"
            summary = "执行策略校验通过：dry-run 不触发真实最小权限身份校验。"
        elif ok:
            decision = "allow"
            summary = "执行策略校验通过：固定模板、审批、身份、范围和前置检查均满足。"
        else:
            decision = "block"
            summary = "执行策略阻断：真实执行前的最小权限校验未通过。"

        return ExecutionValidation(
            ok=ok,
            decision=decision,
            risk_level="low" if dry_run else "high",
            summary=summary,
            action=action,
            template_id=template.template_id if template else None,
            platform=platform_name,
            target=target_text,
            dry_run=dry_run,
            runtime_identity=runtime_identity,
            recommended_runtime_account=recommended_runtime_account,
            template_ok=template_ok,
            platform_ok=platform_ok,
            target_ok=target_ok,
            approval_ok=approval_ok,
            identity_ok=identity_ok,
            scope_ok=scope_ok,
            pre_checks_ok=pre_checks_ok,
            errors=errors,
            warnings=warnings,
            checks=checks,
        )

    def _validate_identity(
        self,
        *,
        template: ExecutionActionTemplate,
        platform_name: str,
        params: dict[str, Any],
        runtime_identity: str,
        dry_run: bool,
    ) -> tuple[bool, list[str], list[str], dict[str, Any]]:
        checks: dict[str, Any] = {
            "runtime_identity": runtime_identity,
            "requires_elevation": template.requires_elevation,
            "allow_privileged_execution": self.allow_privileged_execution,
            "trusted_identities_configured": bool(self.trusted_identities),
        }
        if dry_run:
            checks["agent_profile_required"] = False
            return True, [], ["dry_run=true，跳过真实执行身份校验。"], checks

        if not template.requires_elevation:
            checks["agent_profile_required"] = False
            return True, [], [
                "当前模板不需要提权；生产环境仍建议切换到受限 ops-agent/JEA 身份运行。",
            ], checks

        checks["agent_profile_required"] = True
        errors: list[str] = []
        warnings: list[str] = []
        if not self.allow_privileged_execution:
            errors.append(
                "privileged_template_disabled: 需要提权的模板尚未启用真实最小权限执行代理。"
            )
            warnings.append(
                "如需放开，请先部署 Linux sudoers allowlist 或 Windows JEA，再显式配置 XINGXUAN_MCP_ENABLE_PRIVILEGED_EXECUTION=true。",
            )

        agent_ok, agent_errors, agent_warnings, agent_checks = validate_agent_profile_for_template(
            profile=self.execution_agent_profile,
            template_id=template.template_id,
            action=template.action,
            platform_name=platform_name,
            params=_agent_preflight_params(template.action, params),
            runtime_identity=runtime_identity,
            trusted_identities=self.trusted_identities,
        )
        checks["agent_profile"] = agent_checks
        if not agent_ok:
            errors.extend(agent_errors)
            warnings.extend(agent_warnings)

        if errors:
            return False, errors, warnings, checks

        return True, [], [
            f"已启用提权模板执行，当前身份 {runtime_identity} 被受限执行代理档案允许。",
        ], checks


def _validate_approval(*, dry_run: bool, approval_validation: Any | None) -> tuple[bool, list[str]]:
    if dry_run:
        return True, []
    if approval_validation is None:
        return False, ["missing_approval_validation: 真实执行必须先完成审批账本校验。"]
    if isinstance(approval_validation, dict):
        ok = bool(approval_validation.get("ok"))
        errors = list(approval_validation.get("errors") or [])
    else:
        ok = bool(getattr(approval_validation, "ok", False))
        errors = list(getattr(approval_validation, "errors", []) or [])
    if ok:
        return True, []
    return False, errors or ["approval_validation_failed"]


def _validate_scope(
    *,
    action: str,
    operation: str,
    params: dict[str, Any],
    platform_name: str,
) -> tuple[bool, list[str], list[str], dict[str, Any]]:
    if action == "create_directory":
        return _validate_create_directory_scope(params, platform_name)
    if action == "create_file":
        return _validate_create_file_scope(params, platform_name)
    if action == "modify_file":
        return _validate_modify_file_scope(params, platform_name)
    if action == "delete_file":
        return _validate_delete_file_scope(params, platform_name)
    if action == "purge_quarantine_entry":
        return _validate_purge_quarantine_scope(params, platform_name)
    if action == "restart_service":
        service = str(params.get("service") or "")
        ok = bool(SERVICE_NAME_RE.fullmatch(service))
        return ok, ([] if ok else [f"invalid_service_name: {service}"]), [], {"service": service}
    if action == "stop_process":
        return _validate_stop_process_scope(params)
    if action == "change_permissions":
        return _validate_permission_scope(params, platform_name)
    if action == "manage_package":
        return _validate_package_scope(params)
    if action == "network_policy_change":
        return _validate_network_scope(params)
    return False, [f"scope_validator_missing: operation={operation}, action={action}"], [], {}


def _validate_create_directory_scope(params: dict[str, Any], platform_name: str) -> tuple[bool, list[str], list[str], dict[str, Any]]:
    errors: list[str] = []
    warnings: list[str] = []
    path = str(params.get("path") or "")
    create_parents = bool(params.get("create_parents"))
    errors.extend(_path_scope_errors(path, platform_name))
    if create_parents:
        warnings.append("自动创建父目录会扩大操作范围，真实执行前应再次确认目标路径。")
    return not errors, errors, warnings, {"path": path, "create_parents": create_parents}


def _validate_create_file_scope(params: dict[str, Any], platform_name: str) -> tuple[bool, list[str], list[str], dict[str, Any]]:
    errors: list[str] = []
    warnings: list[str] = []
    path = str(params.get("path") or "")
    create_parents = bool(params.get("create_parents"))
    overwrite_if_exists = bool(params.get("overwrite_if_exists"))
    errors.extend(_path_scope_errors(path, platform_name))
    if create_parents:
        warnings.append("Automatic parent creation expands the write scope and should be reviewed before execution.")
    if overwrite_if_exists:
        warnings.append("Overwriting an existing file is destructive and should only be approved when rollback is understood.")
    return not errors, errors, warnings, {
        "path": path,
        "create_parents": create_parents,
        "overwrite_if_exists": overwrite_if_exists,
    }


def _validate_modify_file_scope(params: dict[str, Any], platform_name: str) -> tuple[bool, list[str], list[str], dict[str, Any]]:
    errors: list[str] = []
    operation = str(params.get("operation") or "")
    path = str(params.get("path") or "")
    if operation not in SAFE_FILE_MODIFY_OPERATIONS:
        errors.append(f"unsupported_file_operation: {operation}")
    if operation in {"replace_text", "set_key_value", "comment_line"} and not params.get("match"):
        errors.append("missing_match: selected operation requires match.")
    errors.extend(_path_scope_errors(path, platform_name))
    return not errors, errors, [], {"path": path, "operation": operation}


def _validate_delete_file_scope(params: dict[str, Any], platform_name: str) -> tuple[bool, list[str], list[str], dict[str, Any]]:
    errors: list[str] = []
    warnings: list[str] = []
    path = str(params.get("path") or "")
    mode = str(params.get("mode") or "quarantine")
    recursive = bool(params.get("recursive"))
    if mode not in SAFE_FILE_CLEANUP_MODES:
        errors.append(f"unsafe_cleanup_mode_disabled_by_policy: {mode}")
    if recursive and mode == "truncate":
        errors.append("recursive_truncate_not_supported")
    if recursive:
        warnings.append("递归清理需要额外人工确认，当前策略仅允许安全归档/隔离路径。")
    errors.extend(_path_scope_errors(path, platform_name))
    return not errors, errors, warnings, {"path": path, "mode": mode, "recursive": recursive}


def _validate_purge_quarantine_scope(params: dict[str, Any], platform_name: str) -> tuple[bool, list[str], list[str], dict[str, Any]]:
    errors: list[str] = []
    warnings: list[str] = []
    path = str(params.get("path") or "")
    recursive = bool(params.get("recursive"))
    errors.extend(_path_scope_errors(path, platform_name))
    if path:
        quarantine_root = _quarantine_root(platform_name)
        candidate = Path(path).expanduser()
        if not _is_within_root(candidate, quarantine_root):
            errors.append(f"path_not_in_quarantine_root: {path}")
        elif candidate.resolve() == quarantine_root:
            errors.append("quarantine_root_self_purge_denied")
    if recursive:
        warnings.append("Recursive quarantine purge expands impact and should be reviewed carefully.")
    return not errors, errors, warnings, {"path": path, "recursive": recursive}


def _validate_stop_process_scope(params: dict[str, Any]) -> tuple[bool, list[str], list[str], dict[str, Any]]:
    errors: list[str] = []
    pid = _int_or_none(params.get("pid"))
    signal_name = str(params.get("signal_name") or "terminate")
    if pid is None:
        errors.append("pid_required")
    elif pid <= 1:
        errors.append(f"critical_pid_denied: {pid}")
    if signal_name not in {"terminate", "kill"}:
        errors.append(f"unsupported_signal: {signal_name}")
    return not errors, errors, [], {"pid": pid, "signal_name": signal_name}


def _validate_permission_scope(params: dict[str, Any], platform_name: str) -> tuple[bool, list[str], list[str], dict[str, Any]]:
    errors: list[str] = []
    path = str(params.get("path") or "")
    mode = str(params.get("mode") or "")
    recursive = bool(params.get("recursive"))
    errors.extend(_path_scope_errors(path, platform_name))
    if platform_name == "windows":
        if mode and mode.upper() not in {"R", "RX", "W", "M"}:
            errors.append(f"unsafe_windows_acl_mode: {mode}")
    else:
        if mode and not re.fullmatch(r"[0-7]{3,4}", mode):
            errors.append(f"invalid_posix_mode: {mode}")
        if mode in {"777", "0777", "000", "0000"}:
            errors.append(f"unsafe_posix_mode: {mode}")
    if recursive and _is_protected_path(path, platform_name):
        errors.append("recursive_permission_change_on_protected_path_denied")
    return not errors, errors, [], {"path": path, "mode": mode, "recursive": recursive}


def _validate_package_scope(params: dict[str, Any]) -> tuple[bool, list[str], list[str], dict[str, Any]]:
    errors: list[str] = []
    package = str(params.get("package") or "")
    action = str(params.get("action") or "")
    if not PACKAGE_NAME_RE.fullmatch(package):
        errors.append(f"invalid_package_name: {package}")
    if action not in {"install", "upgrade", "remove"}:
        errors.append(f"unsupported_package_action: {action}")
    return not errors, errors, [], {"package": package, "action": action, "manager": params.get("manager")}


def _validate_network_scope(params: dict[str, Any]) -> tuple[bool, list[str], list[str], dict[str, Any]]:
    errors: list[str] = []
    action = NETWORK_ACTION_ALIASES.get(str(params.get("action") or "").strip().lower().replace("-", "_"), "")
    protocol = str(params.get("protocol") or "").lower()
    port = _int_or_none(params.get("port"))
    rule_name = str(params.get("rule_name") or "")
    if action not in {"allow_port", "deny_port"}:
        errors.append(f"unsupported_network_action: {params.get('action')}")
    if protocol not in {"tcp", "udp"}:
        errors.append(f"unsupported_protocol: {protocol}")
    if port is None or not 1 <= port <= 65535:
        errors.append(f"invalid_port: {params.get('port')}")
    if port in REMOTE_ADMIN_PORTS and action == "deny_port":
        errors.append(f"deny_remote_admin_port_denied: {port}")
    if rule_name and not RULE_NAME_RE.fullmatch(rule_name):
        errors.append(f"unsafe_rule_name: {rule_name}")
    return not errors, errors, [], {"action": action, "protocol": protocol, "port": port, "rule_name": rule_name}


def _validate_pre_checks(
    *,
    action: str,
    operation: str,
    params: dict[str, Any],
    dry_run: bool,
) -> tuple[bool, list[str], list[str], dict[str, Any]]:
    if dry_run:
        return True, [], ["dry_run=true，跳过真实执行前文件/服务存在性检查。"], {}

    checks: dict[str, Any] = {}
    errors: list[str] = []
    if action == "create_directory":
        path_text = str(params.get("path") or "")
        path = Path(path_text).expanduser()
        checks["path_exists_before"] = path.exists()
        checks["path_is_existing_file"] = path.exists() and not path.is_dir()
        if path.exists() and not path.is_dir():
            errors.append(f"path_exists_as_file: {path_text}")
        return not errors, errors, [], checks
    if action == "create_file":
        path_text = str(params.get("path") or "")
        path = Path(path_text).expanduser()
        parent = path.parent
        overwrite_if_exists = bool(params.get("overwrite_if_exists"))
        create_parents = bool(params.get("create_parents"))
        checks["path_exists_before"] = path.exists()
        checks["path_is_directory"] = path.exists() and path.is_dir()
        checks["parent_exists"] = parent.exists()
        checks["parent_is_directory"] = parent.is_dir() if parent.exists() else False
        if path.exists() and path.is_dir():
            errors.append(f"path_exists_as_directory: {path_text}")
        elif path.exists() and not overwrite_if_exists:
            errors.append(f"path_already_exists_requires_overwrite_flag: {path_text}")
        if not parent.exists() and not create_parents:
            errors.append(f"parent_missing_requires_create_parents: {parent}")
        if parent.exists() and not parent.is_dir():
            errors.append(f"parent_is_not_directory: {parent}")
        return not errors, errors, [], checks
    if action in {"modify_file", "delete_file", "purge_quarantine_entry"}:
        path_text = str(params.get("path") or "")
        path = Path(path_text).expanduser()
        checks["path_exists"] = path.exists()
        if not path.exists():
            errors.append(f"path_not_found: {path_text}")
        if action == "modify_file":
            checks["path_is_file"] = path.is_file()
            if path.exists() and not path.is_file():
                errors.append(f"path_is_not_regular_file: {path_text}")
        if action == "purge_quarantine_entry":
            quarantine_root = _quarantine_root(_normalize_platform(str(params.get("platform_hint") or "auto")))
            checks["path_under_quarantine_root"] = _is_within_root(path, quarantine_root) if path.exists() else False
            if path.exists() and not _is_within_root(path, quarantine_root):
                errors.append(f"path_not_in_quarantine_root: {path_text}")
            checks["path_is_directory"] = path.is_dir() if path.exists() else False
            if path.exists() and path.is_dir() and not bool(params.get("recursive")):
                errors.append(f"directory_requires_recursive_flag: {path_text}")
        if operation == "log_cleanup" and path.exists() and path.is_dir():
            errors.append(f"log_cleanup_requires_file_path: {path_text}")
        if operation == "purge_quarantine_entry" and path.exists() and path.resolve() == _quarantine_root(_normalize_platform(str(params.get("platform_hint") or "auto"))):
            errors.append("quarantine_root_self_purge_denied")
    return not errors, errors, [], checks


def _agent_preflight_params(action: str, params: dict[str, Any]) -> dict[str, Any]:
    allowed_keys = AGENT_REQUEST_PARAM_KEYS.get(action, frozenset())
    summary_params: dict[str, Any] = {
        key: value
        for key, value in params.items()
        if str(key) in allowed_keys
    }
    for key, value in params.items():
        if str(key) in REMOTE_REFERENCE_PARAM_KEYS:
            summary_params[key] = value
    for key, value in params.items():
        if key in summary_params:
            continue
        if _contains_denied_agent_request_key({key: value}):
            summary_params[key] = value
    return summary_params


def _contains_denied_agent_request_key(value: Any, *, depth: int = 0) -> bool:
    if depth > 4:
        return False
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).strip().lower() in DENIED_AGENT_REQUEST_KEYS:
                return True
            if _contains_denied_agent_request_key(child, depth=depth + 1):
                return True
    if isinstance(value, list):
        return any(_contains_denied_agent_request_key(item, depth=depth + 1) for item in value)
    return False


def _path_scope_errors(path: str, platform_name: str, *, allow_protected_non_recursive: bool = False) -> list[str]:
    errors: list[str] = []
    if not path:
        return ["path_required"]
    if "\x00" in path or "*" in path or "?" in path:
        errors.append("path_must_be_explicit_no_wildcards")
    if _is_root_path(path, platform_name):
        errors.append(f"root_path_denied: {path}")
    if _is_protected_path(path, platform_name) and not allow_protected_non_recursive:
        errors.append(f"protected_path_denied: {path}")
    return errors


def _is_root_path(path: str, platform_name: str) -> bool:
    text = path.strip().strip("'\"")
    if platform_name == "windows":
        return bool(WINDOWS_DRIVE_RE.fullmatch(text))
    return text in {"/", "~"}


def _is_protected_path(path: str, platform_name: str) -> bool:
    text = path.strip().strip("'\"")
    if platform_name == "windows":
        lowered = text.replace("/", "\\").lower()
        return bool(WINDOWS_DRIVE_RE.fullmatch(lowered)) or any(
            lowered == prefix or lowered.startswith(prefix + "\\")
            for prefix in PROTECTED_WINDOWS_PREFIXES
        )

    if not text.startswith("/"):
        return False
    normalized = "/" + text.strip().replace("\\", "/").strip("/")
    return any(normalized == prefix or normalized.startswith(prefix + "/") for prefix in PROTECTED_POSIX_PATHS)


def _recommended_identity(template: ExecutionActionTemplate, platform_name: str) -> str:
    if platform_name == "windows":
        return template.recommended_windows_identity
    return template.recommended_linux_account


def _normalize_platform(platform_hint: str = "auto") -> str:
    hint = (platform_hint or "auto").strip().lower()
    if hint in {"windows", "linux"}:
        return hint
    detected = current_platform()
    if detected.startswith("win"):
        return "windows"
    if detected == "linux":
        return "linux"
    return detected


def _env_flag(name: str) -> bool:
    value = get_prefixed_env(name, "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _trusted_identities_from_env() -> set[str]:
    value = get_prefixed_env("TMP_MCP_TRUSTED_EXECUTION_IDENTITIES", "")
    return {item.strip().lower() for item in value.split(",") if item.strip()}


def _safe_current_user() -> str:
    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001 - 身份仅用于审计提示，不影响异常安全。
        return "unknown"


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
