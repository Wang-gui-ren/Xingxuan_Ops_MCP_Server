from __future__ import annotations

from mcp.server.fastmcp import FastMCP


def register_prompts(mcp: FastMCP) -> None:
    @mcp.prompt()
    def diagnose_disk_full(mount_point: str = "/") -> str:
        return f"""
You are diagnosing disk pressure for mount point `{mount_point}`.

Follow this sequence:
1. Read disk summary.
2. Check large files under likely log or data directories.
3. Identify whether the largest files are logs, databases, caches, or user files.
4. Explain evidence before proposing any cleanup.
5. If cleanup is needed, require risk review and approval before any destructive action.

Output:
- symptom
- evidence
- possible root causes
- recommended next step
- risk note
""".strip()

    @mcp.prompt()
    def analyze_port_conflict(port: int) -> str:
        return f"""
You are diagnosing a port conflict for port `{port}`.

Follow this sequence:
1. Check listening ports and process ownership.
2. Identify the service or process bound to the target port.
3. Explain whether the binding is expected.
4. Do not recommend killing or restarting anything without approval.

Output:
- observed process
- expected vs unexpected
- impact
- recommended next step
""".strip()

    @mcp.prompt()
    def assess_log_cleanup_risk(path: str) -> str:
        return f"""
Assess the cleanup risk for log file `{path}`.

Check:
1. Whether it belongs to a critical service.
2. Whether it looks like a database, audit, or security log.
3. Whether archive is safer than truncate/delete.
4. Whether approval is required.

Output:
- file role
- risk level
- safer alternative
- approval requirement
""".strip()

    @mcp.prompt()
    def analyze_server_profile(target: str = "local") -> str:
        return f"""
You are analyzing the server configuration profile for `{target}`.

Follow this sequence:
1. Read `os://host/profile` when the target is local, or call `get_host_profile_tool` for a remote target.
2. Identify OS family, version, CPU shape, memory pressure, disk layout, and exposed listening ports.
3. Highlight anything that affects operations decisions, such as low free disk, missing swap, or many exposed ports.
4. Keep facts and inferences separate.
5. If remote collection fails, explain the access prerequisite instead of guessing.
6. When the profile includes both `boot_time` and `boot_time_iso`, prefer the ISO timestamp in user-facing output.

Output:
- platform summary
- hardware summary
- storage summary
- network exposure
- operations implications
- missing data or access blockers
""".strip()
