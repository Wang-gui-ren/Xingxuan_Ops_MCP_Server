from __future__ import annotations

from pathlib import Path

from mcp.server.fastmcp import FastMCP

from mcp_ops_server.collectors import (
    collect_disk_summary,
    collect_host_profile,
    collect_listening_ports,
    collect_top_processes,
    find_large_files,
    get_service_status,
)
from mcp_ops_server.models import ToolEnvelope


def register_basic_tools(mcp: FastMCP) -> None:
    """注册基础只读采集工具。

    这一组工具负责回答“机器现在是什么状态”：磁盘、进程、端口、服务、
    主机画像等。它们原则上不修改系统，适合作为 Agent 排障前的事实来源。
    """

    @mcp.tool()
    def get_disk_usage() -> dict:
        # 只读采集所有可见分区的容量与使用率。
        data = collect_disk_summary()
        return ToolEnvelope(
            summary=f"Collected disk usage for {len(data)} partitions.",
            data={"partitions": data},
        ).model_dump()

    @mcp.tool()
    def list_processes(
        limit: int = 10,
        include_username: bool = False,
        timeout_seconds: float = 3.0,
    ) -> dict:
        # 默认只返回前若干个高资源占用进程，避免结果过长影响对话上下文。
        # Windows 上用户名解析可能较慢，因此默认关闭；需要时可显式 include_username=true。
        rows = collect_top_processes(
            limit=limit,
            include_username=include_username,
            timeout_seconds=timeout_seconds,
        )
        return ToolEnvelope(
            summary=f"Collected {len(rows)} process summaries.",
            data={
                "processes": rows,
                "collection": {
                    "timeout_seconds": timeout_seconds,
                    "include_username": include_username,
                    "strategy": "bounded_top_k_heap",
                },
            },
        ).model_dump()

    @mcp.tool()
    def get_listening_ports(limit: int = 50) -> dict:
        rows = collect_listening_ports(limit=limit)
        return ToolEnvelope(
            summary=f"Collected {len(rows)} listening port records.",
            data={"ports": rows},
        ).model_dump()

    @mcp.tool()
    def find_large_files_tool(
        root_path: str,
        min_size_mb: int = 100,
        limit: int = 20,
        timeout_seconds: float = 8.0,
        max_files_scanned: int = 50_000,
    ) -> dict:
        # 扫描目录可能较重，因此风险等级标为 medium，并限制最小大小和返回数量。
        base = Path(root_path).expanduser()
        data = find_large_files(
            str(base),
            min_size_mb=min_size_mb,
            limit=limit,
            timeout_seconds=timeout_seconds,
            max_files_scanned=max_files_scanned,
        )
        files = data.get("files", [])
        return ToolEnvelope(
            summary=(
                f"Found {len(files)} files >= {min_size_mb} MB under {base}."
                if not data.get("partial")
                else f"Found {len(files)} files >= {min_size_mb} MB under {base} before scan budget was exhausted."
            ),
            risk_level="medium",
            data=data,
            next_actions=(
                ["Narrow root_path or increase timeout_seconds for a more complete scan."]
                if data.get("partial")
                else []
            ),
        ).model_dump()

    @mcp.tool()
    def get_service_status_tool(service: str) -> dict:
        data = get_service_status(service)
        return ToolEnvelope(
            summary=f"Collected service status for {service}.",
            risk_level="medium",
            data=data,
        ).model_dump()

    @mcp.tool()
    def get_host_profile_tool(
        target: str = "local",
        platform_hint: str = "auto",
        username: str | None = None,
        port: int | None = None,
        timeout_seconds: int = 15,
    ) -> dict:
        """采集本机或远程主机画像，给 Agent 提供服务器配置上下文。"""
        data = collect_host_profile(
            target=target,
            platform_hint=platform_hint,
            username=username,
            port=port,
            timeout_seconds=timeout_seconds,
        )
        risk_level = "low" if data["collection"]["success"] else "medium"
        return ToolEnvelope(
            ok=data["collection"]["success"],
            summary=(
                f"Collected {data['platform']} host profile for {target}."
                if data["collection"]["success"]
                else f"Failed to collect host profile for {target}."
            ),
            risk_level=risk_level,
            data=data,
            next_actions=[
                "For Linux targets, ensure SSH key or agent-based authentication is ready.",
                "For Windows targets, ensure PowerShell Remoting / WinRM is enabled.",
            ],
        ).model_dump()
