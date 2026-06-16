# 0.4.0-alpha 开发路线图

本文档用于规划 `0.4.0-alpha` 后续开发。`0.3.0-alpha` 已完成规则配置化、审计哈希链、trace 串联，并补齐本地外部锚点和可选 HMAC 签名。`0.4.0-alpha` 的重点转向“最小权限执行代理 + 审批链路 + SOP 联动 + 国产化部署验证”。

## 版本目标

`0.4.0-alpha` 不追求开放更多危险命令，而是把写操作从“固定模板 dry-run”推进到“受限身份下的固定模板执行”。

目标闭环：

```text
自然语言请求
-> 查询 SOP
-> 只读诊断采集
-> 生成 request_* dry-run 计划
-> guardrail 决策
-> 审批事件
-> 最小权限代理执行固定模板
-> 审计链 + 锚点验证
```

## P0：真实最小权限执行代理

目标：让 MCP Server 不直接以管理员/root 执行动作，而是把真实动作委托给受限身份和固定模板。

### Linux / 麒麟方向

预开发文档：

- `LEAST_PRIVILEGE_EXECUTION_AGENT_PREDEV.md`

已完成：

- 新增 `execution/policy.py`，先实现身份、模板、scope 和 pre-check 校验骨架。
- 新增 `execution/agents/` 受限执行代理档案，当前包含 Linux/麒麟 `linux-kylin-ops-agent-v1` 与 Windows `windows-jea-endpoint-v1`。
- 新增 `get_execution_agent_profiles_tool`，可只读查询代理档案、允许模板、禁止能力和部署样例路径。
- 创建 `ops-agent` 受限账户部署说明草案。
- 为 `systemctl restart <allowlist>`、`firewall-cmd --add-port/--remove-port`、`chmod` 等模板编写 sudoers allowlist 示例。
- 在执行前检查当前运行身份、代理档案和模板推荐身份是否匹配。
- 对不满足最小权限身份的真实执行返回 `high` 风险提示或拒绝。
- 为麒麟高级服务器版 V11 编写 systemd service 部署模板。
- 固定模板真实执行后返回 `post_checks / rollback_hint`；临时文件模板已记录 `pre_hash / post_hash`、备份检查和回滚提示。

继续待办：

- 在 LoongArch / 麒麟 V11 实机安装 `ops-agent`，验证 sudoers allowlist，并把 `reference_only` 档案升级为已部署态。
- 为实机提权模板补深度执行后检查和回滚验证，例如服务健康、包版本、实际防火墙规则和业务探测。

验收：

- 无任意 shell 执行入口。
- sudoers 中每条命令都与 `ExecutionActionTemplate.template_id` 对应。
- 未满足身份约束时，`dry_run=false` 不应静默执行。

### Windows 方向

待实现：

- 设计 PowerShell JEA Endpoint 或受限本地账户方案。
- 将服务控制、防火墙规则、ACL 修改限制为固定函数。
- 真实执行前检查是否处于 JEA 会话或受限身份。
- 文档化 Windows Server / Windows 10 测试方式。

验收：

- 不要求 MCP Server 直接以管理员身份长期运行。
- 防火墙、服务、ACL 操作必须来自固定模板。
- `get_execution_action_templates_tool` 能说明 Windows 推荐身份。

## P0：审批事件模型

目标：把现在的 `approval_id` 字符串占位升级为可审计审批事件。

状态：已在 `0.5.0-alpha` 完成本地 JSONL 账本第一版，详见 `V0_5_ALPHA_APPROVAL_ROADMAP.md`。

已完成：

- 新增 `approval_requested`、`approval_granted`、`approval_rejected` 审计事件类型。
- 新增 `request_operation_approval_tool`，根据工具、操作、参数和计划生成审批申请。
- 新增 `record_operation_approval_tool`，记录审批人、审批结论、过期时间和范围。
- 新增 `get_operation_approval_tool` 和 `list_operation_approvals_tool`。
- 写操作执行时校验 `approval_id` 是否存在、未过期、匹配 tool / operation / target / scope_hash。
- 高风险写操作 dry-run 返回可复制的 `approval_request` 参数包和 `execute_after_approval` 模板。

继续待办：

- 增加审批撤销、续期、多级审批和外部审批服务。

验收：

- `approval_id` 不能随便伪造。
- 审批只对匹配 `scope_hash` 的操作生效。
- `critical` 风险仍不能通过审批绕过。

## P1：SOP 与流水线联动

目标：让 SOP 不只是元数据查询，而是驱动排障流水线和修复建议。

已完成第一步：

- `run_troubleshooting_pipeline_tool` 和各类 `diagnose_*` 返回 `sop_id` 和 `sop_summary`。
- 关键工具返回 `data.human_report`，便于 AstrBot 按“结论、证据、风险、下一步、trace_id”解释。

继续待办：

- 每个诊断流水线在 `next_actions` 中引用对应 `request_*` dry-run 模板。
- 增加数据库连接异常、SSH 失败、Docker/容器服务异常、备份失败等 SOP。
- 将 SOP 与 guardrail 规则联动：命中敏感路径时优先推荐只读诊断和人工确认。

验收：

- AstrBot 能先查 SOP，再按 SOP 调用只读工具，再生成 dry-run 计划。
- AstrBot 能优先读取 `data.human_report`，按固定段落输出清晰解释。
- SOP 输出不会诱导模型绕过审批或直接执行 shell。

## P1：审计锚点增强

`0.3.0-alpha` 已补齐本地 `anchors.jsonl` 和可选 HMAC 签名。`0.4.0-alpha` 可继续增强：

- 定时锚定：按天或按事件数自动调用 anchor。
- 外部锚定：把 anchor payload 上传到对象存储、Git 仓库、Rekor 或集中审计服务。
- 锚点查询：按日期、文件和 anchor_id 查询历史锚点。
- 锚点轮转：避免 anchors.jsonl 无限制增长。

验收：

- 审计文件被整体重算后，仍能通过 anchor mismatch 发现。
- 配置 `TMP_MCP_AUDIT_ANCHOR_SECRET` 后，锚点签名校验必须通过。

## P2：LoongArch + 麒麟 V11 部署验证

目标：从 Windows 开发环境走向赛题目标环境。

待实现：

- 新增 `docs/deployment/DEPLOY_KYLIN_V11.md`。
- 记录 LoongArch Python、psutil、mcp、PyYAML 安装方式。
- 运行 `check_platform_compatibility_tool` 并保存样例输出。
- 验证 `systemctl`、`journalctl`、`ss`、`lsof`、`firewall-cmd`、`dnf/yum` 可用性。
- 验证 `verify_mcp_operations.py` 在目标平台的兼容结果。

验收：

- 文档能指导从零部署 MCP Server。
- 平台自检能说明缺失依赖和替代路径。

## 推荐开发顺序

1. 审批事件模型，因为它是安全真实执行的前置条件。
2. Linux/麒麟 `ops-agent` + sudoers allowlist，因为赛题目标平台优先。
3. Windows JEA 方案，保持双系统能力完整。
4. SOP 与流水线联动，增强演示效果。
5. 外部锚定服务集成与部署文档。

## 不建议做

- 不新增任意 shell 工具。
- 不允许模型直接传入完整命令字符串执行。
- 不让 `approval_id` 绕过 `critical` 风险。
- 不把 MCP Server 默认部署成 root/Admin 长驻服务。
- 不在目标平台未验证前宣称 LoongArch/麒麟完全兼容。
