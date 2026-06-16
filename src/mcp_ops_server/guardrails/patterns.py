from __future__ import annotations

import re

from mcp_ops_server.models import RiskLevel


PatternRule = tuple[str, str, re.Pattern[str], RiskLevel, str, str]


PROMPT_INJECTION_PATTERNS: tuple[PatternRule, ...] = (
    (
        "PROMPT_IGNORE_POLICY",
        "prompt_injection",
        re.compile(r"(ignore|bypass|override).{0,40}(previous|system|developer|safety|policy|guardrail)", re.I),
        "critical",
        "疑似要求忽略系统规则或安全护栏。",
        "不要执行该请求；要求用户重新描述合法运维目标。",
    ),
    (
        "PROMPT_SKIP_AUDIT",
        "prompt_injection",
        re.compile(r"(不要|无需|跳过|绕过|do not|skip).{0,30}(审计|日志|记录|审批|确认|audit|log|approval)", re.I),
        "critical",
        "疑似诱导跳过审计、日志记录或审批。",
        "保持审计开启，并返回需要审批或拒绝原因。",
    ),
    (
        "PROMPT_ROLEPLAY_ROOT",
        "prompt_injection",
        re.compile(r"(假装|pretend).{0,40}(root|administrator|管理员|sudo)", re.I),
        "high",
        "疑似通过角色扮演诱导越权操作。",
        "只允许通过固定 MCP 工具和审批流程处理。",
    ),
)


COMMAND_PATTERNS: tuple[PatternRule, ...] = (
    (
        "CMD_RM_RF",
        "destructive_command",
        re.compile(r"(^|[\r\n;&|]\s*)(sudo\s+)?rm\s+(--\s+)?(-[^\s]*[rR][fF][^\s]*|-[^\s]*[fF][rR][^\s]*)(\s|$)", re.I),
        "critical",
        "检测到递归强制删除命令。",
        "改用 find_large_files_tool 定位文件，再用 request_log_cleanup 生成 dry-run 计划。",
    ),
    (
        "CMD_FIND_DELETE",
        "destructive_command",
        re.compile(r"\bfind\b.+(?:^|\s)-delete(?:\s|$)|\bfind\b.+(?:^|\s)-exec\s+rm\b", re.I),
        "critical",
        "检测到 find 批量删除命令。",
        "先输出候选文件清单，再走审批后的固定清理模板。",
    ),
    (
        "CMD_WINDOWS_FORCE_DELETE",
        "destructive_command",
        re.compile(r"\b(remove-item|del|rmdir)\b.+(-recurse|/s).+(-force|/q)", re.I),
        "critical",
        "检测到 Windows 强制递归删除命令。",
        "改用 request_delete_file 的 quarantine/archive 模式。",
    ),
    (
        "CMD_FORMAT_OR_WIPE",
        "destructive_command",
        re.compile(r"\b(mkfs|fdisk|parted)\b|\bdd\s+if=.+\bof=/dev/|\bformat\s+[a-z]:", re.I),
        "critical",
        "检测到格式化、分区或块设备覆盖写入。",
        "该类操作不应由当前 MCP Server 执行。",
    ),
    (
        "CMD_CHMOD_PERMISSIVE",
        "permission_escalation",
        re.compile(r"\bchmod\b.+\b(777|0777|a\+rwx|ugo\+rwx)\b", re.I),
        "critical",
        "检测到危险的权限放开操作。",
        "先读取 get_file_stat，再按最小权限原则生成修复计划。",
    ),
    (
        "CMD_CHMOD_ZERO",
        "permission_escalation",
        re.compile(r"\bchmod\b.+\b(000|0000)\b", re.I),
        "critical",
        "检测到可能导致服务不可用的权限清零操作。",
        "先说明影响范围，并通过审批后的固定权限模板处理。",
    ),
    (
        "CMD_CHOWN_RECURSIVE",
        "permission_escalation",
        re.compile(r"\bchown\b\s+-R\b", re.I),
        "high",
        "检测到递归修改属主操作。",
        "限制到明确路径，并要求审批。",
    ),
    (
        "CMD_DOWNLOAD_EXECUTE",
        "network_exfiltration",
        re.compile(r"(curl|wget).{0,120}\|\s*(sh|bash)|\biex\b|invoke-expression|powershell\s+-enc|frombase64string", re.I),
        "critical",
        "检测到下载后执行、编码执行或 PowerShell 动态执行。",
        "禁止隐藏执行链路；改为人工审查脚本内容。",
    ),
    (
        "CMD_DISABLE_SECURITY",
        "service_disruption",
        re.compile(r"(systemctl|service)\s+(stop|disable).{0,60}(firewalld|iptables|ufw|auditd|sshd)|stop-service.+(mpssvc|windefend)", re.I),
        "critical",
        "检测到停止或禁用关键安全/远程管理服务。",
        "该类操作必须人工处理，不允许自动执行。",
    ),
)


PATH_TRAVERSAL_PATTERN = re.compile(r"(^|[\\/])\.\.([\\/]|$)")

SENSITIVE_PATH_KEYWORDS = (
    "mysql",
    "mariadb",
    "postgres",
    "postgresql",
    "oracle",
    "redis",
    "mongodb",
    "etcd",
    "kube",
    "docker",
    "containerd",
    "audit",
)

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
)

PROTECTED_WINDOWS_PREFIXES = (
    "c:\\windows",
    "c:\\program files",
    "c:\\program files (x86)",
    "c:\\programdata\\microsoft",
)

SENSITIVE_WINDOWS_PATH_MARKERS = (
    "\\appdata\\",
    "\\programdata\\",
)
