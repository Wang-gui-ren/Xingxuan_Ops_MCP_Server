from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from mcp_ops_server.collectors import (
    collect_cpu_summary,
    collect_disk_summary,
    collect_local_host_profile,
    collect_listening_ports,
    collect_memory_summary,
    collect_system_summary,
    collect_top_processes,
)


def register_resources(mcp: FastMCP) -> None:
    @mcp.resource("os://system/summary")
    def system_summary() -> dict:
        return collect_system_summary()

    @mcp.resource("os://cpu/summary")
    def cpu_summary() -> dict:
        return collect_cpu_summary()

    @mcp.resource("os://memory/summary")
    def memory_summary() -> dict:
        return collect_memory_summary()

    @mcp.resource("os://disk/summary")
    def disk_summary() -> list[dict]:
        return collect_disk_summary()

    @mcp.resource("os://process/top")
    def process_top() -> list[dict]:
        return collect_top_processes()

    @mcp.resource("os://network/listeners")
    def network_listeners() -> list[dict]:
        return collect_listening_ports()

    @mcp.resource("os://host/profile")
    def host_profile() -> dict:
        return collect_local_host_profile()
