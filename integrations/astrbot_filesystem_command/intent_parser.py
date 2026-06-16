from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


CREATE_DIR_PATTERNS = (
    re.compile(
        r"在(?P<base>.+?)这个(?:文件夹|目录)(?:里|中)?新建一个空(?:文件夹|目录)[:：]?(?:名字叫|名称为|叫)?[\"“](?P<name>[^\"”]+)[\"”]",
        re.IGNORECASE,
    ),
    re.compile(
        r"在(?P<base>.+?)这个(?:文件夹|目录)(?:里|中)?新建一个空(?:文件夹|目录)[:：]?(?:(?:名字叫|名称为|叫)\s*)?(?P<name>[A-Za-z0-9_.\-\u4e00-\u9fff]+)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:新建|创建)(?:一个)?(?:空)?(?:文件夹|目录)[:：]?(?P<name>[A-Za-z0-9_.\-\u4e00-\u9fff]+)\s*(?:到|在)\s*(?P<base>.+)",
        re.IGNORECASE,
    ),
)
CREATE_FILE_PATTERNS = (
    re.compile(
        r"在(?P<base>.+?)(?:中|里)(?:建立|新建|创建)一个文件[:：]?\s*(?P<name>[A-Za-z0-9_.\-\u4e00-\u9fff]+)(?:\s*并写入\s*(?P<content>\{.*\}|.+))?$",
        re.IGNORECASE,
    ),
    re.compile(
        r"创建文件\s*(?P<name>[A-Za-z0-9_.\-\u4e00-\u9fff]+)\s*到\s*(?P<base>.+?)(?:\s*并写入\s*(?P<content>\{.*\}|.+))?$",
        re.IGNORECASE,
    ),
)
RESTART_SERVICE_PATTERNS = (
    re.compile(r"重启(?:服务)?\s*(?P<service>Spooler|spooler|nginx|打印后台处理服务)\s*(?:服务)?", re.IGNORECASE),
    re.compile(r"(?P<service>Spooler|spooler|nginx|打印后台处理服务)\s*服务(?:需要)?重启", re.IGNORECASE),
)
REMOTE_RESTART_SERVICE_PATTERNS = (
    re.compile(
        r"重启远程\s*(?P<platform>linux|windows)\s*(?:主机|服务器)\s*(?P<target>[A-Za-z0-9_.:-]+)\s*上的\s*(?P<service>[A-Za-z0-9_.@:-]+)\s*服务"
        r"(?:\s*(?:用户|账号)\s*(?P<username>[A-Za-z0-9_.-]+))?"
        r"(?:\s*(?:端口|port)\s*(?P<port>\d{1,5}))?",
        re.IGNORECASE,
    ),
    re.compile(
        r"重启远程\s*(?P<platform>windows)\s*(?:主机|服务器)\s*(?P<target>[A-Za-z0-9_.:-]+)\s*上的\s*(?P<service>Spooler|spooler|打印后台处理服务)\s*服务"
        r"(?:\s*(?:用户|账号)\s*(?P<username>[A-Za-z0-9_.-]+))?"
        r"(?:\s*(?:端口|port)\s*(?P<port>\d{1,5}))?",
        re.IGNORECASE,
    ),
)
NETWORK_POLICY_PATTERN = re.compile(
    r"(?P<action>开放|允许|打开|阻断|封禁|关闭|拒绝)\s*(?:(?P<protocol>tcp|udp)\s*)?(?P<port>\d{1,5})\s*端口",
    re.IGNORECASE,
)
ARCHIVE_LOG_PATTERN = re.compile(
    r"(?:归档|存档)\s*(?P<path>(?:[A-Za-z]:[\\/][^\s\"”]+|/[^\s\"”]+))",
    re.IGNORECASE,
)
QUARANTINE_LOG_PATTERN = re.compile(
    r"隔离\s*(?P<path>(?:[A-Za-z]:[\\/][^\s\"”]+|/[^\s\"”]+))",
    re.IGNORECASE,
)
LOCAL_PROFILE_PATTERNS = (
    re.compile(
        r"^(?:帮我)?\s*(?:查询|查看|获取|读取|采集|看一下|看下|查一下|查下|查)\s*(?:一下)?\s*"
        r"(?:(?:这台|当前)\s*)?(?:电脑|本机|主机|服务器|系统)\s*(?:的)?\s*"
        r"(?:配置|信息|画像|硬件信息|系统信息)\s*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:帮我)?\s*(?:查询|查看|获取|读取|采集|看一下|看下|查一下|查下|查)\s*(?:一下)?\s*"
        r"(?:电脑配置|本机配置|主机配置|系统配置|系统信息|硬件信息|主机画像|配置画像)\s*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:电脑配置|本机配置|主机配置|系统配置|系统信息|硬件信息|主机画像|配置画像)$",
        re.IGNORECASE,
    ),
)
REMOTE_PROFILE_PATTERNS = (
    re.compile(
        r"(?:查看|采集|获取|读取|分析)\s*(?:远程)?\s*(?P<platform>linux|windows)\s*(?:主机|服务器)\s*(?P<target>[A-Za-z0-9_.:-]+)"
        r"(?:\s*(?:用户|账号)\s*(?P<username>[A-Za-z0-9_.-]+))?"
        r"(?:\s*(?:端口|port)\s*(?P<port>\d{1,5}))?\s*的?\s*(?:主机画像|配置画像|服务器画像|画像)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:查看|采集|获取|读取|分析)\s*(?P<target>[A-Za-z0-9_.:-]+)\s*的\s*(?P<platform>linux|windows)\s*(?:主机|服务器)"
        r"(?:\s*(?:用户|账号)\s*(?P<username>[A-Za-z0-9_.-]+))?"
        r"(?:\s*(?:端口|port)\s*(?P<port>\d{1,5}))?\s*(?:主机画像|配置画像|服务器画像|画像)",
        re.IGNORECASE,
    ),
)

WINDOWS_HINT_WORDS = ("windows", "win", "spooler", "打印后台处理服务")
LINUX_HINT_WORDS = ("linux", "麒麟", "nginx")
SERVICE_ALIASES = {
    "spooler": ("Spooler", "windows"),
    "打印后台处理服务": ("Spooler", "windows"),
    "nginx": ("nginx", "linux"),
}
NETWORK_ACTIONS = {
    "开放": "allow",
    "允许": "allow",
    "打开": "allow",
    "阻断": "deny",
    "封禁": "deny",
    "关闭": "deny",
    "拒绝": "deny",
}


@dataclass
class DeterministicIntent:
    tool_name: str
    arguments: dict[str, Any]
    summary: str


def parse_intent(text: str) -> DeterministicIntent | None:
    return (
        _parse_remote_host_profile_intent(text)
        or _parse_local_host_profile_intent(text)
        or
        _parse_remote_restart_service_intent(text)
        or
        _parse_create_file_intent(text)
        or
        _parse_create_directory_intent(text)
        or _parse_restart_service_intent(text)
        or _parse_network_policy_intent(text)
        or _parse_log_cleanup_intent(text)
    )


def _parse_local_host_profile_intent(text: str) -> DeterministicIntent | None:
    if not any(pattern.search(text) for pattern in LOCAL_PROFILE_PATTERNS):
        return None
    return DeterministicIntent(
        tool_name="get_host_profile_tool",
        arguments={
            "target": "local",
            "platform_hint": _infer_platform_hint(text=text),
            "timeout_seconds": 8,
        },
        summary="本机主机画像",
    )


def _parse_remote_host_profile_intent(text: str) -> DeterministicIntent | None:
    for pattern in REMOTE_PROFILE_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        target = _clean_token(match.group("target"))
        platform_hint = _clean_token(match.group("platform")).lower()
        username = _clean_token(match.groupdict().get("username"))
        port_text = _clean_token(match.groupdict().get("port"))
        port = None
        if port_text:
            try:
                port = int(port_text)
            except ValueError:
                return None
        if not target or platform_hint not in {"linux", "windows"}:
            continue
        arguments: dict[str, Any] = {
            "target": target,
            "platform_hint": platform_hint,
            "timeout_seconds": 8,
        }
        if username:
            arguments["username"] = username
        if port is not None:
            arguments["port"] = port
        return DeterministicIntent(
            tool_name="get_host_profile_tool",
            arguments=arguments,
            summary="远程主机画像",
        )
    return None


def _parse_create_directory_intent(text: str) -> DeterministicIntent | None:
    for pattern in CREATE_DIR_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        base = _clean_token(match.group("base"))
        name = _clean_token(match.group("name"))
        if not base or not name:
            continue
        full_path = _join_directory_path(base, name)
        platform_hint = _infer_platform_hint(text=text, path=full_path)
        return DeterministicIntent(
            tool_name="request_create_directory",
            arguments={
                "path": full_path,
                "create_parents": True,
                "platform_hint": platform_hint,
                "dry_run": True,
                "reason": "astrbot deterministic ops bridge: create_directory",
            },
            summary="目录创建",
        )
    return None


def _parse_create_file_intent(text: str) -> DeterministicIntent | None:
    for pattern in CREATE_FILE_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        base = _clean_token(match.group("base"))
        name = _clean_token(match.group("name"))
        if not base or not name:
            continue
        content = _clean_token(match.groupdict().get("content")) or ""
        full_path = _join_directory_path(base, name)
        platform_hint = _infer_platform_hint(text=text, path=full_path)
        return DeterministicIntent(
            tool_name="request_create_file",
            arguments={
                "path": full_path,
                "content": content,
                "overwrite_if_exists": False,
                "create_parents": False,
                "platform_hint": platform_hint,
                "dry_run": True,
                "reason": "astrbot deterministic ops bridge: create_file",
            },
            summary="鏂囦欢鍒涘缓",
        )
    return None


def _parse_remote_restart_service_intent(text: str) -> DeterministicIntent | None:
    for pattern in REMOTE_RESTART_SERVICE_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        target = _clean_token(match.group("target"))
        platform_hint = _clean_token(match.group("platform")).lower()
        service = _clean_token(match.group("service"))
        if service.lower() == "打印后台处理服务":
            service = "Spooler"
        username = _clean_token(match.groupdict().get("username"))
        port_text = _clean_token(match.groupdict().get("port"))
        port = None
        if port_text:
            try:
                port = int(port_text)
            except ValueError:
                return None
        if not target or not service or platform_hint not in {"linux", "windows"}:
            continue
        arguments: dict[str, Any] = {
            "service": service,
            "target": target,
            "platform_hint": platform_hint,
            "dry_run": True,
            "reason": "astrbot deterministic ops bridge: remote_restart_service",
        }
        if username:
            arguments["remote_username"] = username
        if port is not None:
            arguments["remote_port"] = port
        return DeterministicIntent(
            tool_name="request_restart_service",
            arguments=arguments,
            summary="远程服务重启计划",
        )
    return None


def _parse_restart_service_intent(text: str) -> DeterministicIntent | None:
    for pattern in RESTART_SERVICE_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        raw_service = _clean_token(match.group("service"))
        service, default_platform = SERVICE_ALIASES.get(raw_service.lower(), (raw_service, "auto"))
        platform_hint = _infer_platform_hint(text=text, default=default_platform)
        return DeterministicIntent(
            tool_name="request_restart_service",
            arguments={
                "service": service,
                "platform_hint": platform_hint,
                "dry_run": True,
                "reason": "astrbot deterministic ops bridge: restart_service",
            },
            summary="服务重启",
        )
    return None


def _parse_network_policy_intent(text: str) -> DeterministicIntent | None:
    match = NETWORK_POLICY_PATTERN.search(text)
    if not match:
        return None
    action_word = _clean_token(match.group("action"))
    protocol = (_clean_token(match.group("protocol")) or "tcp").lower()
    port_text = _clean_token(match.group("port"))
    try:
        port = int(port_text)
    except ValueError:
        return None
    action = NETWORK_ACTIONS.get(action_word)
    if action is None:
        return None
    platform_hint = _infer_platform_hint(text=text)
    return DeterministicIntent(
        tool_name="request_network_policy_change",
        arguments={
            "action": action,
            "protocol": protocol,
            "port": port,
            "platform_hint": platform_hint,
            "dry_run": True,
            "reason": "astrbot deterministic ops bridge: network_policy_change",
        },
        summary="网络策略变更",
    )


def _parse_log_cleanup_intent(text: str) -> DeterministicIntent | None:
    for pattern, mode in ((ARCHIVE_LOG_PATTERN, "archive"), (QUARANTINE_LOG_PATTERN, "quarantine")):
        match = pattern.search(text)
        if not match:
            continue
        path = _clean_token(match.group("path"))
        if not path:
            continue
        platform_hint = _infer_platform_hint(text=text, path=path)
        return DeterministicIntent(
            tool_name="request_log_cleanup",
            arguments={
                "path": path,
                "mode": mode,
                "platform_hint": platform_hint,
                "dry_run": True,
                "reason": "astrbot deterministic ops bridge: log_cleanup",
            },
            summary="日志清理",
        )
    return None


def _join_directory_path(base: str, name: str) -> str:
    if base.endswith("\\") or base.endswith("/"):
        return f"{base}{name}"
    if re.match(r"^[A-Za-z]:[\\/]", base):
        return base + ("\\" + name)
    return base.rstrip("/\\") + "/" + name


def _infer_platform_hint(*, text: str, path: str | None = None, default: str = "auto") -> str:
    lowered = text.lower()
    if any(word in lowered for word in WINDOWS_HINT_WORDS):
        return "windows"
    if any(word in lowered for word in LINUX_HINT_WORDS):
        return "linux"
    if path and re.match(r"^[A-Za-z]:[\\/]", path):
        return "windows"
    if path and path.startswith("/"):
        return "linux"
    return default


def clean_token(value: str | None) -> str:
    return _clean_token(value)


def _clean_token(value: str | None) -> str:
    text = str(value or "").strip().strip("`'\"“”")
    return re.sub(r"[。．.!！；;，,]$", "", text).strip()
