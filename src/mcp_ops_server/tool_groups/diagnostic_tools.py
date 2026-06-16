from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from mcp_ops_server.collectors import (
    check_http_endpoint,
    check_network_connectivity,
    check_platform_compatibility,
    collect_network_connections,
    detect_large_logs,
    get_file_stat,
    get_journal_events,
    list_system_services,
    read_log_excerpt,
    resolve_dns,
    trace_route,
)
from mcp_ops_server.models import ToolEnvelope


def register_diagnostic_tools(mcp: FastMCP) -> None:
    """注册常用运维口令对应的只读诊断工具。

    这一组工具面向“发生了什么问题”：网络连通性、DNS、HTTP、日志片段、
    文件元信息、连接表和服务列表。它们尽量设置超时、数量或大小限制。
    """

    @mcp.tool()
    def check_network_connectivity_tool(host: str, count: int = 3, timeout_seconds: int = 10) -> dict:
        data = check_network_connectivity(host=host, count=count, timeout_seconds=timeout_seconds)
        return ToolEnvelope(
            ok=data["reachable"],
            summary=f"Checked network connectivity to {host}.",
            risk_level="low",
            data=data,
        ).model_dump()

    @mcp.tool()
    def trace_route_tool(host: str, max_hops: int = 12, timeout_seconds: int = 20) -> dict:
        data = trace_route(host=host, max_hops=max_hops, timeout_seconds=timeout_seconds)
        return ToolEnvelope(
            ok=data["result"]["ok"],
            summary=f"Collected route trace to {host}.",
            risk_level="low",
            data=data,
        ).model_dump()

    @mcp.tool()
    def resolve_dns_tool(host: str, timeout_seconds: int = 5) -> dict:
        data = resolve_dns(host=host, timeout_seconds=timeout_seconds)
        return ToolEnvelope(
            ok=data["resolved"],
            summary=f"Resolved DNS for {host}.",
            risk_level="low",
            data=data,
        ).model_dump()

    @mcp.tool()
    def check_http_endpoint_tool(url: str, timeout_seconds: int = 10) -> dict:
        data = check_http_endpoint(url=url, timeout_seconds=timeout_seconds)
        return ToolEnvelope(
            ok=data["ok"],
            summary=f"Checked HTTP endpoint {data['url']}.",
            risk_level="low",
            data=data,
        ).model_dump()

    @mcp.tool()
    def get_file_stat_tool(path: str, include_hash: bool = False) -> dict:
        data = get_file_stat(path=path, include_hash=include_hash)
        return ToolEnvelope(
            ok=data["exists"],
            summary=f"Collected file metadata for {path}.",
            risk_level="low",
            data=data,
        ).model_dump()

    @mcp.tool()
    def read_log_excerpt_tool(
        path: str,
        lines: int = 100,
        keyword: str | None = None,
        max_bytes: int = 1024 * 1024,
    ) -> dict:
        # 日志可能包含敏感上下文，因此默认只读取尾部片段，并限制最大读取字节数。
        data = read_log_excerpt(path=path, lines=lines, keyword=keyword, max_bytes=max_bytes)
        return ToolEnvelope(
            ok=data["ok"],
            summary=f"Read log excerpt from {path}.",
            risk_level="medium",
            data=data,
        ).model_dump()

    @mcp.tool()
    def get_network_connections(limit: int = 50, status: str | None = None) -> dict:
        rows = collect_network_connections(limit=limit, status=status)
        return ToolEnvelope(
            summary=f"Collected {len(rows)} network connection records.",
            risk_level="low",
            data={"connections": rows},
        ).model_dump()

    @mcp.tool()
    def get_system_services(limit: int = 80) -> dict:
        data = list_system_services(limit=limit)
        return ToolEnvelope(
            ok=data["supported"],
            summary=f"Collected system service list for {data['platform']}.",
            risk_level="medium",
            data=data,
        ).model_dump()

    @mcp.tool()
    def get_journal_events_tool(
        unit: str | None = None,
        priority: str = "warning",
        lines: int = 80,
        since: str = "24 hours ago",
        timeout_seconds: int = 10,
    ) -> dict:
        data = get_journal_events(
            unit=unit,
            priority=priority,
            lines=lines,
            since=since,
            timeout_seconds=timeout_seconds,
        )
        return ToolEnvelope(
            ok=data["supported"],
            summary=(
                f"Collected {data.get('line_count', 0)} journal events."
                if data["supported"]
                else f"Journal events are not supported on {data['platform']}."
            ),
            risk_level="medium",
            data=data,
        ).model_dump()

    @mcp.tool()
    def detect_large_logs_tool(
        root_path: str,
        min_size_mb: int = 100,
        limit: int = 20,
        timeout_seconds: float = 8.0,
    ) -> dict:
        data = detect_large_logs(
            root_path=root_path,
            min_size_mb=min_size_mb,
            limit=limit,
            timeout_seconds=timeout_seconds,
        )
        return ToolEnvelope(
            summary=f"Detected {len(data['logs'])} large log-like files under {data['root_path']}.",
            risk_level="medium",
            data=data,
            next_actions=[
                "Classify logs before cleanup; database and audit logs require extra verification.",
                "Use request_log_cleanup with dry_run=true before any archive/truncate action.",
            ],
        ).model_dump()

    @mcp.tool()
    def check_platform_compatibility_tool() -> dict:
        data = check_platform_compatibility()
        return ToolEnvelope(
            summary=f"Checked platform compatibility for {data['system']} {data['machine']}.",
            risk_level="low",
            data=data,
            next_actions=[
                "Validate LoongArch/Kylin compatibility on the real target host before final competition deployment.",
            ],
        ).model_dump()
