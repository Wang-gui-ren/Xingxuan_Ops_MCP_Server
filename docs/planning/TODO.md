# tmp_MCP 开发待办路线图

本文档用于把赛题要求拆解为 `tmp_MCP` 后续开发任务。当前策略是先把 MCP 运维 Server 做成“安全可控的 OS 感知与执行入口”，再逐步补齐规则配置化、审计防篡改、链路追踪、最小权限执行和国产化平台适配。

## 当前状态

已完成的基础能力：

- MCP Server 骨架已建立，包含 `resources / tools / prompts`。
- 支持本机 Windows / Linux 主机画像采集。
- 支持远程 Linux SSH 与远程 Windows WinRM 的主机画像采集入口。
- 支持磁盘、进程、监听端口、大文件扫描等只读诊断工具。
- 支持常用运维口令映射工具和经典故障流水线排查。
- 支持基础写操作固定模板与 `dry_run` 计划。
- 初步实现安全意图校验器，覆盖危险命令、敏感路径、Prompt Injection、写工具默认风险。
- 已实现配置化规则库，默认加载 `config/guardrails/rules.yaml`，并提供规则自检脚本。
- 已实现 JSONL 审计日志，支持敏感字段脱敏、哈希链和最近事件查询。
- 已实现审计链外部锚点，支持本地 `anchors.jsonl` 和可选 HMAC-SHA256 签名。
- 已实现 `trace_id/session_id` 自动生成，写工具审计事件可按 trace 串联查询。
- 所有 `request_*` 写工具已接入校验与审计。
- 已实现本地 JSONL 审批事件模型，支持审批申请、批准/拒绝、查询、过期时间和 `scope_hash` 校验。
- 已实现审批生命周期增强，支持撤销、续期、过期清理，以及撤销/过期后的真实执行阻断。
- 已实现审批账本哈希链，新写入记录带 `prev_hash / event_hash`，并提供 `verify_approval_chain_tool` 与专项验证脚本。
- 已实现审批策略配置和最小多级审批，默认加载 `config/approvals/policies.yaml`，支持 `partially_granted`、审批人数、TTL、审批人角色/白名单、禁止自批和重复审批人拦截。
- 已实现审批账本外部锚点，支持 `anchor_approval_chain_tool`、`verify_approval_anchor_tool`、本地 `anchors.jsonl` 和可选 HMAC-SHA256 签名。
- 已实现 B/S 审批控制台 bundle，`get_approval_console_bundle_tool` 可返回审批队列、指标、选中审核包、企业身份模式和自包含 HTML 页面物料。
- 已实现企业身份断言签发 token 预开发，`issue_enterprise_approval_token_tool` 先校验企业断言，再签发短期 `approval_token`，最终仍由 `record_operation_approval_tool` 落账。
- 已实现托管式 B/S 审批/配置网关 MVP，可通过本地 HTTP 打开 `/approvals`、`/config-admin` 和 `/gateway-settings`，并提供受网关令牌保护的审批/配置 POST API 与项目内网关选项控制台。
- 已实现高风险写操作 dry-run 自动返回 `data.approval_request`、`data.approval_scope_hash` 和 `data.execute_after_approval`，减少 AstrBot 手工填参导致的审批范围不匹配。
- 已实现 Agent 可读化输出层，关键工具返回 `data.human_report`，便于 AstrBot 按结论、证据、风险、下一步和 trace_id 复述。
- 已实现写操作最小权限模板声明，`request_*` 返回中包含 `data.least_privilege`。
- 已提供 `get_execution_action_templates_tool`，可查询固定模板、推荐受限身份、允许/禁止范围和回滚策略。
- 已实现 `ExecutionPolicy` 真实执行前校验骨架，`dry_run=false` 在进入固定模板执行前会校验模板、平台、目标、审批、身份、范围和前置条件，并写入 `execution_validation` 审计事件。
- 已实现受限执行代理档案，提供 `get_execution_agent_profiles_tool` 查询 Linux/麒麟 `ops-agent` 与 Windows JEA 档案；`reference_only` 档案不能放开真实提权模板。
- 已实现受限执行代理预检契约和 reference adapter，`ExecutionPolicy` 会在提权模板校验明细中返回 `adapter_preflight`，代理请求拒绝任意命令字段，并在审计摘要中只记录结构化参数 key。
- 已补充 Linux/麒麟 sudoers allowlist 示例、systemd 示例和 `docs/deployment/DEPLOY_KYLIN_V11.md` 部署草案。
- 已实现内置运维 SOP 元数据，支持查询磁盘满、端口冲突、服务异常、高 CPU、网站不可用、配置漂移、僵尸进程等场景。
- 能被 AstrBot 通过 MCP stdio 方式调用，并返回结构化结果。
当前主要短板：

- 安全规则已经配置化，但还需要更多行业场景规则和中英文 Prompt Injection 对抗样例。
- 审计日志已有本地哈希链和本地锚点签名，但还没有轮转、集中锚定或第三方透明日志。
- `trace_id/session_id` 已自动生成，审批审核包、审批控制台 bundle 和托管式 B/S 网关 MVP 已能返回后端时间线、页面物料、本地 HTTP 入口和网关选项状态；但还没有生产级登录态、CSRF 和防重放。
- 审批事件模型已有本地账本、生命周期增强、哈希链校验、策略配置、最小多级审批、外部锚点、外部审批身份 token 预开发、B/S 审核包后端契约、B/S 审批控制台 bundle、企业身份断言签发 token、托管式 B/S 网关 MVP 和网关选项控制台，但还没有真实 OIDC/IAM/KMS 接入、密钥轮转、token 撤销和防重放。
- 最小权限模板声明、`ExecutionPolicy` 骨架和受限执行代理档案已落地，但真实受限账户安装、sudoers/JEA 实机验证和远程执行隔离尚未落地。
- Linux / LoongArch / 麒麟 V11 场景的部署验证和平台文档还不完整。
- Prompt Injection 规则还需要更多中英文对抗样例和自动化测试。

## 版本目标

当前完成版本：`0.6.0-alpha-predev` 第二阶段，包含规则配置化、审计哈希链、审计锚点、trace 串联、最小权限模板声明、真实执行前 `ExecutionPolicy` 骨架、受限执行代理档案、代理预检契约、固定模板执行后 `post_checks / rollback_hint`、运维 SOP 元数据、Agent 可读化输出层、本地审批事件模型、外部审批身份 token 预开发、B/S 审批审核包后端契约、B/S 审批控制台 bundle 和企业身份断言签发 token。

下一版本建议：在托管式 B/S 网关 MVP 基础上继续推进真实 OIDC/IAM/KMS 身份接入、登录态、CSRF、防重放、签名密钥轮转、token 撤销和 secret resolver；同时继续按 `docs/architecture/LEAST_PRIVILEGE_EXECUTION_AGENT_PREDEV.md` 落地真实受限账户执行代理和 LoongArch/麒麟部署验证。

当前已补充真实最小权限执行代理预开发文档：`docs/architecture/LEAST_PRIVILEGE_EXECUTION_AGENT_PREDEV.md`，并已落地 `ExecutionPolicy` 第一版、受限执行代理档案、代理预检契约、sudoers/systemd 示例、麒麟部署草案，以及固定模板真实执行后的 `post_checks / rollback_hint` 第一版。后续编码应继续按该文档推进 Linux/麒麟 `ops-agent` 实机安装验证、Windows JEA、深度后置校验和部署验证。

## P0：规则配置化

目标：把 `guardrails/patterns.py` 中的危险命令、Prompt Injection、敏感路径规则迁移到 `config/guardrails/rules.yaml`，让规则库可展示、可维护、可测试。

状态：已完成第一版。

已完成：

- 新增 `config/guardrails/rules.yaml`。
- 新增 `config/guardrails/README.md`。
- 新增 `guardrails/rule_schema.py`，定义规则字段和测试样例字段。
- 新增 `guardrails/rule_loader.py`，负责读取 YAML、编译正则、过滤 enabled 规则。
- 改造 `guardrails/risk_engine.py`，优先使用 YAML 规则，失败时回退到 `patterns.py`。
- 为每条规则补齐 `id / category / risk_level / pattern / enabled / version / source / recommendation / test_cases`。
- 新增 `scripts/verify_guardrail_rules.py`，自动运行规则自带测试样例。

验收标准：

- `rules.yaml` 能成功加载并编译所有 enabled 规则。
- 每条规则的 `test_cases` 都能自动验证。
- 禁用某条规则后，其命中结果会变化，证明规则不是写死在代码里。
- 错误规则不会拖垮 MCP Server，能明确报错或回退。
- `validate_operation_intent_tool` 返回的 finding 能展示规则来源、版本和建议。

## P0：审计日志防篡改

目标：在 `audit/logger.py` 中增加 `prev_hash` 和 `event_hash`，让 JSONL 审计日志形成可验证哈希链。

状态：已完成本地哈希链和外部锚点第一版。

已完成：

- 在 `AuditEvent` 或落盘 payload 中追加 `prev_hash` 与 `event_hash`。
- 在 `AuditLogger.append()` 中读取上一条事件 hash，计算当前事件 hash。
- 使用稳定 JSON 序列化：`sort_keys=True`、固定 separators、先脱敏再哈希。
- 新增 `audit/verifier.py`，支持校验单个 JSONL 审计文件。
- 新增 `scripts/verify_audit_chain.py`，用于本地回归和比赛演示。
- 新增 `verify_audit_chain_tool`，通过 MCP 查询审计链是否完整。
- 新增 `audit/anchor.py`，支持对审计文件创建外部锚点。
- 新增 `anchor_audit_chain_tool` 和 `verify_audit_anchor_tool`。
- 新增 `scripts/verify_audit_anchor.py`，验证锚点创建、签名校验和锚定后变更检测。
- 支持 `TMP_MCP_AUDIT_ANCHOR_SECRET` 配置 HMAC-SHA256 签名。

验收标准：

- 连续写入多条事件时，后一条 `prev_hash` 等于前一条 `event_hash`。
- 原始审计文件校验通过。
- 修改任意中间行后，校验失败并定位行号。
- 删除任意中间行后，校验失败并定位断链位置。
- 敏感字段仍然脱敏，且哈希基于脱敏后的落盘内容。
- 创建锚点后，审计文件追加、替换或整体重算都会与锚点不一致。
- 配置 HMAC secret 后，错误密钥会导致签名校验失败。

## P0：trace_id 自动生成与链路串联

目标：在工具入口自动生成并透传 `trace_id`，让一次对话中的 `guardrail_decision -> tool_result -> audit_query` 能串成一条时间线。

状态：已完成第一版。

已完成：

- 新增 `tracing.py`，提供 `ensure_trace_id()`、`ensure_session_id()`、`build_trace_context()`。
- 在所有写工具 wrapper 中统一调用 trace 构建逻辑。
- 不传 `trace_id` 时自动生成 32 位十六进制 ID。
- 调用方传入 `trace_id` 时保持透传。
- 审计事件、工具返回、`guardrail_decision` 使用同一个 `trace_id`。
- `get_audit_events_tool` 支持按 `trace_id` 查询完整链路。
- 文档补充 AstrBot 两步测试口令：先执行 dry-run，再按 trace 查询审计。

验收标准：

- 不传 `trace_id` 调用任意写工具，返回结果中存在 `trace_id`。
- `guardrail_decision` 和 `tool_result` 审计事件拥有相同 `trace_id`。
- 传入外部 `trace_id` 时不被覆盖。
- `get_audit_events_tool(trace_id=...)` 能查回同一次调用的所有事件。

## P1：最小权限执行代理

目标：避免 MCP Server 直接以高权限执行危险命令，真实动作必须被约束在受限账户和固定模板中。

状态：已完成第一版“模板声明 + 返回元数据 + 查询工具 + ExecutionPolicy 真实执行前校验骨架 + 受限执行代理档案”，真实受限账户执行仍待实现。

已完成：

- 新增 `execution/action_templates.py`，将写操作抽象为固定动作模板。
- 已覆盖 `modify_file / delete_file / restart_service / stop_process / change_permissions / manage_package / network_policy_change`。
- 每个模板声明推荐 Linux 受限账户、Windows 受限身份/JEA 思路、是否需要提权、允许范围、禁止范围、前置检查、后置检查和回滚策略。
- `ExecutionProxy` 的计划返回中增加 `data.least_privilege`，让每次 dry-run 都能看到最小权限上下文。
- 新增 `get_execution_action_templates_tool`，支持按 action 和 platform 查询模板。
- 新增 `execution/policy.py`，实现真实执行前的固定模板、平台、目标、审批、身份、范围和前置条件校验。
- 所有 `request_*` 写工具已在 `dry_run=false` 路径接入 `ExecutionPolicy`。
- 新增 `execution_validation` 审计事件，真实执行前策略结果可按 `trace_id` 回放。
- 未部署受限 `ops-agent`、sudoers allowlist 或 Windows JEA 时，需要提权的真实模板默认阻断。
- 新增 `execution/agents/` 受限执行代理档案，内置 Linux/麒麟 `linux-kylin-ops-agent-v1` 和 Windows `windows-jea-endpoint-v1`。
- 新增 `get_execution_agent_profiles_tool`，用于展示代理档案、允许模板、禁止能力和部署样例路径。
- 新增 `ExecutionAgentRequest / ExecutionAgentPreflight / ExecutionAgentResult / ExecutionAgentAdapter / ReferenceExecutionAgentAdapter`，作为真实 sudoers/JEA 适配器前的结构化预检契约。
- 新增 `scripts/verify_execution_agent_profiles.py`，验证缺失档案、`reference_only` 档案、平台错配、任意命令字段拒绝、未知模板拒绝、reference adapter 永不执行、`ExecutionPolicy -> adapter_preflight` 参数 key 审计摘要和 dry-run 不受影响。
- 新增 `packaging/sudoers/tmp-mcp-ops-agent`、`packaging/systemd/tmp-mcp-ops.service` 和 `docs/deployment/DEPLOY_KYLIN_V11.md`。
- 新增真实执行结果的 `post_checks / rollback_hint` 字段，当前覆盖固定模板执行分支；临时文件模板会记录 `pre_hash / post_hash`、备份检查和回滚提示。
- 新增 `scripts/verify_execution_post_checks.py`，专项验证临时文件真实固定模板的后置检查、hash 变化和回滚提示。
- 自动化验收已覆盖最小权限模板字段完整性和执行代理档案边界。

继续待办：

- 在 Linux / 麒麟实机安装 `ops-agent` 受限账户并校验最小 sudoers 规则。
- 将 Windows 高风险动作切换到 PowerShell JEA Endpoint 或受限本地账户。
- 将 `reference_only` 代理档案升级为已部署档案前，补齐安装脚本、实机验证记录和失败回滚流程。
- 新增 Linux/麒麟真实 `ExecutionAgentAdapter` 子类，只把通过预检的固定模板映射到 sudoers allowlist，不接受自由命令。
- 增强执行前身份校验：将当前档案式校验升级为真实受限账户/JEA 身份匹配。
- 将当前模板层 `post_checks` 升级为实机层深度后置校验，例如服务健康、包版本、实际防火墙规则和自动回滚编排。
- 审批事件模型生命周期增强、审批账本哈希链、最小多级审批、审批账本外部锚点、外部审批身份 token 预开发、B/S 审批控制台 bundle、企业身份断言签发 token、身份可信配置管理第一版、托管式 B/S 网关 MVP 和网关选项控制台已完成，后续增强真实 IAM/OIDC/KMS、secret store resolver、key rotation、撤销和防重放。

验收标准：

- 默认不提供自由命令执行工具。
- 高危动作必须满足模板匹配、安全校验、审批通过和审计落盘。
- 非必要动作不使用 root。
- 无审批时不能修改关键配置文件。

## P1：审批事件模型

目标：把 `approval_id` 从字符串占位升级为可验证、可过期、可审计、可范围绑定的审批记录。

状态：已完成本地 JSONL 审批账本第一版、PR-A 生命周期增强、PR-B 审批账本哈希链、PR-C 策略配置/最小多级审批、审批账本外部锚点、PR-D 外部审批身份 token 预开发、B/S 审批审核包后端契约、B/S 审批控制台 bundle、企业身份断言签发 token、PR-E 身份可信配置管理第一版、托管式 B/S 网关 MVP 和网关选项控制台，后续继续增强真实企业身份集成、密钥轮转、撤销和防重放。

已完成：

- 新增 `approvals/store.py`，提供 `ApprovalStore`、`ApprovalRecord`、`ApprovalValidation`。
- 新增 `request_operation_approval_tool`，创建审批申请并写入 `approval_requested` 审计事件。
- 新增 `record_operation_approval_tool`，记录 `grant/reject` 并写入 `approval_granted` 或 `approval_rejected` 审计事件。
- 新增 `renew_operation_approval_tool`，支持对 `granted` 且未过期审批续期，并记录 `approval_renewed`。
- 新增 `revoke_operation_approval_tool`，支持撤销尚未终止的审批，并记录 `approval_revoked`。
- 新增 `cleanup_expired_operation_approvals_tool`，支持扫描或标记过期审批，并记录 `approval_cleanup` / `approval_expired`。
- 新增 `get_operation_approval_tool`、`get_approval_review_packet_tool`、`get_approval_console_bundle_tool` 和 `list_operation_approvals_tool`，支持审批状态查询、B/S 审核包查询、B/S 控制台 bundle 查询和最近审批列表。
- 新增 `issue_enterprise_approval_token_tool`，用于受信企业身份断言换取短期 `approval_token`；该工具只签发 token，不直接写审批账本。
- 新增 `web/approval_console.py`，生成 `approval-console-bundle-v1`，包含审批队列、指标、选中审核包、企业身份状态、MCP 工具契约和自包含 HTML。
- 新增 `config/approval_identity.py` 和 `config/approval_identity.json`，集中管理审批身份强制开关、scope 绑定、企业签发、issuer/role、TTL 和 secret/ref 状态。
- 新增 `tool_groups/config_tools.py`，提供 `get_approval_identity_config_tool`、`validate_approval_identity_config_tool`、`update_approval_identity_config_tool`、`rotate_approval_identity_secret_tool` 和 `get_config_admin_console_bundle_tool`。
- 新增 `web/config_admin_console.py`，生成 `config-admin-console-bundle-v1`，包含脱敏配置、审计事件、指标、MCP 工具契约和自包含 HTML。
- 新增 `web/gateway.py`、`web_gateway.py`、`web/gateway_settings.py` 和 `config/web_gateway.py`，托管 `/approvals`、`/config-admin`、`/gateway-settings`、只读 JSON API、网关选项 API 和受令牌保护的审批/配置 POST API。
- 写工具在 `dry_run=false` 且传入 `approval_id` 时，会校验审批存在、状态为 `granted`、未过期、tool / operation / target / scope_hash 匹配。
- 高风险写工具 dry-run 会返回可直接传给 `request_operation_approval_tool` 的 `data.approval_request`。
- `data.human_report` 已能解释审批状态和 `approval_validation`。
- `verify_mcp_operations.py` 已覆盖可复制审批参数包、审批申请、审批通过、临时文件固定模板执行、审批查询和伪造审批阻断。
- `verify_approval_lifecycle.py` 已覆盖审批申请、通过、拒绝、续期、撤销、过期清理和稳定错误字符串。
- `verify_approval_chain.py` 已覆盖审批账本哈希链原始通过、篡改失败、删行断链失败和旧无链字段失败。
- `verify_approval_policy.py` 已覆盖策略加载、TTL 压缩、双人审批、`partially_granted` 阻断、重复审批人、自批拦截、`max_renewals` 和账本哈希链。
- `verify_approval_anchor.py` 已覆盖审批账本外部锚点、HMAC 签名、错误密钥失败和锚定后追加记录失败。
- `verify_approval_identity.py` 已覆盖外部审批身份 token、缺失 token 拒绝、错误审批人、错误 scope、篡改 token 和身份摘要落账。
- `verify_approval_review_packet.py` 已覆盖 B/S 审批审核包、账本历史、trace 审计事件、合并时间线和 human_report。
- `verify_approval_console.py` 已覆盖 B/S 审批控制台 bundle、企业断言拒绝、企业断言签发 `approval_token`、token 落账、身份摘要、审计事件和审批账本哈希链。
- `verify_approval_identity_config.py` 已覆盖身份可信配置读取、脱敏查询、dry-run 校验、管理员身份断言、配置写入、密钥轮转、配置管理 bundle 和审计事件。
- `verify_web_gateway.py` 已覆盖本地 HTTP 网关启动、页面托管、JSON API、secret 脱敏、POST 令牌门禁、网关选项校验、热更新和业务写 API 开关。
- `verify_mcp_operations.py` 已覆盖 `approval_policy`、`approval_anchor`、`approval_identity`、`approval_identity_config`、`approval_review_packet` 和 `execution_agent_profiles` 全链路用例，并在审批通过但提权模板阻断的链路中断言 `adapter_preflight` 只记录参数 key；当前全量验收目标为 60 / 60 PASS。

继续待办：

- 将托管式 B/S 网关 MVP 升级为生产级网关，补齐真实登录态、CSRF、防重放、会话管理、角色菜单和反向代理/TLS 部署方式。
- 接入真实企业身份系统，例如 OIDC/OAuth2、LDAP/AD、企业微信/飞书/OA 或 mTLS 网关，替换当前 HMAC 企业断言预开发通道。
- 引入 KMS/HSM 或集中密钥管理，把当前 secret ref 从展示状态升级为真实 resolver，补齐签名密钥轮转、token 撤销列表、防重放 nonce/jti 和签发审计。
- 为配置管理 B/S 网关补齐管理员角色映射、变更审批流、配置 reload 通知和 secret resolver。

下一步代码实现方案：

- `docs/architecture/APPROVAL_ENHANCEMENT_IMPLEMENTATION_PLAN.md`
- `docs/architecture/PR_C_APPROVAL_POLICY_DEV_PLAN.md`
- PR-A 生命周期增强已完成。
- PR-B 审批账本哈希链已完成：新写入记录带 `prev_hash / event_hash`，并提供 `verify_approval_chain_tool` 和 `scripts/verify_approval_chain.py`。
- PR-C 策略配置与最小多级审批已完成：接入 `config/approvals/policies.yaml`、`approvals/policy.py`、`partially_granted` 状态、审批人历史和 AstrBot 工具暴露边界说明。
- 审批账本外部锚点/HMAC 已完成：新增 `approvals/anchor.py`、`anchor_approval_chain_tool`、`verify_approval_anchor_tool` 和 `scripts/verify_approval_anchor.py`。
- PR-D B/S 审批审核包、审批控制台 bundle 和企业身份断言签发 token 已完成：新增 `get_approval_review_packet_tool`、`get_approval_console_bundle_tool`、`issue_enterprise_approval_token_tool` 和 `scripts/verify_approval_console.py`。
- PR-E 身份可信配置管理第一版已完成：新增 `config/approval_identity.py`、`tool_groups/config_tools.py`、`web/config_admin_console.py`、`config/approval_identity.json` 和 `scripts/verify_approval_identity_config.py`。
- 托管式 B/S 审批/配置网关 MVP 已完成：新增 `web/gateway.py`、`web_gateway.py`、`web/gateway_settings.py`、`config/web_gateway.py` 和 `scripts/verify_web_gateway.py`，页面可打开，网关选项可通过 `/gateway-settings` 控制，POST 写接口受 `TMP_MCP_GATEWAY_ADMIN_TOKEN` 保护。
- 建议下一步推进真实企业身份/OIDC/KMS 接入、登录态/CSRF、防重放、secret resolver、密钥轮转/撤销和真实受限账户执行代理。

验收标准：

- 伪造 `approval_id` 不能进入真实执行。
- 已拒绝、已撤销或已过期审批不能进入真实执行。
- 审批只能用于匹配 `scope_hash` 的操作。
- `critical` 风险不能被审批放行。

## P1：典型运维场景 SOP

目标：把比赛业务场景沉淀为可演示的工具组合和提示词，使评委能看到“对话式安全运维”的闭环。

状态：已完成第一版 SOP 元数据和 MCP 查询工具，后续可继续让流水线自动引用 SOP。

已完成：

- 新增 `ops_sops.py`，沉淀常见故障场景的只读步骤、决策点、推荐写模板、护栏说明和 AstrBot 提示词。
- 磁盘满诊断 SOP：磁盘占用 -> 大文件 -> 日志识别 -> 风险评估 -> 清理申请。
- 端口冲突 SOP：监听端口 -> 进程归属 -> 服务状态 -> 处理建议。
- 服务异常 SOP：服务状态 -> 最近日志 -> 资源占用 -> 重启申请。
- 高 CPU SOP：资源快照 -> Top-K 进程 -> 服务归属 -> 停止/重启申请。
- 网站不可用 SOP：DNS -> 网络 -> HTTP -> 端口 -> 服务/日志 -> 网络策略或重启申请。
- 僵尸进程 SOP：进程列表 -> 父进程线索 -> 风险说明 -> 人工确认。
- 配置漂移 SOP：文件 stat -> hash -> 最近修改时间 -> 差异摘要。
- 新增 `list_ops_sops_tool` 和 `get_ops_sop_tool`，可在 AstrBot 中先查询 SOP 再执行只读排查。

继续待办：

- 让 `run_troubleshooting_pipeline_tool` 返回对应 SOP 引用 ID。
- 为每条 SOP 增加更多行业样例，例如数据库连接异常、备份失败、容器服务异常。
- 将 SOP 与规则库联动，例如敏感路径命中时自动推荐只读替代工具。

验收标准：

- 每个 SOP 至少包含一个只读感知阶段和一个安全决策阶段。
- Prompt 明确要求 AI 不得跳过安全校验。
- 演示时能输出事实、风险、建议、是否需要审批。

## P2：LoongArch + 麒麟 V11 适配

目标：让项目具备赛题要求的目标平台说明和基础兼容能力。

待办：

- 完善 `docs/deployment/DEPLOY_KYLIN_V11.md` 的实机验证记录。
- 记录 LoongArch Python 环境准备方式。
- 记录 `psutil`、`mcp` 等依赖安装注意事项。
- 标注 Linux 命令兼容性：`ss`、`lsof`、`journalctl`、`systemctl`。
- 使用 `check_platform_compatibility_tool` 生成平台自检报告。

验收标准：

- 文档能指导在麒麟高级服务器版 V11 上部署。
- 平台自检能输出缺失命令、权限不足、依赖缺失等信息。
- 不把 Windows 特有能力写死为主路径。

## 最近开发顺序建议

建议下一轮编码按这个顺序推进：

1. 在托管式 B/S 审批/配置网关 MVP 上接入真实企业身份系统，让 `approver/admin_approver` 来自真实登录态、外部审批服务、OIDC/IAM 或 KMS 签名通道；同步补齐 CSRF、防重放、token 撤销、secret resolver 和密钥轮转。
2. 然后在 Linux/麒麟实机安装 `ops-agent` 受限账户和 sudoers allowlist，并把 Linux `ExecutionAgentAdapter` 从 reference 阻断升级为已部署态固定模板执行。
3. 再补 Windows PowerShell JEA 或受限本地账户方案，并提供同等的代理档案和验收脚本。
4. 接着让 SOP 与 `run_troubleshooting_pipeline_tool` 联动，使流水线返回 `sop_id`、决策点和推荐 `request_*` dry-run 模板。
5. 为审计与审批锚点增加轮转、集中查询或第三方透明日志上传。
6. 最后补 LoongArch + 麒麟 V11 实机验证记录和平台自检样例，确保比赛目标环境可以复现。

## 不建议立刻做的事情

- 不开放任意 shell 执行。
- 不直接实现真实删除文件。
- 不直接实现真实修改系统关键配置。
- 不把 root 权限作为默认运行方式。
- 不在审批事件和最小权限代理稳定前开放真实高危执行。

## 比赛展示重点

推荐展示主线：

1. 管理员提出自然语言请求：“帮我清理系统垃圾”。
2. Agent 先调用 MCP 感知磁盘、大文件、日志和服务状态。
3. Agent 识别待处理文件是否属于敏感路径或关键服务。
4. 安全意图校验器给出风险等级和是否需要审批。
5. 审计日志记录完整链路，并通过哈希链证明未被篡改。
6. 审批账本记录 request/grant/renew/revoke，并通过 `verify_approval_chain_tool` 证明账本未被局部篡改。
7. 通过 `trace_id` 查询同一次对话的 guardrail decision 和 tool result。
8. 只有审批通过后，最小权限执行代理才允许执行固定模板动作。

这条主线比“能执行很多命令”更贴合赛题核心，因为赛题关注点是可控、安全、可追溯的智能运维。
