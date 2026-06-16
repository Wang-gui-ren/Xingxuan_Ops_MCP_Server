from __future__ import annotations

import os
import getpass
import re
import shutil
import subprocess
import tarfile
import time
import zipfile
import hashlib
from pathlib import Path
from typing import Any

import psutil

from mcp_ops_server.branding import DEFAULT_LINUX_MANAGED_ROOT, DEFAULT_WINDOWS_MANAGED_ROOT, get_prefixed_env
from mcp_ops_server.execution.action_templates import build_least_privilege_context, get_action_template
from mcp_ops_server.execution.agents import (
    ExecutionAgentRequest,
    LinuxSSHReferenceExecutionAgentAdapter,
    RemoteReferenceExecutionAgentAdapter,
    WindowsWinRMReferenceExecutionAgentAdapter,
    get_execution_agent_profile,
)
from mcp_ops_server.models import ToolEnvelope
from mcp_ops_server.utils.platform import current_platform


SERVICE_NAME_RE = re.compile(r"^[A-Za-z0-9_.@:-]{1,128}$")
PACKAGE_NAME_RE = re.compile(r"^[A-Za-z0-9_.+:-]{1,160}$")
WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]*$")

PROTECTED_POSIX_PATHS = {
    Path("/"),
    Path("/bin"),
    Path("/boot"),
    Path("/dev"),
    Path("/etc"),
    Path("/lib"),
    Path("/lib64"),
    Path("/proc"),
    Path("/root"),
    Path("/sbin"),
    Path("/sys"),
    Path("/usr"),
    Path("/var/lib"),
}

PROTECTED_WINDOWS_PREFIXES = (
    "c:\\windows",
    "c:\\program files",
    "c:\\program files (x86)",
    "c:\\programdata\\microsoft",
)

PACKAGE_MANAGERS = ("dnf", "yum", "apt-get", "zypper")

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


def _now_suffix() -> str:
    return time.strftime("%Y%m%d%H%M%S")


def _normalize_platform(platform_hint: str = "auto") -> str:
    hint = (platform_hint or "auto").lower()
    if hint in {"windows", "linux"}:
        return hint
    detected = current_platform()
    if detected.startswith("win"):
        return "windows"
    if detected == "linux":
        return "linux"
    return detected


def _completed_process_to_data(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    return {
        "exit_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def _run_command(args: list[str], timeout_seconds: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        capture_output=True,
        check=False,
        text=True,
        timeout=timeout_seconds,
    )


def _is_remote_target(target: str) -> bool:
    return target not in {"", "local", "localhost", "127.0.0.1", "::1"}


def _remote_transport(platform_name: str) -> str:
    return "winrm" if platform_name == "windows" else "ssh"


def _remote_profile_id(platform_name: str) -> str:
    return "windows-jea-endpoint-v1" if platform_name == "windows" else "linux-kylin-ops-agent-v1"


def _safe_path(path: str) -> Path:
    if not path or any(token in path for token in ("\x00", "*", "?")):
        raise ValueError("Path must be explicit and must not contain wildcards.")
    return Path(path).expanduser().resolve()


def _is_protected_path(path: Path, platform_name: str) -> bool:
    if platform_name == "windows":
        text = str(path).lower()
        return WINDOWS_DRIVE_RE.match(text) is not None or any(
            text == prefix or text.startswith(prefix + "\\")
            for prefix in PROTECTED_WINDOWS_PREFIXES
        )

    try:
        return path in PROTECTED_POSIX_PATHS or any(
            path.is_relative_to(protected)
            for protected in PROTECTED_POSIX_PATHS
            if str(protected) not in {"/var/lib"}
        )
    except AttributeError:
        path_text = str(path)
        return any(path_text == str(protected) or path_text.startswith(str(protected) + os.sep) for protected in PROTECTED_POSIX_PATHS)


def _copy_backup(path: Path) -> Path:
    backup = path.with_name(f"{path.name}.bak.{_now_suffix()}")
    if path.is_dir():
        shutil.copytree(path, backup)
    else:
        shutil.copy2(path, backup)
    return backup


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _managed_tmp_mcp_root(platform_name: str) -> Path:
    configured = get_prefixed_env("TMP_MCP_MANAGED_ROOT")
    if configured:
        return Path(configured)
    return DEFAULT_WINDOWS_MANAGED_ROOT if platform_name == "windows" else DEFAULT_LINUX_MANAGED_ROOT


def _quarantine_root(platform_name: str) -> Path:
    return (_managed_tmp_mcp_root(platform_name) / "quarantine").resolve()


def _is_under_root(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _post_checks(ok: bool, checks: list[dict[str, Any]], summary: str) -> dict[str, Any]:
    return {
        "ok": ok,
        "summary": summary,
        "checks": checks,
    }


def _check(name: str, ok: bool, summary: str, **details: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"name": name, "ok": ok, "summary": summary}
    payload.update({key: value for key, value in details.items() if value is not None})
    return payload


def _command_post_checks(name: str, result: subprocess.CompletedProcess[str], success_summary: str, failure_summary: str) -> dict[str, Any]:
    ok = result.returncode == 0
    return _post_checks(
        ok=ok,
        summary=success_summary if ok else failure_summary,
        checks=[
            _check(
                name=name,
                ok=ok,
                summary=f"command exit_code={result.returncode}",
                exit_code=result.returncode,
            ),
        ],
    )


def _common_request_data(
    action: str,
    target: str,
    platform_name: str,
    dry_run: bool,
    reason: str | None,
    approval_id: str | None,
    plan: dict[str, Any],
) -> dict[str, Any]:
    return {
        "action": action,
        "target": target,
        "platform": platform_name,
        "dry_run": dry_run,
        "reason": reason,
        "approval_id": approval_id,
        "plan": plan,
        "least_privilege": build_least_privilege_context(action, platform_name, target, plan),
        "status": "planned" if dry_run else "executed",
    }


def _remote_reference_data(
    target: str,
    platform_name: str,
    action: str,
    plan: dict[str, Any],
    *,
    approval_id: str | None = None,
    scope_hash: str | None = None,
    trace_id: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    template = get_action_template(action)
    profile = get_execution_agent_profile(_remote_profile_id(platform_name))
    request = ExecutionAgentRequest(
        template_id=template.template_id if template else "",
        action=action,
        platform=platform_name,
        target=target,
        params=plan,
        profile_id=profile.profile_id if profile else None,
        approval_id=approval_id,
        scope_hash=scope_hash,
        trace_id=trace_id,
        session_id=session_id,
    )
    adapter: RemoteReferenceExecutionAgentAdapter
    if platform_name == "windows":
        adapter = WindowsWinRMReferenceExecutionAgentAdapter(profile)
    else:
        adapter = LinuxSSHReferenceExecutionAgentAdapter(profile)
    return adapter.build_reference_bundle(
        request,
        runtime_identity=getpass.getuser() if hasattr(getpass, "getuser") else "unknown",
        trusted_identities=set(),
    )


def _remote_reference_envelope(
    *,
    action: str,
    target: str,
    platform_name: str,
    dry_run: bool,
    reason: str | None,
    approval_id: str | None,
    scope_hash: str | None = None,
    trace_id: str | None = None,
    session_id: str | None = None,
    plan: dict[str, Any],
    summary: str,
    next_actions: list[str] | None = None,
) -> ToolEnvelope:
    data = _common_request_data(action, target, platform_name, dry_run, reason, approval_id, plan)
    data["remote_execution"] = _remote_reference_data(
        target,
        platform_name,
        action,
        plan,
        approval_id=approval_id,
        scope_hash=scope_hash,
        trace_id=trace_id,
        session_id=session_id,
    )
    return ToolEnvelope(
        ok=True,
        risk_level="high",
        summary=summary,
        data=data,
        next_actions=(next_actions or [])
        + [
            "当前只生成远程 reference-only 计划，不会执行真实远程写操作。",
            "保持 dry_run=true 以绑定审批范围、trace 和审计证据。",
        ],
    )


def _normalize_network_action(action: str) -> str:
    normalized = (action or "").strip().lower().replace("-", "_").replace(" ", "_")
    return NETWORK_ACTION_ALIASES.get(normalized, normalized)


def _build_modify_file_post_checks(
    *,
    file_path: Path,
    operation: str,
    content: str,
    backup_path: Path | None,
    pre_hash: str,
    post_hash: str,
) -> dict[str, Any]:
    current_text = file_path.read_text(encoding="utf-8")
    content_applied = content in current_text
    checks = [
        _check("file_exists_after_write", file_path.exists(), "target file exists after write", path=str(file_path)),
        _check("file_is_regular_after_write", file_path.is_file(), "target is still a regular file", path=str(file_path)),
        _check("file_hash_changed", pre_hash != post_hash, "file hash changed after fixed-template write", pre_hash=pre_hash, post_hash=post_hash),
        _check("operation_content_visible", content_applied, "requested content is visible after write", operation=operation),
    ]
    if backup_path is not None:
        checks.append(
            _check("backup_created", backup_path.exists(), "backup file exists for rollback", backup_path=str(backup_path))
        )
    ok = all(item["ok"] for item in checks)
    return _post_checks(
        ok=ok,
        summary="File modification post-checks completed." if ok else "File modification post-checks need review.",
        checks=checks,
    )


def _build_file_cleanup_post_checks(*, path: Path, mode: str, result_path: Path | None) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    if mode == "truncate":
        checks.extend(
            [
                _check("source_exists_after_truncate", path.exists(), "source file still exists after truncate", path=str(path)),
                _check(
                    "source_size_zero",
                    path.exists() and path.stat().st_size == 0,
                    "source file size is zero after truncate",
                    path=str(path),
                ),
            ]
        )
    elif mode == "delete":
        checks.append(_check("source_absent_after_delete", not path.exists(), "source path is absent after delete", path=str(path)))
    elif mode == "quarantine":
        checks.extend(
            [
                _check("source_absent_after_quarantine", not path.exists(), "source path moved to quarantine", path=str(path)),
                _check("result_path_exists", bool(result_path and result_path.exists()), "quarantine result path exists", result_path=str(result_path) if result_path else None),
            ]
        )
    elif mode == "archive":
        checks.extend(
            [
                _check("source_retained_after_archive", path.exists(), "archive mode keeps the source path", path=str(path)),
                _check("archive_path_exists", bool(result_path and result_path.exists()), "archive file exists", result_path=str(result_path) if result_path else None),
            ]
        )
    else:
        checks.append(_check("cleanup_mode_supported", False, "cleanup mode has no post-check template", mode=mode))

    ok = all(item["ok"] for item in checks)
    return _post_checks(
        ok=ok,
        summary="File cleanup post-checks completed." if ok else "File cleanup post-checks need review.",
        checks=checks,
    )


def _build_create_directory_post_checks(*, directory_path: Path, existed_before: bool) -> dict[str, Any]:
    exists_after = directory_path.exists()
    is_dir_after = directory_path.is_dir() if exists_after else False
    checks = [
        _check("directory_exists_after_create", exists_after, "target directory exists after create", path=str(directory_path)),
        _check("directory_is_directory", is_dir_after, "target path is a directory after create", path=str(directory_path)),
        _check("directory_was_new", not existed_before, "target directory did not exist before create", path=str(directory_path)),
    ]
    ok = all(item["ok"] for item in checks)
    return _post_checks(
        ok=ok,
        summary="Directory creation post-checks completed." if ok else "Directory creation post-checks need review.",
        checks=checks,
    )


def _build_create_file_post_checks(
    *,
    file_path: Path,
    content: str,
    existed_before: bool,
    backup_path: Path | None,
    pre_hash: str | None,
    post_hash: str,
) -> dict[str, Any]:
    current_text = file_path.read_text(encoding="utf-8")
    content_applied = current_text == content
    checks = [
        _check("file_exists_after_create", file_path.exists(), "target file exists after create", path=str(file_path)),
        _check("file_is_regular_after_create", file_path.is_file(), "target is a regular file after create", path=str(file_path)),
        _check("file_content_matches_requested", content_applied, "created file content matches requested content", path=str(file_path)),
    ]
    if existed_before:
        checks.append(
            _check(
                "file_hash_changed",
                pre_hash is not None and pre_hash != post_hash,
                "existing file hash changed after overwrite",
                pre_hash=pre_hash,
                post_hash=post_hash,
            )
        )
    else:
        checks.append(
            _check(
                "file_was_new",
                pre_hash is None,
                "file did not exist before create",
                path=str(file_path),
            )
        )
    if backup_path is not None:
        checks.append(
            _check("backup_created", backup_path.exists(), "backup file exists for rollback", backup_path=str(backup_path))
        )
    ok = all(item["ok"] for item in checks)
    return _post_checks(
        ok=ok,
        summary="File creation post-checks completed." if ok else "File creation post-checks need review.",
        checks=checks,
    )


def _build_purge_quarantine_post_checks(*, path: Path) -> dict[str, Any]:
    checks = [
        _check("quarantine_entry_absent_after_purge", not path.exists(), "quarantine entry is absent after purge", path=str(path)),
    ]
    ok = all(item["ok"] for item in checks)
    return _post_checks(
        ok=ok,
        summary="Quarantine purge post-checks completed." if ok else "Quarantine purge post-checks need review.",
        checks=checks,
    )


def _build_stop_process_post_checks(*, pid: int, stopped: bool) -> dict[str, Any]:
    pid_absent = not psutil.pid_exists(pid)
    checks = [
        _check("process_stop_reported", stopped, "process wait completed after signal", pid=pid),
        _check("pid_absent_after_signal", pid_absent, "PID is absent after stop attempt", pid=pid),
    ]
    ok = all(item["ok"] for item in checks)
    return _post_checks(
        ok=ok,
        summary="Process stop post-checks completed." if ok else "Process stop post-checks need review.",
        checks=checks,
    )


def _build_permission_post_checks(*, file_path: Path, mode: str | None, ok: bool) -> dict[str, Any]:
    checks = [
        _check("permission_command_completed", ok, "permission command returned success", path=str(file_path)),
        _check("path_exists_after_permission_change", file_path.exists(), "target path still exists", path=str(file_path)),
    ]
    if mode and os.name != "nt" and file_path.exists():
        current_mode = oct(file_path.stat().st_mode & 0o777)
        expected_mode = oct(int(mode, 8))
        checks.append(
            _check(
                "posix_mode_matches",
                current_mode == expected_mode,
                "POSIX mode matches requested value",
                expected_mode=expected_mode,
                current_mode=current_mode,
            )
        )
    checks_ok = all(item["ok"] for item in checks)
    return _post_checks(
        ok=checks_ok,
        summary="Permission post-checks completed." if checks_ok else "Permission post-checks need review.",
        checks=checks,
    )


def _rollback_hint(action: str, context: dict[str, Any]) -> list[str]:
    if action == "create_directory":
        path = context.get("path")
        return [
            f"Remove the newly created empty directory at {path} after approval if rollback is needed.",
            "If files were added later, review contents manually before removal.",
        ]
    if action == "create_file":
        path = context.get("path")
        backup_path = context.get("backup_path")
        if backup_path:
            return [
                f"Restore the backup file from {backup_path} if the overwrite must be rolled back.",
                f"If rollback is still required after verification, remove or replace {path} only through a new approved plan.",
            ]
        return [
            f"Remove the newly created file at {path} after approval if rollback is needed.",
            "If downstream systems already consumed the file, review those side effects before cleanup.",
        ]
    if action == "modify_file":
        backup_path = context.get("backup_path")
        if backup_path:
            return [
                f"Restore the backup file from {backup_path} if verification fails.",
                "Run request_modify_file with dry_run=true before applying any corrective edit.",
            ]
        return ["No backup file was created; use audit hashes and manual review before rollback."]
    if action == "delete_file":
        mode = context.get("mode")
        result_path = context.get("result_path")
        if mode == "quarantine" and result_path:
            return [f"Move the quarantined file back from {result_path} after approval if rollback is needed."]
        if mode == "archive" and result_path:
            return [f"Restore from archive {result_path} after approval if rollback is needed."]
        if mode == "truncate":
            return ["Truncate is not fully reversible; restore from external backup if content is needed."]
        return ["Permanent delete is not reversible through this MCP template."]
    if action == "purge_quarantine_entry":
        return [
            "Quarantine purge is not reversible through this MCP template.",
            "Restore only from an external backup or a separately retained archive if recovery is required.",
        ]
    if action == "restart_service":
        service = context.get("service")
        return [
            f"Check service status for {service} and recent logs before declaring success.",
            "If restart caused impact, run diagnostics and prepare an approved service rollback plan.",
        ]
    if action == "stop_process":
        return ["Process stop is not directly reversible; restart the owning service only after a new approved plan."]
    if action == "change_permissions":
        return ["Restore the previously recorded owner/mode or ACL through a new request_change_permissions dry-run plan."]
    if action == "manage_package":
        package = context.get("package")
        requested_action = context.get("action")
        if requested_action == "install":
            return [f"Rollback usually means removing package {package} through a new approved package plan."]
        if requested_action == "remove":
            return [f"Rollback usually means reinstalling package {package} from a trusted repository."]
        return [f"Rollback package {package} by reinstalling the previously recorded version if available."]
    if action == "network_policy_change":
        requested_action = context.get("action")
        opposite = "deny_port" if requested_action == "allow_port" else "allow_port"
        return [
            f"Rollback by creating a new approved network policy plan with action={opposite}.",
            "Verify the effective firewall rule after rollback.",
        ]
    return ["Review the fixed template audit record before preparing a rollback plan."]


class ExecutionProxy:
    """Fixed-template execution helpers for local Windows and Linux hosts.

    These methods intentionally do not expose arbitrary shell execution. Remote
    execution, audit logging, and approval persistence are left for later layers.
    """

    def _reject_remote(self, target: str) -> ToolEnvelope | None:
        if _is_remote_target(target):
            return ToolEnvelope(
                ok=False,
                risk_level="high",
                summary="Remote execution is not implemented yet.",
                data={"target": target, "status": "remote_execution_not_supported"},
                next_actions=[
                    "Use target='local' for the current implementation.",
                    "Add SSH/WinRM execution adapters before enabling remote operations.",
                ],
            )
        return None

    def request_modify_file(
        self,
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
    ) -> ToolEnvelope:
        platform_name = _normalize_platform(platform_hint)
        if _is_remote_target(target):
            plan = {
                "path": str(path),
                "operation": operation,
                "backup": backup,
                "content_preview": content[:120],
                "match": match,
                "remote_username": remote_username,
                "remote_port": remote_port,
                "remote_auth_ref": remote_auth_ref,
                "remote_endpoint": remote_endpoint,
            }
            if dry_run:
                return _remote_reference_envelope(
                    action="modify_file",
                    target=target,
                    platform_name=platform_name,
                    dry_run=dry_run,
                    reason=reason,
                    approval_id=approval_id,
                    plan=plan,
                    summary="Generated remote file modification reference plan; no remote changes were made.",
                )
            return self._reject_remote(target)
        try:
            file_path = _safe_path(path)
            if _is_protected_path(file_path, platform_name):
                return ToolEnvelope(
                    ok=False,
                    risk_level="critical",
                    summary="Refused to modify a protected system path.",
                    data={"path": str(file_path), "status": "refused_protected_path"},
                )
            if operation not in {"replace_text", "append_line", "set_key_value", "comment_line", "overwrite"}:
                raise ValueError("Unsupported file modification operation.")
            if not file_path.exists() or not file_path.is_file():
                raise ValueError("Target path must be an existing file.")
            if operation in {"replace_text", "set_key_value", "comment_line"} and not match:
                raise ValueError("The selected operation requires a match value.")

            plan = {
                "path": str(file_path),
                "operation": operation,
                "backup": backup,
                "content_preview": content[:120],
                "match": match,
            }
            data = _common_request_data("modify_file", target, platform_name, dry_run, reason, approval_id, plan)
            if dry_run:
                return ToolEnvelope(
                    risk_level="high",
                    summary="Generated file modification plan; no changes were made.",
                    data=data,
                    next_actions=["Call again with dry_run=false only after manual confirmation."],
                )

            pre_hash = _sha256_file(file_path)
            original_text = file_path.read_text(encoding="utf-8")
            new_text = self._apply_text_operation(original_text, operation, content, match)
            backup_path = _copy_backup(file_path) if backup else None
            file_path.write_text(new_text, encoding="utf-8")
            post_hash = _sha256_file(file_path)
            data["backup_path"] = str(backup_path) if backup_path else None
            data["pre_hash"] = pre_hash
            data["post_hash"] = post_hash
            data["post_checks"] = _build_modify_file_post_checks(
                file_path=file_path,
                operation=operation,
                content=content,
                backup_path=backup_path,
                pre_hash=pre_hash,
                post_hash=post_hash,
            )
            data["rollback_hint"] = _rollback_hint("modify_file", {"backup_path": data["backup_path"]})
            return ToolEnvelope(
                risk_level="high",
                summary="File modification completed with a fixed template.",
                data=data,
            )
        except Exception as exc:
            return ToolEnvelope(
                ok=False,
                risk_level="high",
                summary="Failed to modify file.",
                data={"path": path, "operation": operation, "error": str(exc)},
            )

    def request_create_directory(
        self,
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
    ) -> ToolEnvelope:
        platform_name = _normalize_platform(platform_hint)
        if _is_remote_target(target):
            plan = {
                "path": str(path),
                "create_parents": create_parents,
                "exists_before": None,
                "remote_username": remote_username,
                "remote_port": remote_port,
                "remote_auth_ref": remote_auth_ref,
                "remote_endpoint": remote_endpoint,
            }
            if dry_run:
                return _remote_reference_envelope(
                    action="create_directory",
                    target=target,
                    platform_name=platform_name,
                    dry_run=dry_run,
                    reason=reason,
                    approval_id=approval_id,
                    plan=plan,
                    summary="Generated remote directory creation reference plan; no remote changes were made.",
                )
            return self._reject_remote(target)
        try:
            dir_path = _safe_path(path)
            if _is_protected_path(dir_path, platform_name):
                return ToolEnvelope(
                    ok=False,
                    risk_level="critical",
                    summary="Refused to create a directory under a protected system path.",
                    data={"path": str(dir_path), "status": "refused_protected_path"},
                )
            if dir_path.exists() and not dir_path.is_dir():
                raise ValueError("Target path already exists and is not a directory.")

            plan = {
                "path": str(dir_path),
                "create_parents": create_parents,
                "exists_before": dir_path.exists(),
            }
            data = _common_request_data("create_directory", target, platform_name, dry_run, reason, approval_id, plan)
            if dry_run:
                return ToolEnvelope(
                    risk_level="high",
                    summary="Generated directory creation plan; no directories were created.",
                    data=data,
                    next_actions=["Review the target path and parent directory scope before real execution."],
                )

            existed_before = dir_path.exists()
            if existed_before:
                raise ValueError("Target directory already exists.")
            dir_path.mkdir(parents=create_parents, exist_ok=False)
            data["directory_created"] = True
            data["target_exists"] = dir_path.exists()
            data["post_checks"] = _build_create_directory_post_checks(
                directory_path=dir_path,
                existed_before=existed_before,
            )
            data["rollback_hint"] = _rollback_hint("create_directory", {"path": str(dir_path)})
            return ToolEnvelope(
                risk_level="high",
                summary="Directory creation completed with a fixed template.",
                data=data,
            )
        except Exception as exc:
            return ToolEnvelope(
                ok=False,
                risk_level="high",
                summary="Failed to create directory.",
                data={"path": path, "create_parents": create_parents, "error": str(exc)},
            )

    def request_create_file(
        self,
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
    ) -> ToolEnvelope:
        platform_name = _normalize_platform(platform_hint)
        if _is_remote_target(target):
            plan = {
                "path": str(path),
                "content_preview": content[:120],
                "overwrite_if_exists": overwrite_if_exists,
                "create_parents": create_parents,
                "remote_username": remote_username,
                "remote_port": remote_port,
                "remote_auth_ref": remote_auth_ref,
                "remote_endpoint": remote_endpoint,
            }
            if dry_run:
                return _remote_reference_envelope(
                    action="create_file",
                    target=target,
                    platform_name=platform_name,
                    dry_run=dry_run,
                    reason=reason,
                    approval_id=approval_id,
                    plan=plan,
                    summary="Generated remote file creation reference plan; no files were created.",
                )
            return self._reject_remote(target)
        try:
            file_path = _safe_path(path)
            if _is_protected_path(file_path, platform_name):
                return ToolEnvelope(
                    ok=False,
                    risk_level="critical",
                    summary="Refused to create a file under a protected system path.",
                    data={"path": str(file_path), "status": "refused_protected_path"},
                )

            parent_dir = file_path.parent
            exists_before = file_path.exists()
            if exists_before and file_path.is_dir():
                raise ValueError("Target path already exists and is a directory.")
            if exists_before and not overwrite_if_exists:
                raise ValueError("Target file already exists; set overwrite_if_exists=true to overwrite it.")
            if not parent_dir.exists() and not create_parents:
                raise ValueError("Parent directory does not exist; set create_parents=true to create it.")
            if parent_dir.exists() and not parent_dir.is_dir():
                raise ValueError("Parent path exists and is not a directory.")

            plan = {
                "path": str(file_path),
                "content_preview": content[:120],
                "overwrite_if_exists": overwrite_if_exists,
                "create_parents": create_parents,
                "exists_before": exists_before,
            }
            data = _common_request_data("create_file", target, platform_name, dry_run, reason, approval_id, plan)
            if dry_run:
                return ToolEnvelope(
                    risk_level="high",
                    summary="Generated file creation plan; no files were created.",
                    data=data,
                    next_actions=["Review the target path, parent directory, and initial content before real execution."],
                )

            if not parent_dir.exists():
                parent_dir.mkdir(parents=create_parents, exist_ok=False)

            pre_hash: str | None = _sha256_file(file_path) if exists_before and file_path.is_file() else None
            backup_path = _copy_backup(file_path) if exists_before and overwrite_if_exists else None
            file_path.write_text(content, encoding="utf-8")
            post_hash = _sha256_file(file_path)
            data["created_file"] = True
            data["target_exists"] = file_path.exists()
            data["backup_path"] = str(backup_path) if backup_path else None
            data["pre_hash"] = pre_hash
            data["post_hash"] = post_hash
            data["post_checks"] = _build_create_file_post_checks(
                file_path=file_path,
                content=content,
                existed_before=exists_before,
                backup_path=backup_path,
                pre_hash=pre_hash,
                post_hash=post_hash,
            )
            data["rollback_hint"] = _rollback_hint(
                "create_file",
                {"path": str(file_path), "backup_path": data["backup_path"]},
            )
            return ToolEnvelope(
                risk_level="high",
                summary="File creation completed with a fixed template.",
                data=data,
            )
        except Exception as exc:
            return ToolEnvelope(
                ok=False,
                risk_level="high",
                summary="Failed to create file.",
                data={
                    "path": path,
                    "overwrite_if_exists": overwrite_if_exists,
                    "create_parents": create_parents,
                    "error": str(exc),
                },
            )

    def _apply_text_operation(self, text: str, operation: str, content: str, match: str | None) -> str:
        if operation == "append_line":
            suffix = "" if text.endswith("\n") else "\n"
            return f"{text}{suffix}{content}\n"
        if operation == "overwrite":
            return content
        if operation == "replace_text":
            if match not in text:
                raise ValueError("Match text was not found.")
            return text.replace(match or "", content, 1)
        if operation == "set_key_value":
            lines = text.splitlines()
            changed = False
            for idx, line in enumerate(lines):
                if line.strip().startswith(match or ""):
                    lines[idx] = content
                    changed = True
                    break
            if not changed:
                raise ValueError("Configuration key was not found.")
            return "\n".join(lines) + ("\n" if text.endswith("\n") else "")
        if operation == "comment_line":
            lines = text.splitlines()
            changed = False
            for idx, line in enumerate(lines):
                if match and match in line and not line.lstrip().startswith("#"):
                    lines[idx] = f"# {line}"
                    changed = True
                    break
            if not changed:
                raise ValueError("Matching uncommented line was not found.")
            return "\n".join(lines) + ("\n" if text.endswith("\n") else "")
        raise ValueError("Unsupported file modification operation.")

    def request_delete_file(
        self,
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
    ) -> ToolEnvelope:
        platform_name = _normalize_platform(platform_hint)
        if _is_remote_target(target):
            plan = {
                "path": str(path),
                "mode": mode,
                "recursive": recursive,
                "is_dir": None,
                "remote_username": remote_username,
                "remote_port": remote_port,
                "remote_auth_ref": remote_auth_ref,
                "remote_endpoint": remote_endpoint,
            }
            if dry_run:
                return _remote_reference_envelope(
                    action="delete_file",
                    target=target,
                    platform_name=platform_name,
                    dry_run=dry_run,
                    reason=reason,
                    approval_id=approval_id,
                    plan=plan,
                    summary="Generated remote file cleanup reference plan; no remote changes were made.",
                )
            return self._reject_remote(target)
        try:
            file_path = _safe_path(path)
            if mode not in {"quarantine", "archive", "truncate", "delete"}:
                raise ValueError("Unsupported delete mode.")
            if _is_protected_path(file_path, platform_name):
                return ToolEnvelope(
                    ok=False,
                    risk_level="critical",
                    summary="Refused to delete or alter a protected system path.",
                    data={"path": str(file_path), "status": "refused_protected_path"},
                )
            if not file_path.exists():
                raise ValueError("Target path does not exist.")
            if file_path.is_dir() and not recursive:
                raise ValueError("Directory operations require recursive=true.")
            if mode == "truncate" and not file_path.is_file():
                raise ValueError("Truncate mode only supports files.")

            plan = {
                "path": str(file_path),
                "mode": mode,
                "recursive": recursive,
                "is_dir": file_path.is_dir(),
            }
            data = _common_request_data("delete_file", target, platform_name, dry_run, reason, approval_id, plan)
            if dry_run:
                return ToolEnvelope(
                    risk_level="high",
                    summary="Generated file cleanup plan; no changes were made.",
                    data=data,
                    next_actions=["Use quarantine or archive mode before considering permanent delete."],
                )

            result_path = self._execute_file_cleanup(file_path, mode, platform_name, recursive)
            data["result_path"] = str(result_path) if result_path else None
            data["post_checks"] = _build_file_cleanup_post_checks(
                path=file_path,
                mode=mode,
                result_path=result_path,
            )
            data["rollback_hint"] = _rollback_hint("delete_file", {"mode": mode, "result_path": data["result_path"]})
            return ToolEnvelope(
                risk_level="high",
                summary="File cleanup action completed with a fixed template.",
                data=data,
            )
        except Exception as exc:
            return ToolEnvelope(
                ok=False,
                risk_level="high",
                summary="Failed to process file cleanup request.",
                data={"path": path, "mode": mode, "error": str(exc)},
            )

    def request_purge_quarantine_entry(
        self,
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
    ) -> ToolEnvelope:
        platform_name = _normalize_platform(platform_hint)
        if _is_remote_target(target):
            plan = {
                "path": str(path),
                "recursive": recursive,
                "remote_username": remote_username,
                "remote_port": remote_port,
                "remote_auth_ref": remote_auth_ref,
                "remote_endpoint": remote_endpoint,
            }
            if dry_run:
                return _remote_reference_envelope(
                    action="purge_quarantine_entry",
                    target=target,
                    platform_name=platform_name,
                    dry_run=dry_run,
                    reason=reason,
                    approval_id=approval_id,
                    plan=plan,
                    summary="Generated quarantine purge reference plan; no files were removed.",
                )
            return self._reject_remote(target)
        try:
            entry_path = _safe_path(path)
            quarantine_root = _quarantine_root(platform_name)
            if not _is_under_root(entry_path, quarantine_root):
                raise ValueError(f"Path must stay within quarantine root: {quarantine_root}")
            if entry_path == quarantine_root:
                raise ValueError("Refusing to purge the quarantine root itself.")
            if not entry_path.exists():
                raise ValueError("Quarantine entry does not exist.")
            if entry_path.is_dir() and not recursive:
                raise ValueError("Directory purge requires recursive=true.")

            plan = {
                "path": str(entry_path),
                "recursive": recursive,
                "quarantine_root": str(quarantine_root),
                "is_dir": entry_path.is_dir(),
            }
            data = _common_request_data("purge_quarantine_entry", target, platform_name, dry_run, reason, approval_id, plan)
            if dry_run:
                return ToolEnvelope(
                    risk_level="high",
                    summary="Generated quarantine purge plan; no files were removed.",
                    data=data,
                    next_actions=["Verify the quarantine entry path before approving irreversible purge."],
                )

            if entry_path.is_dir():
                shutil.rmtree(entry_path)
            else:
                entry_path.unlink()
            data["post_checks"] = _build_purge_quarantine_post_checks(path=entry_path)
            data["rollback_hint"] = _rollback_hint("purge_quarantine_entry", {"path": str(entry_path)})
            return ToolEnvelope(
                risk_level="high",
                summary="Quarantine entry purge completed with a fixed template.",
                data=data,
            )
        except Exception as exc:
            return ToolEnvelope(
                ok=False,
                risk_level="high",
                summary="Failed to purge quarantine entry.",
                data={"path": path, "recursive": recursive, "error": str(exc)},
            )

    def _execute_file_cleanup(self, path: Path, mode: str, platform_name: str, recursive: bool) -> Path | None:
        base_dir = _managed_tmp_mcp_root(platform_name)
        if mode == "truncate":
            path.write_text("", encoding="utf-8")
            return path
        if mode == "quarantine":
            quarantine_dir = base_dir / "quarantine"
            quarantine_dir.mkdir(parents=True, exist_ok=True)
            dest = quarantine_dir / f"{path.name}.{_now_suffix()}"
            shutil.move(str(path), str(dest))
            return dest
        if mode == "archive":
            archive_dir = base_dir / "archive"
            archive_dir.mkdir(parents=True, exist_ok=True)
            if platform_name == "windows":
                dest = archive_dir / f"{path.name}.{_now_suffix()}.zip"
                with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
                    if path.is_dir():
                        for child in path.rglob("*"):
                            zf.write(child, child.relative_to(path.parent))
                    else:
                        zf.write(path, path.name)
            else:
                dest = archive_dir / f"{path.name}.{_now_suffix()}.tar.gz"
                with tarfile.open(dest, "w:gz") as tf:
                    tf.add(path, arcname=path.name)
            return dest
        if mode == "delete":
            if path.is_dir():
                if not recursive:
                    raise ValueError("Directory delete requires recursive=true.")
                shutil.rmtree(path)
            else:
                path.unlink()
            return None
        raise ValueError("Unsupported cleanup mode.")

    def request_restart_service(
        self,
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
    ) -> ToolEnvelope:
        platform_name = _normalize_platform(platform_hint)
        if _is_remote_target(target):
            command = (
                ["powershell", "-NoProfile", "-Command", f"Restart-Service -Name '{service}' -ErrorAction Stop"]
                if platform_name == "windows"
                else ["systemctl", "restart", service]
            )
            plan = {
                "service": service,
                "command_template": command,
                "remote_username": remote_username,
                "remote_port": remote_port,
                "remote_auth_ref": remote_auth_ref,
                "remote_endpoint": remote_endpoint,
            }
            if dry_run:
                return _remote_reference_envelope(
                    action="restart_service",
                    target=target,
                    platform_name=platform_name,
                    dry_run=dry_run,
                    reason=reason,
                    approval_id=approval_id,
                    plan=plan,
                    summary="Generated remote service restart reference plan; no remote changes were made.",
                )
            return self._reject_remote(target)
        if not SERVICE_NAME_RE.match(service):
            return ToolEnvelope(
                ok=False,
                risk_level="high",
                summary="Refused service operation because the service name is invalid.",
                data={"service": service, "status": "invalid_service_name"},
            )

        command = (
            ["powershell", "-NoProfile", "-Command", f"Restart-Service -Name '{service}' -ErrorAction Stop"]
            if platform_name == "windows"
            else ["systemctl", "restart", service]
        )
        plan = {"service": service, "command_template": command}
        data = _common_request_data("restart_service", target, platform_name, dry_run, reason, approval_id, plan)
        if dry_run:
            return ToolEnvelope(
                risk_level="high",
                summary="Generated service restart plan; service was not restarted.",
                data=data,
                next_actions=["Call get_service_status_tool before and after execution."],
            )

        try:
            result = _run_command(command, timeout_seconds=timeout_seconds)
            data["result"] = _completed_process_to_data(result)
            data["post_checks"] = _command_post_checks(
                "service_restart_command",
                result,
                "Service manager accepted the restart command; verify service health next.",
                "Service manager rejected the restart command; no health success is claimed.",
            )
            data["rollback_hint"] = _rollback_hint("restart_service", {"service": service})
            return ToolEnvelope(
                ok=result.returncode == 0,
                risk_level="high",
                summary="Service restart command executed." if result.returncode == 0 else "Service restart command failed.",
                data=data,
            )
        except Exception as exc:
            return ToolEnvelope(
                ok=False,
                risk_level="high",
                summary="Failed to restart service.",
                data={"service": service, "error": str(exc), **data},
            )

    def request_stop_process(
        self,
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
    ) -> ToolEnvelope:
        platform_name = _normalize_platform(platform_hint)
        if _is_remote_target(target):
            plan = {
                "pid": pid,
                "process_name": process_name or "unknown",
                "signal": signal_name,
                "remote_username": remote_username,
                "remote_port": remote_port,
                "remote_auth_ref": remote_auth_ref,
                "remote_endpoint": remote_endpoint,
            }
            if dry_run:
                return _remote_reference_envelope(
                    action="stop_process",
                    target=target,
                    platform_name=platform_name,
                    dry_run=dry_run,
                    reason=reason,
                    approval_id=approval_id,
                    plan=plan,
                    summary="Generated remote process stop reference plan; no remote changes were made.",
                )
            return self._reject_remote(target)
        try:
            if pid <= 1:
                raise ValueError("Refusing to stop PID 0 or PID 1.")
            proc = psutil.Process(pid) if psutil.pid_exists(pid) else None
            if proc is None and not dry_run:
                raise ValueError(f"process PID not found (pid={pid})")
            actual_name = proc.name() if proc else process_name or "unknown"
            if process_name and actual_name.lower() != process_name.lower():
                raise ValueError(f"PID name mismatch: expected {process_name}, got {actual_name}.")
            if signal_name not in {"terminate", "kill"}:
                raise ValueError("signal_name must be terminate or kill.")

            plan = {
                "pid": pid,
                "process_name": actual_name,
                "signal": signal_name,
            }
            data = _common_request_data("stop_process", target, platform_name, dry_run, reason, approval_id, plan)
            if dry_run:
                return ToolEnvelope(
                    risk_level="high",
                    summary="Generated process stop plan; process was not stopped.",
                    data=data,
                )

            if proc is None:
                raise ValueError(f"process PID not found (pid={pid})")
            if signal_name == "terminate":
                proc.terminate()
            else:
                proc.kill()
            try:
                proc.wait(timeout=timeout_seconds)
                stopped = True
            except psutil.TimeoutExpired:
                stopped = False
            data["stopped"] = stopped
            data["post_checks"] = _build_stop_process_post_checks(pid=pid, stopped=stopped)
            data["rollback_hint"] = _rollback_hint("stop_process", {"pid": pid, "process_name": actual_name})
            return ToolEnvelope(
                ok=stopped,
                risk_level="high",
                summary="Process stop signal sent." if stopped else "Process did not stop before timeout.",
                data=data,
            )
        except Exception as exc:
            return ToolEnvelope(
                ok=False,
                risk_level="high",
                summary="Failed to stop process.",
                data={"pid": pid, "process_name": process_name, "error": str(exc)},
            )

    def request_change_permissions(
        self,
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
    ) -> ToolEnvelope:
        platform_name = _normalize_platform(platform_hint)
        if _is_remote_target(target):
            plan = {
                "path": str(path),
                "mode": mode,
                "owner": owner,
                "group": group,
                "recursive": recursive,
                "remote_username": remote_username,
                "remote_port": remote_port,
                "remote_auth_ref": remote_auth_ref,
                "remote_endpoint": remote_endpoint,
            }
            if dry_run:
                return _remote_reference_envelope(
                    action="change_permissions",
                    target=target,
                    platform_name=platform_name,
                    dry_run=dry_run,
                    reason=reason,
                    approval_id=approval_id,
                    plan=plan,
                    summary="Generated remote permission change reference plan; no remote changes were made.",
                )
            return self._reject_remote(target)
        try:
            file_path = _safe_path(path)
            if _is_protected_path(file_path, platform_name) and recursive:
                return ToolEnvelope(
                    ok=False,
                    risk_level="critical",
                    summary="Refused recursive permission changes on a protected path.",
                    data={"path": str(file_path), "status": "refused_protected_path"},
                )
            if not file_path.exists():
                raise ValueError("Target path does not exist.")
            if platform_name == "windows":
                if mode and mode.upper() not in {"R", "RX", "W", "M", "F"}:
                    raise ValueError("Windows ACL mode must be one of R, RX, W, M, or F.")
                if mode and mode.upper() == "F":
                    raise ValueError("Refusing broad Windows FullControl permission.")
            else:
                if mode and not re.fullmatch(r"[0-7]{3,4}", mode):
                    raise ValueError("Linux mode must be an octal string such as 0640.")
                if mode in {"777", "0777", "000", "0000"}:
                    raise ValueError("Refusing unsafe permission mode.")

            plan = {
                "path": str(file_path),
                "mode": mode,
                "owner": owner,
                "group": group,
                "recursive": recursive,
            }
            data = _common_request_data("change_permissions", target, platform_name, dry_run, reason, approval_id, plan)
            if dry_run:
                return ToolEnvelope(
                    risk_level="high",
                    summary="Generated permission change plan; permissions were not changed.",
                    data=data,
                )

            if platform_name == "windows":
                principal = owner or group
                if not principal or not mode:
                    raise ValueError("Windows ACL template requires owner or group plus a permission mode.")
                command = ["icacls", str(file_path), "/grant", f"{principal}:{mode.upper()}"]
                result = _run_command(command, timeout_seconds=timeout_seconds)
                data["acl_result"] = _completed_process_to_data(result)
                data["post_checks"] = _command_post_checks(
                    "windows_acl_command",
                    result,
                    "Windows ACL command completed; verify the effective ACL if needed.",
                    "Windows ACL command failed; effective permissions were not verified.",
                )
                data["rollback_hint"] = _rollback_hint("change_permissions", {"path": str(file_path), "platform": platform_name})
                return ToolEnvelope(
                    ok=result.returncode == 0,
                    risk_level="high",
                    summary="Windows ACL command executed." if result.returncode == 0 else "Windows ACL command failed.",
                    data=data,
                )

            if mode:
                os.chmod(file_path, int(mode, 8))
            if owner or group:
                command = ["chown"]
                if recursive:
                    command.append("-R")
                command.extend([f"{owner or ''}:{group or ''}", str(file_path)])
                result = _run_command(command, timeout_seconds=timeout_seconds)
                data["chown_result"] = _completed_process_to_data(result)
                ok = result.returncode == 0
            else:
                ok = True
            data["post_checks"] = _build_permission_post_checks(file_path=file_path, mode=mode, ok=ok)
            data["rollback_hint"] = _rollback_hint("change_permissions", {"path": str(file_path), "platform": platform_name})
            return ToolEnvelope(
                ok=ok,
                risk_level="high",
                summary="Permission change completed." if ok else "Permission owner/group change failed.",
                data=data,
            )
        except Exception as exc:
            return ToolEnvelope(
                ok=False,
                risk_level="high",
                summary="Failed to change permissions.",
                data={"path": path, "error": str(exc)},
            )

    def request_manage_package(
        self,
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
    ) -> ToolEnvelope:
        platform_name = _normalize_platform(platform_hint)
        if _is_remote_target(target):
            selected_manager = manager if manager != "auto" else ("winget" if platform_name == "windows" else "dnf")
            package_spec = f"{package}={version}" if version and selected_manager in {"apt-get"} else package
            command = self._build_package_command(platform_name, selected_manager, action, package_spec)
            plan = {
                "manager": selected_manager,
                "action": action,
                "package": package,
                "version": version,
                "command_template": command,
                "remote_username": remote_username,
                "remote_port": remote_port,
                "remote_auth_ref": remote_auth_ref,
                "remote_endpoint": remote_endpoint,
            }
            if dry_run:
                return _remote_reference_envelope(
                    action="manage_package",
                    target=target,
                    platform_name=platform_name,
                    dry_run=dry_run,
                    reason=reason,
                    approval_id=approval_id,
                    plan=plan,
                    summary="Generated remote package management reference plan; no remote changes were made.",
                )
            return self._reject_remote(target)
        try:
            if action not in {"install", "upgrade", "remove"}:
                raise ValueError("action must be install, upgrade, or remove.")
            if not PACKAGE_NAME_RE.match(package):
                raise ValueError("Invalid package name.")
            selected_manager = self._select_package_manager(platform_name, manager, require_available=not dry_run)
            package_spec = f"{package}={version}" if version and selected_manager in {"apt-get"} else package
            command = self._build_package_command(platform_name, selected_manager, action, package_spec)
            plan = {
                "manager": selected_manager,
                "action": action,
                "package": package,
                "version": version,
                "command_template": command,
            }
            data = _common_request_data("manage_package", target, platform_name, dry_run, reason, approval_id, plan)
            if dry_run:
                return ToolEnvelope(
                    risk_level="high",
                    summary="Generated package management plan; package manager was not executed.",
                    data=data,
                )

            result = _run_command(command, timeout_seconds=timeout_seconds)
            data["result"] = _completed_process_to_data(result)
            data["post_checks"] = _command_post_checks(
                "package_manager_command",
                result,
                "Package manager command completed; verify installed version next.",
                "Package manager command failed; package state was not changed as requested.",
            )
            data["rollback_hint"] = _rollback_hint("manage_package", {"action": action, "package": package})
            return ToolEnvelope(
                ok=result.returncode == 0,
                risk_level="high",
                summary="Package manager command executed." if result.returncode == 0 else "Package manager command failed.",
                data=data,
            )
        except Exception as exc:
            return ToolEnvelope(
                ok=False,
                risk_level="high",
                summary="Failed to manage package.",
                data={"package": package, "action": action, "error": str(exc)},
            )

    def _select_package_manager(self, platform_name: str, manager: str, require_available: bool = True) -> str:
        if platform_name == "windows":
            selected = "winget" if manager == "auto" else manager
            if selected != "winget":
                raise ValueError("Only winget is supported on Windows in this template.")
            if require_available and not shutil.which("winget"):
                raise ValueError("winget was not found.")
            return selected

        selected = manager
        if manager == "auto":
            selected = next((candidate for candidate in PACKAGE_MANAGERS if shutil.which(candidate)), "")
            if not selected and not require_available:
                selected = "dnf"
        if selected not in PACKAGE_MANAGERS:
            raise ValueError("Unsupported Linux package manager.")
        if require_available and not shutil.which(selected):
            raise ValueError("No supported Linux package manager was found.")
        return selected

    def _build_package_command(self, platform_name: str, manager: str, action: str, package: str) -> list[str]:
        if platform_name == "windows":
            if action == "install":
                return ["winget", "install", "--id", package, "--silent"]
            if action == "upgrade":
                return ["winget", "upgrade", "--id", package, "--silent"]
            return ["winget", "uninstall", "--id", package, "--silent"]

        if manager == "apt-get":
            mapped = {"install": "install", "upgrade": "install", "remove": "remove"}[action]
            return ["apt-get", "-y", mapped, package]
        if manager in {"dnf", "yum", "zypper"}:
            mapped = {"install": "install", "upgrade": "upgrade", "remove": "remove"}[action]
            return [manager, "-y", mapped, package]
        raise ValueError("Unsupported package manager.")

    def request_network_policy_change(
        self,
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
    ) -> ToolEnvelope:
        platform_name = _normalize_platform(platform_hint)
        if _is_remote_target(target):
            original_action = action
            normalized_action = _normalize_network_action(action)
            command = self._build_network_command(
                platform_name,
                normalized_action if normalized_action in {"allow_port", "deny_port"} else "allow_port",
                protocol.lower(),
                port,
                source,
                rule_name,
                require_available=False,
            )
            plan = {
                "action": normalized_action,
                "requested_action": original_action,
                "protocol": protocol.lower(),
                "port": port,
                "source": source,
                "rule_name": rule_name,
                "command_template": command,
                "remote_username": remote_username,
                "remote_port": remote_port,
                "remote_auth_ref": remote_auth_ref,
                "remote_endpoint": remote_endpoint,
            }
            if dry_run:
                return _remote_reference_envelope(
                    action="network_policy_change",
                    target=target,
                    platform_name=platform_name,
                    dry_run=dry_run,
                    reason=reason,
                    approval_id=approval_id,
                    plan=plan,
                    summary="Generated remote network policy reference plan; no remote changes were made.",
                )
            return self._reject_remote(target)
        try:
            original_action = action
            action = _normalize_network_action(action)
            if action not in {"allow_port", "deny_port"}:
                raise ValueError("Only allow_port and deny_port are implemented in this first template.")
            if protocol.lower() not in {"tcp", "udp"}:
                raise ValueError("protocol must be tcp or udp.")
            if port < 1 or port > 65535:
                raise ValueError("port must be between 1 and 65535.")
            if port in {22, 3389, 5985, 5986} and action == "deny_port":
                raise ValueError("Refusing to deny common remote administration ports.")

            command = self._build_network_command(
                platform_name,
                action,
                protocol.lower(),
                port,
                source,
                rule_name,
                require_available=not dry_run,
            )
            plan = {
                "action": action,
                "requested_action": original_action,
                "protocol": protocol.lower(),
                "port": port,
                "source": source,
                "rule_name": rule_name,
                "command_template": command,
            }
            data = _common_request_data("network_policy_change", target, platform_name, dry_run, reason, approval_id, plan)
            if dry_run:
                return ToolEnvelope(
                    risk_level="high",
                    summary="Generated network policy plan; firewall was not changed.",
                    data=data,
                )

            result = _run_command(command, timeout_seconds=timeout_seconds)
            data["result"] = _completed_process_to_data(result)
            data["post_checks"] = _command_post_checks(
                "network_policy_command",
                result,
                "Firewall command completed; verify the effective rule next.",
                "Firewall command failed; effective network policy was not changed as requested.",
            )
            data["rollback_hint"] = _rollback_hint(
                "network_policy_change",
                {"action": action, "protocol": protocol.lower(), "port": port, "rule_name": rule_name},
            )
            return ToolEnvelope(
                ok=result.returncode == 0,
                risk_level="high",
                summary="Network policy command executed." if result.returncode == 0 else "Network policy command failed.",
                data=data,
            )
        except Exception as exc:
            return ToolEnvelope(
                ok=False,
                risk_level="high",
                summary="Failed to change network policy.",
                data={"action": action, "protocol": protocol, "port": port, "error": str(exc)},
            )

    def _build_network_command(
        self,
        platform_name: str,
        action: str,
        protocol: str,
        port: int,
        source: str,
        rule_name: str | None,
        require_available: bool = True,
    ) -> list[str]:
        display_name = rule_name or f"xingxuan_mcp_{action}_{protocol}_{port}"
        if platform_name == "windows":
            access = "Allow" if action == "allow_port" else "Block"
            command = (
                f"New-NetFirewallRule -DisplayName '{display_name}' "
                f"-Direction Inbound -Action {access} -Protocol {protocol.upper()} -LocalPort {port}"
            )
            if source:
                command += f" -RemoteAddress '{source}'"
            return ["powershell", "-NoProfile", "-Command", command]

        if shutil.which("firewall-cmd") or not require_available:
            if action == "allow_port":
                return ["firewall-cmd", "--add-port", f"{port}/{protocol}"]
            return ["firewall-cmd", "--remove-port", f"{port}/{protocol}"]
        raise ValueError("firewall-cmd was not found; nftables/iptables templates are not enabled yet.")

    def request_log_cleanup(
        self,
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
    ) -> ToolEnvelope:
        if mode not in {"archive", "truncate", "quarantine"}:
            return ToolEnvelope(
                ok=False,
                risk_level="high",
                summary="Unsupported log cleanup mode.",
                data={"path": path, "mode": mode, "status": "unsupported_mode"},
            )
        return self.request_delete_file(
            path=path,
            mode=mode,
            recursive=False,
            target=target,
            platform_hint=platform_hint,
            remote_username=remote_username,
            remote_port=remote_port,
            remote_auth_ref=remote_auth_ref,
            remote_endpoint=remote_endpoint,
            dry_run=dry_run,
            reason=reason,
            approval_id=approval_id,
        )
