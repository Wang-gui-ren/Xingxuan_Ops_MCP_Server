from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from mcp_ops_server.collectors import (
    diagnose_disk_full,
    diagnose_high_cpu,
    diagnose_port_conflict,
    diagnose_service_issue,
    diagnose_website_down,
    run_troubleshooting_pipeline,
)
from mcp_ops_server.models import ToolEnvelope
from mcp_ops_server.ops_sops import get_ops_sop, list_ops_sops
from mcp_ops_server.presentation import (
    attach_human_report,
    build_pipeline_report,
    build_sop_detail_report,
    build_sop_list_report,
)


def register_pipeline_tools(mcp: FastMCP) -> None:
    """注册经典故障排查流水线工具。

    流水线工具把多个只读采集动作组合成固定 SOP，适合比赛演示“自然语言
    -> 环境感知 -> 排查结论 -> 下一步建议”的闭环，但不直接修改系统。
    """

    @mcp.tool()
    def list_ops_sops_tool(include_prompts: bool = False) -> dict:
        """列出内置运维 SOP 元数据。

        该工具只返回排障流程设计，不执行任何系统采集或修复动作。
        """
        sops = list_ops_sops(include_prompts=include_prompts)
        result = ToolEnvelope(
            risk_level="low",
            summary=f"Returned {len(sops)} built-in operations SOP definition(s).",
            data={
                "sops": sops,
                "count": len(sops),
                "read_only": True,
                "execution_boundary": "SOP tools only describe diagnosis flow; remediation must use request_* dry-run templates.",
            },
            next_actions=[
                "Pick one scenario and call get_ops_sop_tool for detailed steps.",
                "Run the corresponding diagnose_* tool before generating any request_* dry-run plan.",
            ],
        ).model_dump()
        return attach_human_report(result, build_sop_list_report(sops))

    @mcp.tool()
    def get_ops_sop_tool(scenario: str, include_prompts: bool = True) -> dict:
        """按场景查询一条运维 SOP。"""
        sop = get_ops_sop(scenario, include_prompts=include_prompts)
        if sop is None:
            return ToolEnvelope(
                ok=False,
                risk_level="low",
                summary=f"Operations SOP not found: {scenario}.",
                data={
                    "scenario": scenario,
                    "available_scenarios": [item["scenario"] for item in list_ops_sops(include_prompts=False)],
                },
            ).model_dump()
        result = ToolEnvelope(
            risk_level="low",
            summary=f"Returned operations SOP for scenario: {sop['scenario']}.",
            data={"sop": sop, "read_only": True},
            next_actions=[
                "Follow read_only_steps first to gather evidence.",
                "If remediation is needed, generate a request_* dry-run plan and inspect guardrail_decision.",
            ],
        ).model_dump()
        return attach_human_report(result, build_sop_detail_report(sop))

    @mcp.tool()
    def diagnose_website_down_tool(
        url: str,
        host: str | None = None,
        port: int | None = None,
        service: str | None = None,
        log_path: str | None = None,
        include_trace: bool = False,
    ) -> dict:
        data = diagnose_website_down(
            url=url,
            host=host,
            port=port,
            service=service,
            log_path=log_path,
            include_trace=include_trace,
        )
        failed = [step["name"] for step in data["steps"] if not step.get("ok")]
        result = ToolEnvelope(
            ok=not failed,
            summary=(
                "Website troubleshooting pipeline completed without failed checks."
                if not failed
                else f"Website troubleshooting pipeline found failed checks: {', '.join(failed)}."
            ),
            risk_level="medium",
            data=data,
            next_actions=data["next_actions"],
        ).model_dump()
        return _with_pipeline_report(result, data)

    @mcp.tool()
    def diagnose_high_cpu_tool(limit: int = 10) -> dict:
        data = diagnose_high_cpu(limit=limit)
        suspects = data["steps"][2]["data"]["processes"]
        result = ToolEnvelope(
            summary=f"High CPU pipeline completed; found {len(suspects)} suspect process records.",
            risk_level="medium",
            data=data,
            next_actions=data["next_actions"],
        ).model_dump()
        return _with_pipeline_report(result, data)

    @mcp.tool()
    def diagnose_disk_full_tool(root_path: str = ".", min_size_mb: int = 100, limit: int = 20) -> dict:
        data = diagnose_disk_full(root_path=root_path, min_size_mb=min_size_mb, limit=limit)
        pressure = data["steps"][0]["data"]["pressure"]
        result = ToolEnvelope(
            summary=f"Disk troubleshooting pipeline completed; found {len(pressure)} high-usage partitions.",
            risk_level="medium",
            data=data,
            next_actions=data["next_actions"],
        ).model_dump()
        return _with_pipeline_report(result, data)

    @mcp.tool()
    def diagnose_port_conflict_tool(port: int, limit: int = 120) -> dict:
        data = diagnose_port_conflict(port=port, limit=limit)
        matches = data["steps"][0]["data"]["matches"]
        result = ToolEnvelope(
            ok=bool(matches),
            summary=f"Port conflict pipeline found {len(matches)} listener records for port {port}.",
            risk_level="medium",
            data=data,
            next_actions=data["next_actions"],
        ).model_dump()
        return _with_pipeline_report(result, data)

    @mcp.tool()
    def diagnose_service_issue_tool(service: str, log_path: str | None = None) -> dict:
        data = diagnose_service_issue(service=service, log_path=log_path)
        result = ToolEnvelope(
            summary=f"Service troubleshooting pipeline completed for {service}.",
            risk_level="medium",
            data=data,
            next_actions=data["next_actions"],
        ).model_dump()
        return _with_pipeline_report(result, data)

    @mcp.tool()
    def run_troubleshooting_pipeline_tool(
        scenario: str,
        url: str | None = None,
        host: str | None = None,
        port: int | None = None,
        service: str | None = None,
        log_path: str | None = None,
        root_path: str = ".",
        min_size_mb: int = 100,
        limit: int = 20,
    ) -> dict:
        """按场景名称自动分发到对应排障 SOP。"""
        try:
            data = run_troubleshooting_pipeline(
                scenario=scenario,
                url=url,
                host=host,
                port=port,
                service=service,
                log_path=log_path,
                root_path=root_path,
                min_size_mb=min_size_mb,
                limit=limit,
            )
            failed = [step["name"] for step in data["steps"] if not step.get("ok")]
            result = ToolEnvelope(
                ok=not failed,
                summary=(
                    f"Troubleshooting pipeline {scenario} completed."
                    if not failed
                    else f"Troubleshooting pipeline {scenario} completed with failed checks: {', '.join(failed)}."
                ),
                risk_level="medium",
                data=data,
                next_actions=data["next_actions"],
            ).model_dump()
            return _with_pipeline_report(result, data)
        except Exception as exc:
            return ToolEnvelope(
                ok=False,
                summary=f"Failed to run troubleshooting pipeline {scenario}.",
                risk_level="medium",
                data={"scenario": scenario, "error": str(exc)},
            ).model_dump()


def _with_pipeline_report(result: dict, data: dict) -> dict:
    scenario = str(data.get("scenario") or "unknown")
    sop = get_ops_sop(scenario, include_prompts=False)
    if sop:
        result.setdefault("data", {})
        if isinstance(result["data"], dict):
            result["data"]["sop_id"] = sop.get("scenario")
            result["data"]["sop_summary"] = sop.get("summary")
    return attach_human_report(result, build_pipeline_report(scenario=scenario, envelope=result, sop=sop))
