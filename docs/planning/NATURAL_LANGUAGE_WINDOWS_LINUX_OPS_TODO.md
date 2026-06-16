# 自然语言参与 Windows / Linux 运维 TODO

本文档用于锁定 `tmp_MCP` 下一阶段的开发路线：先把 `request_create_directory` 这条 bug 修复链完整验收，再把“自然语言参与 Windows / Linux 运维”从零散能力整理成一条可逐步落地的混合入口路线。

这里的“混合口径”指的是：

- 高频、固定、参数结构清晰的意图，通过 deterministic bridge 直接落到 MCP 工具。
- 复杂排障、分析、SOP 选择和多步工具规划，继续由 `LLM + AstrBot + 璇玑 + MCP` 协同完成。
- 所有真实动作最终仍统一回到 MCP 的 guardrail、审批、审计和执行策略边界内。

这不是实现说明，也不是比赛报告，而是后续逐项编码、测试和联调的执行清单。

## 下一阶段混合路线总览

下一阶段采用“LLM 解析 + MCP 硬约束”的混合路线，而不是把自然语言运维全部做成规则路由，也不是把执行授权交给模型判断：

| 路线 | 适用请求 | 处理方式 | 当前边界 |
| --- | --- | --- | --- |
| 固定意图 deterministic bridge | 创建目录、重启单个服务、开放/阻断单个端口、归档/隔离单个日志、远程主机画像 | AstrBot bridge 在事件前置阶段解析，直接映射到固定 MCP 工具，默认 `dry_run=true`，命中后 `stop_event()` | 只处理参数结构清楚的窄场景，不做通用自然语言路由器 |
| 复杂意图 LLM + MCP | 故障分析、CPU/磁盘/服务异常定位、SOP 选择、多步变更计划 | LLM 负责解释意图、选择工具、组织步骤；璇玑负责语义与工具链护栏；MCP 负责结构化工具、审批、审计和执行边界 | LLM 不能生成任意 shell 直接执行，也不能替代审批授权 |
| 远程意图 reference-only | 远程 Linux / Windows 主机画像、远程服务重启计划、远程网络策略计划 | 远程只读画像可直接进入 `get_host_profile_tool`；远程写请求只生成 `remote_execution.mode=reference_only` 的执行计划和审批/trace 契约 | 远程真实写操作继续关闭，必须等 SSH / WinRM-JEA 受限执行代理落地后再开放 |

当前状态可以概括为：

| 维度 | 已完成 | 下一步 | 明确不能做 |
| --- | --- | --- | --- |
| `request_create_directory` | MCP 工具链、审批链、后置检查和专项脚本已成型 | 收口 AstrBot 手工重载验收与现场日志口径 | 不能把目录创建扩成任意文件系统 shell |
| 本机自然语言运维 | bridge 已覆盖 4 类固定意图，并验证复杂请求不被误拦截 | 补齐用户文档、开发规范和更多稳定话术样例 | 不能让 bridge 变成通用自然语言命令执行器 |
| 复杂运维分析 | 保留 `AstrBot + 璇玑 + LLM + MCP` 主链 | 明确提示词和验收口径：模型负责规划，MCP 负责执行约束 | 不能让 LLM 绕过 MCP 工具、审批和审计 |
| 远程运维 | 远程只读画像已打通，远程写操作已有 `reference_only` 契约 | 推进可消费的 `ExecutionAgentRequest` 契约，再对接 SSH / WinRM-JEA 代理 | 不能在受限代理未部署前开放远程真实写操作 |

下一步优先级固定为：

1. 收口 `request_create_directory` 的 AstrBot 手工验收。
2. 完善 Windows / Linux 本机固定意图 bridge 的文档、话术和验收口径。
3. 为复杂运维请求补“继续走 LLM + MCP”的提示词和测试边界。
4. 把远程 `reference_only` bundle 推进为可被 Linux SSH / Windows WinRM-JEA 受限执行代理消费的请求契约。

## 一、当前状态

### 1. `request_create_directory` 修复链已基本成型

当前 `request_create_directory` 已经接入以下位置：

- `src/mcp_ops_server/tool_groups/execution_tools.py`
- `src/mcp_ops_server/execution/proxy.py`
- `src/mcp_ops_server/execution/policy.py`
- `src/mcp_ops_server/guardrails/rules.py`
- `src/mcp_ops_server/guardrails/risk_engine.py`
- `scripts/verify_mcp_operations.py`
- `scripts/verify_create_directory_flow.py`

当前能力边界：

- `request_create_directory` 默认 `dry_run=true`。
- 目录创建请求会进入现有 `guardrail_decision -> approval_validation -> execution_validation -> tool_result` 审计链。
- 真实执行仍受 `ExecutionPolicy`、审批范围、固定模板和后置检查约束。
- 针对“新建空文件夹 / 创建目录”的中文短语，已经存在一个可扩展的 AstrBot bridge 模板：
  - `integrations/astrbot_filesystem_command/main.py`
  - `integrations/astrbot_filesystem_command/intent_parser.py`
  - `scripts/install_astrbot_filesystem_plugin.py`
- 该 bridge 命中后会直接调用 MCP 工具，并 `stop_event()` 阻止事件继续进入普通 LLM 流程。

### 2. 已存在的 deterministic bridge 基础

目前仓库里已经有两类不依赖普通 LLM 规划的前置桥接模式：

- `/approvals` 命令桥接
  - 通过 `integrations/astrbot_approvals_command/`
  - 直接调用审批控制台相关 MCP 工具
- 文件系统 / 运维窄桥接
  - 通过 `integrations/astrbot_filesystem_command/`
  - 当前已覆盖创建目录，并已扩展出统一 deterministic ops bridge 的第一版意图解析

这说明 `tmp_MCP` 已经具备“在 AstrBot 事件阶段前置到 MCP 工具”的交付模式，后续自然语言运维入口应继续复用这个模式，而不是修改 AstrBot Core。

但它只适合处理固定、高频、参数语义清晰的意图，不能替代 LLM 在复杂故障分析、多步排障和工具组合规划中的作用。

### 3. 已存在的 Windows / Linux 运维能力

当前已可用的本机 Windows / Linux 运维能力包括：

- 只读感知与诊断
  - 主机画像、磁盘、进程、端口、服务、网络连接、日志片段、平台兼容性检查
  - 故障流水线与 SOP 查询
- 本机写工具
  - `request_create_directory`
  - `request_modify_file`
  - `request_delete_file`
  - `request_restart_service`
  - `request_stop_process`
  - `request_change_permissions`
  - `request_manage_package`
  - `request_network_policy_change`
  - `request_log_cleanup`
- 最小权限与审批能力
  - `ExecutionPolicy`
  - `ExecutionActionTemplate`
  - `linux-kylin-ops-agent-v1`
  - `windows-jea-endpoint-v1`
  - 审批账本、`scope_hash`、审批审核包、审批控制台 bundle

当前远程能力边界：

- 远程 Linux SSH 与远程 Windows WinRM 主机画像采集入口已存在。
- 远程写操作尚未支持；所有写工具目前仍会在 `ExecutionProxy._reject_remote()` 中返回 `remote_execution_not_supported`。

### 4. 已存在的 LLM 参与基础

当前仓库并不是“只允许 bridge，不允许模型参与”。现有架构已经明确保留了 LLM 的职责：

- AstrBot 作为对话与 Agent 编排入口，负责组织上下文和调用 MCP。
- 璇玑在输入、工具输入、输出等阶段负责语义护栏。
- 只读诊断工具、SOP 工具和流水线工具本身就是为“自然语言 -> 分析 -> 调 MCP”设计的。

这意味着下一步目标不应该是“让所有自然语言都绕开 LLM”，而应该是建立一条混合路线：

- 高频固定意图：deterministic bridge
- 复杂排障与分析：`LLM + MCP`
- 所有真实动作：统一进入 MCP 审批、审计与执行策略边界

## 二、第一阶段目标：收尾 `request_create_directory`

这一阶段的目标不是再设计新能力，而是把已有修复链真正验收到“可以稳定交付使用”的程度。

### 需要完成的事项

- 完成 `request_create_directory` dry-run 用例验收
  - 普通路径返回创建计划
  - 返回 `approval_request`、`approval_scope_hash`、`execute_after_approval`
  - 返回 `least_privilege`、`trace_id`、`human_report`
- 完成审批链验收
  - `request_create_directory(dry_run=true)`
  - `request_operation_approval_tool`
  - `record_operation_approval_tool`
  - `request_create_directory(dry_run=false, approval_id=...)`
- 完成真实执行后置检查验收
  - `data.directory_created=true`
  - `data.target_exists=true`
  - `data.post_checks.ok=true`
  - `data.rollback_hint` 存在且可解释
- 保持专项脚本可用
  - `scripts/verify_create_directory_flow.py`
- 补齐 AstrBot 手工验证说明
  - 安装 `install_astrbot_filesystem_plugin.py`
  - 重载插件
  - 发送固定中文短语
  - 预期不进入 LLM，而是直接返回 MCP 结构化结果

### 成功标准

- 普通中文自然语言“新建空文件夹”不进入 LLM。
- 能直接调用 `request_create_directory(dry_run=true)`。
- 真实执行路径仍受审批和执行策略约束。
- 对已存在目录、目标是文件、敏感路径、远程目标都能稳定阻断。

### 当前进度

- `scripts/verify_create_directory_flow.py` 已补齐并通过。
- `verify_mcp_operations.py` 已覆盖 `request_create_directory` dry-run 用例。
- 剩余重点是 AstrBot 真实重载后的手工联调验收。

## 三、第二阶段目标：Windows + Linux 本机混合运维入口

这一阶段的目标不是把所有自然语言都变成 deterministic 路由，而是把当前“文件系统单点桥接”提升为“Windows + Linux 本机混合运维入口”：

- 高频固定意图走 deterministic bridge。
- 复杂分析、排障和工具规划继续交给 `LLM + MCP`。

### 目标原则

- 不做通用自然语言命令执行器。
- 不把所有自然语言都交给 LLM，也不把所有自然语言都交给规则桥接。
- 高频固定意图命中后，直接走 MCP 工具，并 `stop_event()` 阻止进入 LLM。
- 开放式排障、分析、SOP 选择和多步工具规划，继续交给 `LLM + MCP`。
- bridge 命中的写意图默认全部生成 `dry_run=true` 计划。
- 真实执行仍必须走审批、`ExecutionPolicy` 和审计链。

### 第一批 deterministic bridge 意图

#### 1. 创建目录

- Windows 示例
  - `在 C:\tmp 这个文件夹新建一个空文件夹：名字叫 test1`
- Linux 示例
  - `在 /tmp 这个文件夹新建一个空目录：名字叫 test1`
- MCP 工具
  - `request_create_directory`

#### 2. 重启服务

- Windows 示例
  - `重启 Spooler 服务`
- Linux 示例
  - `重启 nginx 服务`
- MCP 工具
  - `request_restart_service(dry_run=true, platform_hint=windows|linux)`

#### 3. 网络策略计划

- Windows / Linux 示例
  - `开放 tcp 8080 端口`
  - `阻断 3389 端口`
- MCP 工具
  - `request_network_policy_change(dry_run=true, platform_hint=windows|linux)`

#### 4. 日志清理计划

- Windows / Linux 示例
  - `归档 /var/log/nginx/access.log`
  - `隔离 C:\logs\app.log`
- MCP 工具
  - `request_log_cleanup(dry_run=true, mode=archive|quarantine, platform_hint=windows|linux)`

### 仍由 LLM + MCP 负责的自然语言场景

以下场景不应被硬塞进 deterministic bridge，而应继续让 LLM 结合只读工具、SOP 和流水线工具参与：

- `帮我看看 nginx 为什么不可用`
- `分析这台 Windows 服务器 CPU 为什么飙高`
- `判断这次日志清理应该先归档还是先查大文件`
- `根据当前主机状态生成安全的变更计划`

这些请求的共同特点是：需要多步推理、证据整合、SOP 选择或工具组合，它们天然更适合交给 LLM 规划，再由 MCP 提供可验证的结构化工具结果。

### 实现方式

- 在现有 `astrbot_filesystem_command` 基础上演进为统一 bridge 模板。
- 第一版继续保留现有目录名与安装脚本，降低交付扰动；逻辑上把它视为 deterministic ops bridge 子层。
- 如后续桥接范围持续扩大，再考虑迁移为 `integrations/astrbot_ops_command/`。
- 对 deterministic bridge
  - 使用规则解析或显式短语模板
  - 每条意图对应一个固定 MCP 工具
- 对 LLM 路线
  - 保持现有 `AstrBot + 璇玑 + MCP` 主链
  - 明确约束“只允许通过 MCP 工具调用，不允许直接生成 shell 执行”
  - 让 LLM 负责工具选择和计划说明，不负责绕过 MCP 安全边界

### 成功标准

- Windows 与 Linux 的 4 类高频意图都能在本机 deterministic bridge 中命中。
- deterministic bridge 命中后不进入 LLM。
- 复杂排障与分析请求仍能进入 `LLM + MCP` 主链，而不是被 bridge 粗暴拦截。
- 两条入口最终都返回结构化 MCP 结果，带 `trace_id`、`guardrail_decision`、`approval_request` 等关键字段。

### 当前进度

- deterministic bridge 子层第一版已具备以下能力：
  - 目录创建、服务重启、端口计划、日志清理计划 4 类意图解析
  - 离线解析验证
  - 解析后直达 MCP 写工具 dry-run 的工具级专项验收
  - 插件目录安装
  - `data.plugins...` 导入性验证
  - 已安装插件副本与源码同步校验
  - 最小 AstrBot 事件模拟下的 `should_call_llm(False) / set_result() / stop_event()` 运行态验证
  - 隔离真实 AstrBot 实例下的 live bridge 验证
  - 隔离真实 AstrBot 实例下的复杂请求边界验证
- 下一步重点：
  - 现网 AstrBot 实例联调与环境侧排障
  - 收集日志与验收口径

## 四、第三阶段目标：远程 Linux / Windows 写操作执行链

这一阶段明确不是当前 bug 修复的直接范围，而是后续真正让“自然语言参与服务器运维”成立的关键扩展。

### 当前事实

- 远程 Linux / Windows 只读主机画像已支持。
- 所有写工具当前仍明确阻断远程执行。

### 后续必须补齐的能力

#### 1. 远程 Linux 写操作执行链

- 受限 SSH 执行代理
- 固定模板映射到远程命令
- 远程身份与认证管理
- 远程审批范围与 `scope_hash`
- 远程执行后的 post-check 与审计

#### 2. 远程 Windows 写操作执行链

- WinRM / JEA 远程受限执行代理
- PowerShell 固定函数映射
- 远程身份、Endpoint、角色与审批约束
- 防火墙、服务、目录、日志清理等模板的远程版本

#### 3. 远程通用安全要求

- 远程身份鉴别
- 远程审批 token / scope 绑定
- 远程 trace 与审计回收
- 远程失败回滚与应急处置

### 文档中必须明确的边界

- 当前不宣称已支持远程真实写操作。
- 当前只支持远程只读感知。
- 远程写操作必须等受限远程执行代理落地后再开放。

## 五、明确非目标

以下内容不属于当前阶段目标：

- 不开放任意 shell。
- 不做通用自然语言路由器。
- 不允许自然语言桥接绕过审批、审计或 `ExecutionPolicy`。
- 不在未落地 `JEA / ops-agent / SSH` 受限执行代理前开放真实远程写操作。
- 不把“模型不可用时绕开 LLM”误解成“系统不再需要 LLM”；bridge 只处理有限 deterministic 场景，复杂运维仍依赖 `LLM + MCP`。

## 六、验收顺序与里程碑

### 里程碑 A：`request_create_directory` 收尾

- 跑专项验收脚本
- 跑通 dry-run、审批、真实执行、后置检查
- 跑通 AstrBot 中文短语桥接

当前进度：

- `scripts/verify_create_directory_flow.py` 已通过
- `verify_mcp_operations.py` 已覆盖
- 剩余重点是 AstrBot 重载后的手工联调

### 里程碑 B：Windows / Linux 本机混合运维入口

- 扩展 bridge 模板支持 4 类高频 deterministic 意图
- Windows 与 Linux 各补最小手工验证用例
- 同步补一组“复杂自然语言仍走 LLM + MCP”的测试口径
- 文档补充安装、触发短语、边界说明和混合路由规则

当前进度：

- deterministic bridge 第一版已完成解析、安装、导入验证和运行态模拟验证
- 现已补充“解析结果真正落到 MCP 写工具 dry-run 路径”的专项验收证据
- 现已补充 AstrBot 真实联调前的插件同步校验脚本与手工验收文档
- 已完成一次隔离真实 AstrBot 实例下的 live bridge 验证，证明 4 类固定意图会在真实 `/api/chat/send` 入口被 bridge 抢占并返回 MCP `dry_run` 结果
- 已完成一次隔离真实 AstrBot 实例下的复杂请求边界验证，证明 `帮我看看 nginx 为什么不可用`、`分析这台 Windows 服务器 CPU 为什么飙高` 不会被 deterministic bridge 拦截
- 已定位并修复一个关键接线问题：bridge 插件必须通过 `@filter.event_message_type(...)` 注册为消息处理器，不能只定义普通 `on_message_event` 方法
- 已补充现网 AstrBot dashboard 诊断脚本，它既能报告当前实例是否出现 `/api/plugin/reload` 的 SQLite runtime `disk I/O error` 或 `/api/chat/new_session` 500，也能在实例恢复健康时直接完成 fixed intent / complex intent 的现网 live 验证
- 已补充 AstrBot runtime DB 健康脚本，证明 `data_v4.db` 文件本身、`preferences` 查询、`platform_sessions` 插入/删除，以及 AstrBot 自己的 `SQLiteDatabase / SharedPreferences` 独立探针均正常；因此现网异常若再次出现，更可能位于“运行中的 AstrBot 进程状态”，而不是数据库文件损坏
- 当前现网实例已再次通过 live 验证：4 类 fixed intent 会被 deterministic bridge 抢占，复杂请求不会出现 deterministic bridge tool marker
- 下一步重点可以转向里程碑 C 的“远程只读自然语言参与”，或继续补更多本机固定意图口径

### 里程碑 C：远程只读自然语言参与

- 让自然语言可以稳定触发远程 Linux SSH 与远程 Windows WinRM 主机画像
- 不进入真实写操作

当前进度：

- 已新增远程 Linux / Windows 主机画像的 deterministic bridge 话术解析
- 已在 `verify_ops_bridge_patterns.py` 中覆盖远程画像意图解析
- 已在 `verify_ops_bridge_runtime.py` 中覆盖 `get_host_profile_tool` 的事件前置拦截
- 已新增 `verify_remote_profile_bridge_flow.py`，证明远程画像话术会落到 `get_host_profile_tool`，并在当前无远程连通性/无认证条件下返回受控只读失败结果，而不会进入真实写操作
- 已在 `verify_astrbot_isolated_live_ops_bridge.py` 与 `verify_astrbot_live_ops_bridge.py` 中补齐远程 Linux 主机画像的 live 级验证，证明它在真实 `/api/chat/send` 入口会命中 `get_host_profile_tool`，并以受控只读失败方式返回

阶段结论：

- 里程碑 C 已具备可演示状态：远程 Linux / Windows 主机画像的自然语言入口已经在 parser、runtime、tool 和 live 层级打通，且失败模式是受控只读失败，不会进入任何真实写操作。

### 里程碑 D：远程写操作受限执行链

- Linux SSH 受限执行代理
- Windows WinRM / JEA 受限执行代理
- 审批、审计、trace、post-check、回滚全部补齐

当前进度：

- 已把远程写操作从“一律 `remote_execution_not_supported`”推进到第一步 `reference_only` 计划链：
  - 远程 `dry_run=true` 现在可返回结构化远程执行计划
  - 返回中包含 `remote_execution.mode=reference_only`
  - 返回中包含 `remote_execution.reference_request / reference_preflight / connection / auth_requirements / post_check_plan / rollback_plan`
  - 同时保留 `approval_request / execute_after_approval / human_report`
  - 现在还会把 `approval_binding / trace_binding` 与真实 `approval_scope_hash / trace_id / session_id` 同步写回 remote bundle
  - 现在还会给 remote bundle 增加 `bundle_validation.ok / errors`，用于证明当前 reference 契约自校验通过
  - 远程 `dry_run=false` 仍继续显式阻断
- 已新增 `verify_remote_execution_reference_flow.py`，证明远程写操作的 reference-only 计划链已经形成
- 已验证“远程 dry-run -> 审批申请 -> grant -> dry_run=false -> execution_validation 阻断”链路，说明审批通过后远程真实执行仍会被 remote target 边界明确阻断

下一步重点：

- 将 Linux SSH reference bundle 进一步细化为真正可对接远程 `ExecutionAgentRequest` 的字段集合
- 为 Windows WinRM / JEA reference bundle 补充对等字段

当前补充说明：

- 远程 Linux 服务重启的 deterministic bridge 话术、runtime 模拟和 `verify_remote_execution_reference_flow.py` 均已通过。
- 远程 Linux 服务重启的 live 验证已在隔离实例中通过，现网实例也已能返回 `reference_only` 远程执行计划。
- 远程 Windows 服务重启的 deterministic bridge 话术、runtime 模拟和 `verify_remote_execution_reference_flow.py` 也已通过，说明 Linux/Windows 双侧 reference 入口都已形成。
- 远程 Windows 服务重启的 live 验证现已在隔离实例和现网实例中通过，现网实例也已能返回 `remote_execution.mode=reference_only / transport=winrm / reference_request / reference_preflight`。
- 若现网 `verify_astrbot_live_ops_bridge.py` 仍看到旧的 `remote_execution_not_supported` 返回，需要先重启当前运行中的 `tmp_mcp_ops` MCP 进程，让现网实例加载最新的 `ExecutionProxy` 代码，再做 live 验证。

阶段结论补充：

- 远程 Linux 服务重启 reference 入口已经在 parser、runtime、reference-flow、isolated live 和 current live 层级全部打通，可视为里程碑 D 第二步的稳定入口。
- 远程 Windows 服务重启 reference 入口已经在 parser、runtime、reference-flow、isolated live 和 current live 层级全部打通，可视为里程碑 D 第二步的对等稳定入口。

下一步阶段建议：

- 不再继续堆更多 reference 入口，而是开始把 Linux SSH / Windows WinRM 的 `ExecutionAgentRequest` 契约再收束一层，例如明确 remote identity source、endpoint profile、known_hosts / host verification、service health probe contract 等字段。

当前进度补充：

- 上述远程契约字段已经在 `ExecutionAgentRequest` / remote reference bundle 中落地，并通过 `verify_remote_execution_reference_flow.py` 校验。
- 当前 `verify_remote_execution_reference_flow.py` 已不只验证“有 bundle”，还验证：
  - `approval_scope_hash` 会与 `approval_request.params` 保持一致
  - `approval_binding.scope_hash` 与 `reference_request.scope_hash` 会同步到同一摘要
  - `trace_binding.trace_id / session_id` 与 `reference_request.trace_id / session_id` 会同步到真实 MCP trace
  - `bundle_validation.ok` 为 `true`，且 `validate_remote_reference_bundle(...)` 本地校验通过
- 当前还新增了更细一层的 `validate_remote_reference_request_contract(...)`，用于单独校验 `identity_source / endpoint_profile / host_verification_policy / health_probe_contract / post_check_contract / rollback_contract / connection policy` 是否满足当前 remote reference 契约要求
- 这一步的第一刀已经落地：`synchronize_remote_reference_bundle(...)` 已从工具层散落逻辑中抽出，`build_remote_reference_bundle(...)` 也已进入契约层，开始形成独立的 remote contract `build + synchronize + validate` 子层。
- 下一步不再是“新增字段”，而是继续把这层 `build + synchronize + validate` 扩成更完整的 remote contract 装配入口，并向真实远程受限执行代理适配。

阶段结论：

- 里程碑 D 已完成第一步可验证落地：远程真实写操作仍未开放，但远程受限执行链的计划层、审批层和审计层占位已经存在，可作为后续 SSH/WinRM/JEA 真正落地的骨架。

## 七、最近开发顺序建议

建议后续编码顺序固定为：

1. 完成 `request_create_directory` 的 AstrBot 手工验收。
2. 继续把 `astrbot_filesystem_command` 收口为 Windows + Linux 本机混合运维入口中的 deterministic bridge 子层。
3. 先补 Windows 侧的服务重启、端口计划自然语言桥接示例。
4. 再补 Linux 侧的服务重启、日志归档自然语言桥接示例。
5. 为复杂排障场景补“继续走 LLM + MCP 主链”的提示词、测试口径和说明。
6. 单独设计远程写操作执行链，不与本机 deterministic bridge 混做。

## 八、一句话结论

下一步的核心不是让自然语言“无边界地执行运维”，也不是把所有解析都交给 LLM，而是建立一条混合路线：高频固定意图走 deterministic bridge，复杂排障与分析走 `LLM + MCP`，所有真实动作统一回到审批、审计和执行策略边界之内。
