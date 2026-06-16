# 真实最小权限执行代理预开发文档

本文档用于指导 `tmp_MCP` 后续从“固定模板 dry-run + 审批校验”推进到“受限身份下的真实执行”。目标不是开放更多命令，而是把每一次真实运维动作限制在最小权限账户、固定模板、审批范围、审计链和回滚策略之内。

## 当前落地状态

`0.6.0-alpha-predev` 已完成第一段代码落地：

- 新增 `execution/policy.py`，实现 `ExecutionPolicy` 与 `ExecutionValidation`。
- 新增 `execution/agents/`，实现受限执行代理档案 `ExecutionAgentProfile`，当前包含 Linux/麒麟 `linux-kylin-ops-agent-v1` 和 Windows `windows-jea-endpoint-v1`。
- 新增受限执行代理预检契约：`ExecutionAgentRequest`、`ExecutionAgentPreflight`、`ExecutionAgentResult`、`ExecutionAgentAdapter` 和 `ReferenceExecutionAgentAdapter`。
- 所有 `request_*` 写工具在 `dry_run=false` 且审批校验通过后，会先执行 `ExecutionPolicy`，再进入固定模板执行。
- `ExecutionPolicy` 会校验模板是否存在、平台是否支持、目标是否为本地、审批是否通过、身份是否满足、操作范围是否安全、真实执行前置条件是否满足。
- `ExecutionPolicy` 对提权模板新增代理档案和 `adapter_preflight` 校验：`TMP_MCP_ENABLE_PRIVILEGED_EXECUTION=true` 不能单独放开真实执行，还必须存在已部署代理档案，且平台、模板、身份匹配。
- `adapter_preflight` 接收来自 `ExecutionPolicy` 的结构化参数摘要，只记录 `params_keys`、`raw_command_present` 和 `denied_request_keys`，不回显参数原值或任意命令字符串。
- 远程 `reference_only` 计划链已补充结构化远程契约字段：`reference_request`、`reference_preflight`、`connection`、`auth_requirements`、`approval_binding`、`trace_binding`、`execution_contract`、`post_check_plan` 和 `rollback_plan`。
- `ExecutionPolicy` 校验结果会返回到 `data.execution_validation`，并写入 `execution_validation` 审计事件，便于按 `trace_id` 回放。
- 新增 `get_execution_agent_profiles_tool`，用于通过 MCP 只读查询 `ops-agent` / JEA 档案、允许模板、禁止能力和部署样例路径。
- 新增 `scripts/verify_execution_agent_profiles.py`，专项验证缺失档案、`reference_only` 档案、平台错配、结构化代理请求、任意命令字段拒绝、未知模板拒绝、reference 适配器不执行真实动作和 dry-run 不受影响。
- 新增 `packaging/sudoers/tmp-mcp-ops-agent` 和 `packaging/systemd/tmp-mcp-ops.service` 作为 Linux/麒麟部署参考。
- 新增 `docs/deployment/DEPLOY_KYLIN_V11.md`，沉淀 LoongArch + 麒麟 V11 最小权限部署草案。
- 新增真实执行结果的 `post_checks / rollback_hint` 第一版，当前固定模板在执行后会返回命令退出码、文件 hash 变化、备份检查、结果路径或回滚提示等结构化信息。
- 新增 `scripts/verify_execution_post_checks.py`，专项验证临时文件真实固定模板的后置检查、hash 变化和回滚提示。
- 当前未部署 Linux sudoers / Windows JEA 时，服务重启、防火墙、包管理、权限修改、进程停止等需要提权的真实模板默认阻断。
- 当前仍保留临时文件类非提权固定模板的审批后执行能力，用于验证审批闭环和执行策略链路。

尚未完成：

- Linux / 麒麟 `ops-agent` 真实受限账户的实机安装验证。
- Linux / 麒麟真实 `ExecutionAgentAdapter` 子类，负责把已通过预检的固定模板映射到 sudoers allowlist。
- sudoers allowlist 示例文件已提供，仍缺少实机安装脚本和验证记录。
- Windows PowerShell JEA Endpoint 和对应 `ExecutionAgentAdapter` 子类。
- 提权代理实机执行后的深度 post-check 与自动回滚编排，例如服务健康、包版本、实际防火墙规则和业务探测。
- LoongArch / 麒麟 V11 实机验证。

## 开发目标

真实最小权限执行代理要解决四个问题：

- MCP Server 不应长期以 root、Administrator 或高权限用户运行。
- 高风险动作不能由模型拼接任意 shell 命令执行。
- 审批通过只代表“允许执行某个固定模板的某个范围”，不能扩大权限边界。
- 执行前、执行中、执行后都要可审计、可回放、可定位。

第一版目标：

- Linux / 麒麟 V11 优先，设计 `ops-agent` 受限账户与 sudoers allowlist。
- Windows 保留 PowerShell JEA 或受限本地账户方案设计。
- 执行代理只接受结构化模板请求，不接受任意命令字符串。
- 真实执行前强制校验 guardrail、approval、template、identity 和 audit trace。
- 所有真实执行返回 `execution_validation`、`least_privilege`、`post_checks` 和 `rollback_hint`。

### LLM 解析不等于执行授权

自然语言运维可以让 LLM 参与意图解释、SOP 选择、工具规划和结果说明，但执行授权必须由 MCP 后端完成。换句话说，LLM 可以提出“应该调用哪个 MCP 工具、为什么这样排障”，不能直接提交 shell、PowerShell 或远程脚本，也不能把审批、审计、`ExecutionPolicy` 和受限执行代理的判断替掉。

下一阶段远程写操作的路线是：继续从 `remote_execution.mode=reference_only` bundle 收束到可消费的 `ExecutionAgentRequest` 契约，再分别对接 Linux SSH 受限执行代理和 Windows WinRM / JEA 受限执行代理。未部署受限代理、未完成审批绑定、未具备 post-check 和回滚设计前，远程 `dry_run=false` 必须保持显式阻断。

非目标：

- 不实现通用远程命令执行器。
- 不让 LLM 直接传入 shell / PowerShell 脚本。
- 不把审批当作绕过 `critical` 风险的通行证。
- 不在没有目标平台验证前宣称 LoongArch / 麒麟完全兼容。

## 总体架构

推荐链路：

```text
AstrBot / Agent
-> request_* dry-run
-> guardrail_decision
-> approval_request
-> approval_granted
-> request_*(dry_run=false, approval_id=...)
-> ExecutionPolicy 校验
-> ExecutionAgentAdapter
-> Linux sudoers / Windows JEA 固定模板
-> post_checks
-> audit tool_result
-> audit anchor
```

组件拆分：

| 组件 | 建议位置 | 职责 |
| --- | --- | --- |
| `ExecutionPolicy` | `execution/policy.py` | 校验目标平台、当前身份、模板范围、审批范围和风险边界 |
| `ExecutionAgentProfile` | `execution/agents/base.py` | 定义受限执行代理能力档案、允许模板、禁止能力和部署状态 |
| `ExecutionAgentAdapter` | `execution/agents/base.py` | 已定义结构化请求、预检结果和执行结果契约，不暴露任意 shell；当前 reference adapter 只阻断不执行 |
| `LocalLinuxAgent` | `execution/agents/linux.py` | 通过固定命令模板调用受限 sudoers |
| `LocalWindowsAgent` | `execution/agents/windows.py` | 通过 JEA 或受限账户执行固定函数 |
| `ExecutionProxy` | `execution/proxy.py` | 继续负责参数校验、dry-run、模板计划和调用代理 |
| `ActionTemplate` | `execution/action_templates.py` | 声明模板 ID、允许范围、禁止范围、前后置检查和回滚策略 |
| `approval_store` | `approvals/store.py` | 校验审批状态、过期时间和 `scope_hash` |
| `audit_logger` | `audit/logger.py` | 写入 guardrail、approval_validation、execution_validation、tool_result |

## Linux / 麒麟 V11 方向

### 受限账户

建议创建专用低权限账户：

```text
ops-agent
```

账户原则：

- 不允许交互式登录或限制登录 shell。
- 不加入 root 组。
- 不持有业务数据目录的默认写权限。
- 只通过 sudoers allowlist 执行固定命令。
- 命令范围必须与 `ExecutionActionTemplate.template_id` 对齐。

### sudoers allowlist 设计

建议文件：

```text
/etc/sudoers.d/tmp-mcp-ops-agent
```

示例方向：

```text
Cmnd_Alias TMP_MCP_RESTART_NGINX = /usr/bin/systemctl restart nginx, /usr/bin/systemctl status nginx
Cmnd_Alias TMP_MCP_FIREWALL_HTTP = /usr/bin/firewall-cmd --add-port=8080/tcp, /usr/bin/firewall-cmd --remove-port=8080/tcp
Cmnd_Alias TMP_MCP_CHMOD_APP = /usr/bin/chmod 0640 /opt/app/*.conf

ops-agent ALL=(root) NOPASSWD: TMP_MCP_RESTART_NGINX, TMP_MCP_FIREWALL_HTTP, TMP_MCP_CHMOD_APP
```

注意：

- sudoers 不能写成宽泛的 `/usr/bin/systemctl *`。
- 不允许 `/bin/sh`、`/bin/bash`、`python`、`perl`、`awk` 这类可逃逸解释器。
- 文件路径尽量使用明确 allowlist，不使用任意通配。
- 对 `chmod/chown` 必须限制路径和模式。
- 对 `firewall-cmd` 必须限制端口、协议和方向。

### systemd 部署建议

后续可新增：

```text
docs/deployment/DEPLOY_KYLIN_V11.md
packaging/systemd/tmp-mcp-ops.service
packaging/sudoers/tmp-mcp-ops-agent
```

当前这三个文件已经作为 `reference_only` 草案落地。它们的作用是帮助实机部署验证，不代表当前开发机已经安装 `ops-agent` 或放开提权模板。

服务原则：

- MCP Server 以普通用户运行。
- 真实动作通过 `ops-agent` 或受限 sudoers 执行。
- 环境变量显式配置审计目录、审批目录和锚点密钥。
- 日志写入项目可控目录或系统日志，不混入敏感凭据。

### 远程 Linux SSH reference 契约

当前仓库尚未开放真实 SSH 写操作，但远程 `dry_run=true` 计划已经会生成一个可被后续 Linux SSH 执行器复用的 reference bundle。核心字段包括：

- `connection`
  - `target`
  - `port`
  - `username`
  - `auth_ref`
  - `auth_mode=ssh_key_or_agent`
  - `requires_known_host`
  - `strict_host_key_checking`
- `reference_request`
  - `transport=ssh`
  - `identity_source=ssh_remote_username_or_host_mapping`
  - `endpoint_profile=linux-ssh-reference-v1`
  - `host_verification_policy=known_hosts_strict`
  - `health_probe_contract`
  - `post_check_contract`
  - `rollback_contract`
- `approval_binding`
  - 远程真实执行仍要求 `approval_id`
  - `scope_hash` 未来应绑定 `tool_name / operation / target / platform / remote endpoint metadata`
- `trace_binding`
  - 远程真实执行前必须具备 `trace_id / session_id`

当前意义：

- 这些字段并不代表已经能真实 SSH 执行。
- 它们的作用是把“远程写链未来需要什么信息”先结构化下来，避免后续 Linux SSH 执行器再回头改 MCP 工具契约。
- 当前还额外补上了更正式的契约层字段：
  - `approval_binding`
  - `trace_binding`
  - `execution_contract`
  - `identity_source`
  - `endpoint_profile`
  - `host_verification_policy`
  - `health_probe_contract`
  - `post_check_contract`
  - `rollback_contract`
- 当前契约层已经开始从“字段存在”走向“字段可校验”：
  - `build_remote_reference_bundle(...)` 负责统一装配 reference bundle
  - `synchronize_remote_reference_bundle(...)` 负责把真实 `approval_scope_hash / trace_id / session_id` 回写到 bundle
  - `validate_remote_reference_bundle(...)` 负责整包校验
  - `validate_remote_reference_request_contract(...)` 负责单独校验 `reference_request` 中的连接策略、身份来源、host verification 和 service health / post-check / rollback 合同

## Windows 方向

Windows 不建议长期让 MCP Server 以 Administrator 身份运行。推荐两条路线：

### PowerShell JEA

设计 JEA Endpoint，只暴露固定函数：

- `Restart-AllowedService`
- `Set-AllowedFirewallPort`
- `Set-AllowedAcl`

限制原则：

- 不开放 `Invoke-Expression`。
- 不开放任意 `powershell -Command`。
- 不开放文件系统任意写。
- JEA 函数参数做 allowlist 校验。

### 受限本地账户

如果比赛环境难以配置 JEA，可先用受限本地账户方案：

- MCP Server 普通用户运行。
- 需要管理员权限的动作只生成 dry-run 或返回“当前身份不满足最小权限执行要求”。
- 文档明确 Windows 真实执行仍待 JEA 验证。

### 远程 Windows WinRM / JEA reference 契约

Windows 方向与 Linux 对称，当前远程 `dry_run=true` 计划已补充：

- `connection`
  - `target`
  - `port`
  - `username`
  - `auth_ref`
  - `auth_mode=winrm_psremoting`
  - `https_recommended`
  - `endpoint`
- `reference_request`
  - `transport=winrm`
  - `identity_source=winrm_remote_username_or_endpoint_mapping`
  - `endpoint_profile`
  - `host_verification_policy=winrm_listener_and_tls_policy`
  - `health_probe_contract`
  - `post_check_contract`
  - `rollback_contract`

当前意义同样是：

- 先把远程 WinRM / JEA 执行器未来需要的字段收束为结构化契约
- 保持真实执行关闭
- 让审批、审计、trace 和 human_report 先围绕统一契约稳定下来

这一层已经不再只是“reference bundle 里有一些说明字段”，而是开始收束为未来真实远程执行器的请求契约雏形。

## 执行前校验

真实执行前必须全部通过：

| 校验 | 说明 |
| --- | --- |
| `guardrail` | 不能命中 `critical`，高风险必须有审批 |
| `approval` | `approval_id` 存在、`granted`、未过期、`scope_hash` 匹配 |
| `template` | action 必须存在固定模板 |
| `identity` | 当前执行身份符合模板推荐身份或受限代理身份 |
| `scope` | 路径、服务、端口、包名、权限模式在 allowlist 内 |
| `pre_checks` | 执行前状态可读取，例如服务存在、文件存在、端口合法 |
| `audit` | trace_id/session_id 已生成，执行前校验结果已写审计 |
| `agent_preflight` | 代理请求必须是 `ExecutionAgentRequest` 结构化模板请求，不能携带 `command / shell / script / powershell` 等自由命令字段；审计摘要只保留 `params_keys` 和拒绝字段路径 |

建议返回结构：

```json
{
  "execution_validation": {
    "ok": true,
    "template_id": "restart_service.linux.systemd",
    "runtime_identity": "ops-agent",
    "identity_ok": true,
    "checks": {"identity": {"agent_profile": {"adapter_preflight": {"ok": true}}}},
    "scope_ok": true,
    "pre_checks_ok": true,
    "errors": []
  }
}
```

## 执行后校验

真实执行后不能只返回命令退出码，还要返回后置检查：

- 服务重启：查询服务状态、最近日志摘要。
- 进程停止：确认 PID 是否消失，或进程名是否变化。
- 权限修改：读取文件权限并比对期望值。
- 网络策略：确认规则存在或端口策略已变化。
- 包管理：查询包版本或安装状态。
- 文件修改：返回备份路径、hash 变化、回滚方式。

当前第一版已在 `ExecutionProxy` 固定模板返回中落地结构化字段：

- `data.post_checks.ok`：当前后置检查是否整体通过。
- `data.post_checks.checks[]`：每个检查项的 `name / ok / summary` 和关键字段。
- `data.rollback_hint[]`：如果后置检查失败或业务验证不通过，给审批后回滚计划使用的提示。
- `request_modify_file(dry_run=false)` 额外返回 `pre_hash / post_hash / backup_path`，并验证 `file_hash_changed` 与 `backup_created`。

这只是模板层后置检查，不等价于 Linux sudoers / Windows JEA 实机代理已完成。服务健康、包版本、实际防火墙规则和业务探测仍要在目标平台部署后继续增强。

建议返回结构：

```json
{
  "post_checks": {
    "ok": true,
    "checks": [
      {"name": "service_status", "ok": true, "summary": "nginx active"}
    ]
  },
  "rollback_hint": [
    "使用 backup_path 恢复原配置",
    "执行 request_restart_service dry-run 生成回滚重启计划"
  ]
}
```

## 与审批模型的关系

审批只解决“谁允许做这件事”，最小权限执行代理解决“系统实际只能怎么做”。

两者不能互相替代：

- 有审批但模板不匹配：拒绝执行。
- 有审批但当前身份过高或过宽：拒绝或降级为 dry-run。
- 有审批但命中 `critical`：拒绝执行。
- 有审批但后置检查失败：返回失败并提供回滚建议。

## 与审计链的关系

真实执行至少写入这些事件：

- `guardrail_decision`
- `approval_validation`
- `execution_validation`
- `tool_result`
- 可选 `audit_anchor`

审计摘要应包含：

- `trace_id`
- `approval_id`
- `template_id`
- `runtime_identity`
- `scope_hash`
- `pre_checks`
- `post_checks`
- `result_summary`
- `rollback_hint`

## 第一阶段开发任务

建议拆成 5 个小 PR / 小提交：

1. 新增预开发文档和部署草案。
2. 新增 `execution/policy.py`，实现身份、模板和范围校验的纯 Python 骨架。
3. 扩展 `ExecutionProxy`，在 `dry_run=false` 前调用 `ExecutionPolicy`，先只返回 validation，不改变真实执行行为。
4. 新增 Linux / 麒麟 `ops-agent` 与 sudoers 示例文件。
5. 新增受限执行代理档案和 `get_execution_agent_profiles_tool`，让 `ExecutionPolicy` 能区分“配置了提权开关”和“目标主机真的部署了代理”。
6. 新增自动化测试：身份不匹配阻断、模板不存在阻断、scope 超界阻断、缺失代理档案阻断、`reference_only` 档案阻断、dry-run 不受影响。
7. 新增固定模板执行后的 `post_checks / rollback_hint` 和专项验证脚本，先覆盖临时文件真实执行闭环。
8. 新增受限执行代理预检契约和 reference adapter，确保后续真实代理只能接收结构化模板请求，且当前阶段不会执行 sudo/JEA。

## 验收用例

自动化用例：

| 编号 | 场景 | 期望 |
| --- | --- | --- |
| LP-001 | `dry_run=true` | 返回 `least_privilege` 和 `approval_request`，不执行身份校验 |
| LP-002 | `dry_run=false`，审批通过但身份不满足 | 阻断，返回 `execution_validation.identity_ok=false` |
| LP-003 | `dry_run=false`，审批通过但路径超出 allowlist | 阻断，返回 `execution_validation.scope_ok=false` |
| LP-004 | `dry_run=false`，模板不存在 | 阻断，返回 `template_not_found` |
| LP-005 | `dry_run=false`，全部校验通过的临时文件模板 | 执行固定模板并返回 `post_checks.ok=true`、`pre_hash / post_hash` 和 `rollback_hint` |
| LP-006 | 构造 `ExecutionAgentRequest(params={"command": "sudo systemctl restart nginx"})` | 代理预检阻断，返回 `execution_agent_request_not_structured`，且摘要不回显原始命令字符串 |
| LP-007 | 调用 `ReferenceExecutionAgentAdapter.execute()` | 永远阻断，返回 `execution_agent_execute_not_implemented`，不触发真实 sudo/JEA |
| LP-008 | `ExecutionPolicy.validate(params={"service": "nginx"})` 进入提权模板代理预检 | `adapter_preflight.checks.request.params_keys=["service"]`，摘要不出现 `nginx` 原值 |

AstrBot 手工提示词：

```text
只允许通过 MCP 工具调用，不要使用 shell。调用 get_execution_action_templates_tool，查询 restart_service 在 Linux 上的最小权限模板，并说明 recommended_runtime_account、allowed_scopes、denied_scopes 和 rollback_strategy。
```

```text
只允许通过 MCP 工具调用，不要使用 shell。调用 request_restart_service，生成重启 nginx 的 dry_run 计划，不要真实重启。请说明 data.least_privilege、data.approval_request 和后续真实执行需要满足的最小权限条件。
```

```text
只允许通过 MCP 工具调用，不要使用 shell。模拟 dry_run=false 但当前身份不满足 ops-agent/JEA 要求的场景，说明 execution_validation 为什么阻断，不要真实修改系统。
```

## 风险与注意事项

- sudoers 示例必须非常保守，宁可少开放，不可写成通配命令。
- Windows JEA 需要实机验证，文档中要区分“设计完成”和“验证完成”。
- 不要把 Python 测试脚本变成绕过执行代理的真实执行入口。
- 真实执行测试优先使用临时文件和无害服务，不要操作生产服务。
- LoongArch / 麒麟依赖安装差异需要单独记录，不要只按 Windows 开发环境推断。

## 与后续版本的关系

建议版本节奏：

- `0.6.0-alpha-predev`：完成本预开发文档、policy 骨架、代理档案、预检契约、reference adapter 和部署草案。
- `0.6.0-alpha`：完成 Linux / 麒麟本地最小权限校验第一版。
- `0.6.1-alpha`：补 Windows JEA 方案和测试文档。
- `0.7.0-alpha`：接入 B/S 时间线、审批页面和审计查询页面。
