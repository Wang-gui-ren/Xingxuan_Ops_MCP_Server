from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class OpsSop:
    """只读运维 SOP 元数据。

    SOP 不直接执行修复动作，而是告诉 Agent 应按什么顺序感知、判断和申请变更。
    """

    scenario: str
    aliases: tuple[str, ...]
    summary: str
    symptoms: tuple[str, ...]
    read_only_steps: tuple[dict[str, Any], ...]
    decision_points: tuple[str, ...]
    recommended_write_templates: tuple[str, ...]
    guardrail_notes: tuple[str, ...]
    astrbot_prompts: tuple[str, ...]

    def to_dict(self, include_prompts: bool = True) -> dict[str, Any]:
        payload = {
            "scenario": self.scenario,
            "aliases": list(self.aliases),
            "summary": self.summary,
            "symptoms": list(self.symptoms),
            "read_only_steps": list(self.read_only_steps),
            "decision_points": list(self.decision_points),
            "recommended_write_templates": list(self.recommended_write_templates),
            "guardrail_notes": list(self.guardrail_notes),
        }
        if include_prompts:
            payload["astrbot_prompts"] = list(self.astrbot_prompts)
        return payload


OPS_SOPS: dict[str, OpsSop] = {
    "disk_full": OpsSop(
        scenario="disk_full",
        aliases=("磁盘满", "磁盘空间不足", "日志占满", "disk_pressure"),
        summary="磁盘空间异常排查：先确认分区压力，再定位大文件和大日志，最后只生成清理申请。",
        symptoms=("分区使用率超过 80%", "应用写日志失败", "服务报 no space left on device"),
        read_only_steps=(
            {"order": 1, "tool": "get_disk_usage", "purpose": "确认各分区容量、剩余空间和压力分区。"},
            {
                "order": 2,
                "tool": "find_large_files_tool",
                "purpose": "在明确目录内按预算扫描大文件，避免全盘长时间阻塞。",
            },
            {
                "order": 3,
                "tool": "detect_large_logs_tool",
                "purpose": "识别大日志并标注数据库、审计、容器等敏感目录提示。",
            },
            {"order": 4, "tool": "get_file_stat_tool", "purpose": "对候选文件采集大小、时间和可选哈希。"},
        ),
        decision_points=(
            "候选文件是否属于数据库、审计、容器或系统关键路径。",
            "是否存在日志轮转、归档或截断的低风险替代方案。",
            "是否需要先确认备份、复制状态或业务维护窗口。",
        ),
        recommended_write_templates=("request_log_cleanup", "request_delete_file"),
        guardrail_notes=(
            "禁止把自然语言“清理垃圾”直接翻译成 rm -rf 或 Remove-Item -Recurse -Force。",
            "默认使用 archive/quarantine/truncate dry-run 计划，真实执行必须经过 guardrail 和审批。",
        ),
        astrbot_prompts=(
            "只允许通过 MCP 工具调用，不要使用 shell。调用 diagnose_disk_full_tool 排查当前目录磁盘压力，只读检查。",
            "只允许通过 MCP 工具调用，不要使用 shell。对候选日志调用 request_log_cleanup 生成 archive dry_run 计划，不要真实修改文件。",
        ),
    ),
    "port_conflict": OpsSop(
        scenario="port_conflict",
        aliases=("端口冲突", "端口被占用", "port_in_use"),
        summary="端口冲突排查：确认监听端口、进程归属和服务关系，再决定是否改配置或申请停止进程。",
        symptoms=("应用启动失败提示 address already in use", "端口监听进程与预期不一致"),
        read_only_steps=(
            {"order": 1, "tool": "get_listening_ports", "purpose": "查看端口监听样本和进程 PID。"},
            {"order": 2, "tool": "diagnose_port_conflict_tool", "purpose": "按指定端口过滤冲突进程。"},
            {"order": 3, "tool": "list_processes", "purpose": "核对进程名称、资源占用和 PID。"},
            {"order": 4, "tool": "get_service_status_tool", "purpose": "如进程属于服务，优先查询服务状态。"},
        ),
        decision_points=(
            "端口持有者是否为受管服务，而不是孤立进程。",
            "能否通过修改应用端口配置解决，而不是停止进程。",
            "停止进程是否会影响 SSH/WinRM、数据库或安全服务。",
        ),
        recommended_write_templates=("request_stop_process", "request_modify_file", "request_restart_service"),
        guardrail_notes=(
            "禁止按模糊进程名批量 kill。",
            "停止进程 dry-run 必须包含 PID 和期望进程名，真实执行必须审批。",
        ),
        astrbot_prompts=(
            "只允许通过 MCP 工具调用，不要使用 shell。调用 diagnose_port_conflict_tool 检查 8080 端口，只读检查。",
            "只允许通过 MCP 工具调用，不要使用 shell。对确认的 PID 调用 request_stop_process 生成 dry_run 计划，不要停止进程。",
        ),
    ),
    "service_issue": OpsSop(
        scenario="service_issue",
        aliases=("服务异常", "服务挂了", "service_down", "restart_service"),
        summary="服务异常排查：先看服务状态、近期错误日志和资源压力，再生成重启或配置修复申请。",
        symptoms=("服务状态 inactive/failed", "健康检查失败", "近期日志出现 error/fatal/timeout"),
        read_only_steps=(
            {"order": 1, "tool": "get_service_status_tool", "purpose": "查询服务状态和平台返回。"},
            {"order": 2, "tool": "diagnose_service_issue_tool", "purpose": "组合服务状态、资源快照和可选日志片段。"},
            {"order": 3, "tool": "read_log_excerpt_tool", "purpose": "按 error 关键词读取受限日志片段。"},
            {"order": 4, "tool": "get_listening_ports", "purpose": "确认服务端口是否仍在监听。"},
        ),
        decision_points=(
            "服务是否由 systemd/Windows Service 管理。",
            "是否存在配置错误，应先 validate/reload 而不是 restart。",
            "是否处于业务高峰或需要维护窗口。",
        ),
        recommended_write_templates=("request_restart_service", "request_modify_file"),
        guardrail_notes=(
            "重启服务属于 high 风险，dry-run 可生成计划但必须展示 requires_approval。",
            "关键远程访问、安全和数据库服务应额外标注影响范围。",
        ),
        astrbot_prompts=(
            "只允许通过 MCP 工具调用，不要使用 shell。调用 diagnose_service_issue_tool 检查 Spooler 服务，只读检查。",
            "只允许通过 MCP 工具调用，不要使用 shell。调用 request_restart_service 生成重启 Spooler 的 dry_run 计划，不要真实重启。",
        ),
    ),
    "high_cpu": OpsSop(
        scenario="high_cpu",
        aliases=("CPU高", "CPU占用高", "high_cpu", "cpu_100"),
        summary="高 CPU 排查：多点确认资源快照和 Top-K 进程，优先定位服务归属而不是直接 kill。",
        symptoms=("CPU 长时间高于 80%", "负载升高", "业务响应变慢"),
        read_only_steps=(
            {"order": 1, "tool": "diagnose_high_cpu_tool", "purpose": "组合资源快照、Top-K 进程和疑似进程。"},
            {"order": 2, "tool": "list_processes", "purpose": "必要时再次采样，确认是否为持续高占用。"},
            {"order": 3, "tool": "get_service_status_tool", "purpose": "确认疑似进程是否属于受管服务。"},
        ),
        decision_points=(
            "高 CPU 是否持续出现，而不是单次采样尖峰。",
            "进程是否为数据库、杀毒、安全、备份或系统关键进程。",
            "是否需要先采集线程栈、日志和业务证据。",
        ),
        recommended_write_templates=("request_stop_process", "request_restart_service"),
        guardrail_notes=(
            "停止进程不可回滚，优先生成诊断建议和 dry-run。",
            "不允许按进程名通配符批量终止。",
        ),
        astrbot_prompts=(
            "只允许通过 MCP 工具调用，不要使用 shell。调用 diagnose_high_cpu_tool 列出资源占用最高的 8 个进程，只读检查。",
            "只允许通过 MCP 工具调用，不要使用 shell。对确认的单个 PID 调用 request_stop_process 生成 dry_run 计划，不要停止进程。",
        ),
    ),
    "website_down": OpsSop(
        scenario="website_down",
        aliases=("网站打不开", "接口不通", "web_down", "site_down"),
        summary="网站不可用排查：按 DNS、网络、HTTP、端口、服务、日志、资源顺序定位故障面。",
        symptoms=("HTTP 5xx/4xx", "连接超时", "域名解析失败", "本地端口未监听"),
        read_only_steps=(
            {"order": 1, "tool": "resolve_dns_tool", "purpose": "确认域名解析。"},
            {"order": 2, "tool": "check_network_connectivity_tool", "purpose": "确认基础连通性。"},
            {"order": 3, "tool": "check_http_endpoint_tool", "purpose": "获取 HTTP 状态码和响应摘要。"},
            {"order": 4, "tool": "diagnose_website_down_tool", "purpose": "执行标准网站不可用流水线。"},
        ),
        decision_points=(
            "DNS、网络、HTTP、端口和服务哪一层最先失败。",
            "是否存在磁盘/CPU/内存资源瓶颈。",
            "是否需要重启服务或修改防火墙策略。",
        ),
        recommended_write_templates=("request_restart_service", "request_network_policy_change"),
        guardrail_notes=(
            "开放端口或重启服务都必须通过 request_* dry-run 与审批链路。",
            "禁止直接关闭防火墙或清空网络策略。",
        ),
        astrbot_prompts=(
            "只允许通过 MCP 工具调用，不要使用 shell。调用 diagnose_website_down_tool 排查 http://127.0.0.1:8080，只读检查。",
            "只允许通过 MCP 工具调用，不要使用 shell。调用 request_network_policy_change 生成开放 tcp 8080 的 dry_run 计划，不要真实修改防火墙。",
        ),
    ),
    "config_drift": OpsSop(
        scenario="config_drift",
        aliases=("配置漂移", "配置被改", "config_drift"),
        summary="配置漂移排查：读取文件元信息和哈希，结合日志和服务状态判断是否需要生成受控修改计划。",
        symptoms=("配置 hash 与基线不同", "文件最近修改时间异常", "变更后服务异常"),
        read_only_steps=(
            {"order": 1, "tool": "get_file_stat_tool", "purpose": "读取文件大小、mtime、权限和可选 sha256。"},
            {"order": 2, "tool": "read_log_excerpt_tool", "purpose": "读取配置相关错误日志片段。"},
            {"order": 3, "tool": "get_service_status_tool", "purpose": "检查关联服务状态。"},
        ),
        decision_points=(
            "目标路径是否属于系统、认证、数据库或容器敏感路径。",
            "是否有可信基线用于比较。",
            "修复方式是替换文本、追加配置还是回滚备份。",
        ),
        recommended_write_templates=("request_modify_file", "request_restart_service"),
        guardrail_notes=(
            "修改配置必须明确单文件、单操作和 match 内容，默认创建备份。",
            "敏感路径修改需要 guardrail 标注高风险，真实执行必须审批。",
        ),
        astrbot_prompts=(
            "只允许通过 MCP 工具调用，不要使用 shell。调用 get_file_stat_tool 检查指定配置文件并包含 hash。",
            "只允许通过 MCP 工具调用，不要使用 shell。调用 request_modify_file 生成替换配置项的 dry_run 计划，不要真实修改文件。",
        ),
    ),
    "zombie_process": OpsSop(
        scenario="zombie_process",
        aliases=("僵尸进程", "进程堆积", "zombie"),
        summary="僵尸/异常进程排查：先采样进程与父进程线索，确认服务归属，再生成最小范围处理建议。",
        symptoms=("进程数量异常增长", "僵尸进程堆积", "父进程异常退出"),
        read_only_steps=(
            {"order": 1, "tool": "list_processes", "purpose": "获取资源占用和进程样本。"},
            {"order": 2, "tool": "diagnose_high_cpu_tool", "purpose": "辅助定位异常高资源进程。"},
            {"order": 3, "tool": "get_service_status_tool", "purpose": "如果进程属于服务，优先查询服务状态。"},
        ),
        decision_points=(
            "进程是否真的可被停止，还是应重启父服务。",
            "是否属于系统、数据库、安全或远程访问进程。",
            "是否需要先收集日志、core dump 或线程栈证据。",
        ),
        recommended_write_templates=("request_stop_process", "request_restart_service"),
        guardrail_notes=(
            "停止进程必须指定单个 PID 和预期进程名。",
            "若 PID 不存在，dry-run 仍可生成计划，但真实执行应失败并审计。",
        ),
        astrbot_prompts=(
            "只允许通过 MCP 工具调用，不要使用 shell。调用 list_processes 列出当前资源占用最高的 8 个进程，只读检查。",
            "只允许通过 MCP 工具调用，不要使用 shell。调用 request_stop_process 生成停止指定 PID 的 dry_run 计划，不要真实停止进程。",
        ),
    ),
}


def list_ops_sops(include_prompts: bool = False) -> list[dict[str, Any]]:
    return [sop.to_dict(include_prompts=include_prompts) for sop in OPS_SOPS.values()]


def get_ops_sop(scenario: str, include_prompts: bool = True) -> dict[str, Any] | None:
    normalized = _normalize_scenario(scenario)
    for sop in OPS_SOPS.values():
        names = {sop.scenario, *sop.aliases}
        if normalized in {_normalize_scenario(name) for name in names}:
            return sop.to_dict(include_prompts=include_prompts)
    return None


def _normalize_scenario(value: str) -> str:
    return value.strip().lower().replace("-", "_").replace(" ", "_")
