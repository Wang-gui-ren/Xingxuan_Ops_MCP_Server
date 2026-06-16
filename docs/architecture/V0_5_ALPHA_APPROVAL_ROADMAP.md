# 0.5.0-alpha 审批事件模型路线图

本文档记录 `0.5.0-alpha` 的设计目标、当前实现、验收方式和后续增强方向。这个版本的重点不是开放更多系统修改能力，而是把 `approval_id` 从“人工口头确认字符串”升级为“可查询、可过期、可校验范围、可写审计的审批事件”。

## 版本目标

`0.5.0-alpha` 要解决的问题：

- 高风险写操作不能因为随便传入一个 `approval_id` 就进入真实执行。
- 审批申请、审批结论和执行结果必须能通过 `trace_id` 串起来。
- 审批必须绑定具体工具、操作、目标和参数范围，不能被拿去复用到另一类动作。
- 审批结果要能在 AstrBot 中用人能读懂的方式解释。

## 当前实现

代码组件：

- `src/mcp_ops_server/approvals/store.py`：本地 JSONL 审批账本。
- `src/mcp_ops_server/approvals/verifier.py`：审批 JSONL 账本哈希链校验。
- `src/mcp_ops_server/approvals/anchor.py`：审批账本外部锚点和可选 HMAC 签名。
- `src/mcp_ops_server/approvals/external.py`：外部审批身份通道预留和 HMAC 审批决策 token 校验。
- `src/mcp_ops_server/tool_groups/approval_tools.py`：审批相关 MCP Tools。
- `src/mcp_ops_server/tool_groups/execution_tools.py`：写操作执行前校验 `approval_id`。
- `src/mcp_ops_server/presentation.py`：把 `approval_validation` 放入 `data.human_report.details`。

MCP Tools：

- `request_operation_approval_tool`：创建审批申请，只写审批账本，不执行运维动作。
- `record_operation_approval_tool`：记录 `grant` 或 `reject` 结论。
- `renew_operation_approval_tool`：续期已通过且未过期的审批，不改变审批范围。
- `revoke_operation_approval_tool`：撤销尚未终止的审批，撤销后不能进入真实执行。
- `cleanup_expired_operation_approvals_tool`：扫描或标记过期审批，默认 `dry_run=true`。
- `verify_approval_chain_tool`：只读校验审批账本 `prev_hash / event_hash` 哈希链。
- `anchor_approval_chain_tool`：为审批账本创建外部锚点。
- `verify_approval_anchor_tool`：验证审批账本是否仍匹配最近锚点。
- `get_operation_approval_tool`：查询单个 `approval_id` 最新状态。
- `get_approval_review_packet_tool`：查询 B/S 审批页可渲染的只读审核包，包含审批历史、trace 审计事件和合并时间线。
- `list_operation_approvals_tool`：查询最近审批记录，可按 `status` 或 `trace_id` 过滤。

`record_operation_approval_tool` 已新增可选 `approval_token` 参数。开启 `TMP_MCP_REQUIRE_APPROVAL_IDENTITY=true` 后，审批结论必须携带由外部审批通道签发的 HMAC token，否则不会写入审批账本。

审计事件：

- `approval_requested`
- `approval_granted`
- `approval_rejected`
- `approval_renewed`
- `approval_revoked`
- `approval_expired`
- `approval_cleanup`
- `approval_chain_verification`
- `approval_anchor_created`
- `approval_anchor_verification`
- `approval_identity_denied`
- `approval_identity_verified`
- `tool_result` 中包含 `approval_validation`

写操作 dry-run 返回：

- `data.approval_request`：可直接传给 `request_operation_approval_tool` 的参数包。
- `data.approval_scope_hash`：基于可复制参数包计算的审批范围 hash。
- `data.execute_after_approval`：审批通过后可复用的真实执行参数模板，只需要替换 `approval_id`。

默认账本路径：

```text
tmp_MCP/data/approvals/approvals.jsonl
```

可通过环境变量覆盖：

```powershell
$env:TMP_MCP_APPROVAL_DIR="G:\完整mcp\tmp_MCP\data\approvals"
```

## 审批记录结构

审批记录采用追加写 JSONL。相同 `approval_id` 的最后一条记录代表当前状态。

核心字段：

- `approval_id`：审批 ID，格式类似 `appr_...`。
- `status`：`requested / partially_granted / granted / rejected / revoked / expired`。
- `tool_name`：被审批的 MCP 工具名。
- `operation`：工具内部操作名，例如 `modify_file`、`restart_service`。
- `target`：目标范围，当前主要是 `local`。
- `risk_level`：审批对应风险等级。
- `scope_hash`：基于 `tool_name / operation / target / params` 计算的范围哈希。
- `created_at` / `updated_at` / `expires_at`：创建、更新与过期时间。
- `requester` / `approver` / `renewed_by` / `revoked_by` / `expired_by`：申请人、审批人和状态变更人标识。
- `renewal_count` / `last_action`：续期次数和最后一次生命周期动作。
- `trace_id` / `session_id`：链路追踪字段。
- `params_summary` / `plan_summary`：参数和计划摘要。
- `prev_hash` / `event_hash`：审批账本哈希链字段，第一条从 `sha256:GENESIS` 开始。

## 审批账本哈希链

新写入审批记录会自动计算：

- `prev_hash`：上一条审批记录的 `event_hash`。
- `event_hash`：基于 `prev_hash` 和当前记录稳定 JSON 计算的 SHA-256。

`verify_approval_chain_tool` 会重新读取账本并校验：

- 原始账本通过。
- 修改中间记录会触发 `event_hash` 不匹配。
- 删除中间记录会触发下一行 `prev_hash` 不匹配。
- 旧格式记录缺少链字段时返回 `missing hash chain fields`。

## 审批账本外部锚点

审批哈希链可以证明现有账本内部没有被局部篡改。外部锚点进一步记录某一时刻的链尾 hash 和整个审批文件摘要，用于发现账本被整体重算、替换或截断。

默认锚点位置：

```text
tmp_MCP/data/approvals/anchors/anchors.jsonl
```

可选环境变量：

```powershell
$env:TMP_MCP_APPROVAL_ANCHOR_SECRET="your-local-approval-anchor-secret"
```

- `anchor_approval_chain_tool` 会先调用审批哈希链校验，只有账本有效才创建锚点。
- `verify_approval_anchor_tool` 会比对 `head_hash / file_sha256`，并在启用 HMAC 时校验签名。
- 未配置 HMAC 时仍能发现账本与锚点不一致，但不能证明锚点本身没有被本地重写。

## 外部审批身份通道

PR-D 预开发已加入外部审批身份 token 校验，用于把 `approver` 从裸字符串推进为可验证凭证。

环境变量：

```powershell
$env:TMP_MCP_APPROVAL_IDENTITY_SECRET="your-external-approval-hmac-secret"
$env:TMP_MCP_REQUIRE_APPROVAL_IDENTITY="true"
$env:TMP_MCP_REQUIRE_APPROVAL_IDENTITY_SCOPE="true"
```

- `approval_token` 由外部审批通道签发，MCP Server 只验证，不应把签发能力暴露给普通会话。
- token 绑定 `approval_id / decision / approver`，可选绑定 `scope_hash / record_event_hash`。
- 验证失败写入 `approval_identity_denied`，不追加审批账本。
- 验证成功写入 `approval_identity_verified`，并把摘要写入 `approver_history[].identity`。

## scope_hash 规则

`scope_hash` 用于防止审批被挪用。审批通过只对同一组操作范围生效：

- 相同 `tool_name`
- 相同 `operation`
- 相同 `target`
- 相同归一化参数

归一化参数会忽略：

- `approval_id`
- `dry_run`
- `guard_context`
- `reason`
- `session_id`
- `trace_id`

这样可以允许同一计划从 dry-run 切换到真实执行，但不能把“修改 A 文件”的审批拿去“删除 B 文件”。

## 执行前校验

当写工具满足以下条件时才进入真实固定模板：

- 安全意图校验未命中 `critical`。
- `dry_run=false`。
- `approval_id` 存在。
- 审批账本中能查到该 `approval_id`。
- 最新状态为 `granted`。
- 未超过 `expires_at`。
- `tool_name / operation / target / scope_hash` 全部匹配。

如果最新状态为 `rejected / revoked / expired`，或虽然状态仍是 `requested/granted` 但时间戳已过期，真实写操作都会在 `approval_validation` 阶段被阻断。

任何一项不满足，写工具会返回：

- `ok=false`
- `risk_level=high`
- `data.blocked=true`
- `data.approval_validation.ok=false`
- `data.human_report` 中解释失败原因

## AstrBot 测试提示词

创建审批申请：

```text
只允许通过 MCP 工具调用，不要使用 shell。先调用 request_modify_file 生成 dry_run 计划，不要真实修改文件。然后复制返回的 data.approval_request 调用 request_operation_approval_tool 创建审批申请。
```

记录审批通过：

```text
只允许通过 MCP 工具调用，不要使用 shell。调用 record_operation_approval_tool，将上一步 approval_id 记录为 grant，审批人为 verify-admin，备注为“本地沙箱验证审批流”。
```

查询审批状态：

```text
只允许通过 MCP 工具调用，不要使用 shell。调用 get_operation_approval_tool 查询上一步 approval_id，并根据 data.human_report 说明审批状态、过期时间、scope_hash 和 trace_id。
```

验证伪造审批阻断：

```text
只允许通过 MCP 工具调用，不要使用 shell。调用 request_restart_service，参数 service=Spooler、platform_hint=windows、dry_run=false、approval_id=appr_fake_not_found。不要使用 shell，并说明 approval_validation 为什么阻断。
```

查询审批列表：

```text
只允许通过 MCP 工具调用，不要使用 shell。调用 list_operation_approvals_tool，limit=5，只查询最近审批记录，并按 data.human_report 解释。
```

续期并撤销审批：

```text
只允许通过 MCP 工具调用，不要使用 shell。创建一个 request_modify_file 的审批申请并记录 grant，然后调用 renew_operation_approval_tool 续期，再调用 revoke_operation_approval_tool 撤销。最后复用原 approval_id 执行 dry_run=false，说明 approval_validation 为什么阻断。
```

校验审批账本：

```text
只允许通过 MCP 工具调用，不要使用 shell。调用 verify_approval_chain_tool 校验审批账本，并说明 checked_records、first_bad_line、expected_hash 和 actual_hash。
```

## 自动化验收

`scripts/verify_mcp_operations.py` 已覆盖：

- 所有高风险写操作 dry-run 都返回 `data.approval_request`、`data.approval_scope_hash` 和 `data.execute_after_approval`。
- 创建审批申请。
- 记录审批通过。
- 直接使用 dry-run 返回的 `data.approval_request` 创建审批，并使用 `data.execute_after_approval` 对临时文件执行固定模板修改。
- 查询单个审批记录。
- 查询最近审批列表。
- 查询 B/S 审批审核包，确认返回 `ledger_history`、`audit_events`、`timeline` 和 `review_packet`。
- 使用伪造 `approval_id` 验证真实执行被阻断。
- 验证审批通过后可续期、可撤销，撤销后复用原 `approval_id` 会在真实执行前被阻断。
- 调用 `verify_approval_chain_tool` 校验审批账本哈希链，并确认写入 `approval_chain_verification` 审计事件。
- 调用 `anchor_approval_chain_tool` 和 `verify_approval_anchor_tool` 校验审批账本外部锚点，并确认写入 `approval_anchor_verification` 审计事件。
- 强制开启外部审批身份 token 后，缺失 token 被拒绝，签名 token 可以记录审批，并确认写入 `approval_identity_denied / approval_identity_verified` 审计事件。

`scripts/verify_approval_lifecycle.py` 额外覆盖：

- `requested / granted / rejected / revoked / expired` 状态流转。
- 续期不改变 `tool_name / operation / target / scope_hash`。
- 撤销、拒绝和过期审批不能进入真实执行。
- 过期清理默认 `dry_run=true`，提交清理时追加 `expired` 记录。

`scripts/verify_approval_chain.py` 额外覆盖：

- 新写入记录包含 `prev_hash / event_hash`。
- 原始账本通过。
- 篡改中间记录失败。
- 删除中间记录失败。
- 旧格式无链字段记录失败。

`scripts/verify_approval_anchor.py` 额外覆盖：

- HMAC 签名锚点创建成功。
- 原始审批账本通过锚点校验。
- 缺失或错误 HMAC 密钥会失败。
- 锚定后追加审批记录会触发 `head_hash mismatch` 和 `file_sha256 mismatch`。

`scripts/verify_approval_identity.py` 额外覆盖：

- 强制身份校验时缺失 token 被拒绝。
- HMAC 签名 token 可以通过验证并记录审批。
- 错误审批人、错误 `scope_hash` 和篡改 token 会失败。
- 带身份摘要的审批记录仍通过审批账本哈希链校验。

`scripts/verify_approval_review_packet.py` 额外覆盖：

- `get_approval_review_packet_tool` 按 `approval_id` 查询最新审批状态。
- `ledger_history` 包含同一审批的追加账本历史。
- `audit_events` 包含同 `trace_id` 的审批审计事件。
- `timeline` 同时包含 `approval_ledger` 和 `audit` 来源。
- `review_packet.policy / lineage / identity / audit` 可供 B/S 页面渲染。

最近一次验收目标：

```text
58 / 58 PASS
```

## 安全边界

- 审批不能放行 `critical` 风险。
- 审批不能放行任意 shell。
- 审批只对匹配范围生效，不能跨工具、跨操作、跨目标复用。
- 本版本是本地 JSONL 审批账本，已支持最小多级审批；但仍不等价于企业级 IAM、OA 审批或强身份授权系统。
- 审批账本已有本地哈希链和外部锚点；未配置 HMAC 或未把锚点复制到主机外时，仍不能等价于第三方透明日志。

## 后续增强

建议 `0.6.0-alpha` 或后续版本继续推进：

- 托管式 B/S 审批/配置网关 MVP 已接入，消费 `get_approval_console_bundle_tool` 和配置管理 bundle 展示审批、配置与网关设置页面；后续重点是把本地 token 闸门升级为生产级登录态和权限边界。
- 对接完整外部审批系统或企业身份系统，把当前 HMAC token 和企业断言预开发通道升级为真实登录态、KMS/HSM 签名、OIDC/OAuth、LDAP/AD、企业 OA 或 mTLS 网关校验。
- 为审批身份 token 增加签名密钥轮转、撤销列表、防重放 nonce/jti 和签发审计。
- 为审批锚点增加轮转、集中查询和第三方透明日志上传。
- 将审批事件与最小权限执行代理结合，形成“审批通过 -> 受限身份执行 -> 后置检查 -> 审计锚定”的闭环。

PR-A 生命周期增强、PR-B 审批账本哈希链、PR-C 策略配置/最小多级审批、审批账本外部锚点/可选 HMAC 签名、PR-D 外部审批身份 token 预开发、B/S 审批审核包后端契约、B/S 审批控制台 bundle、企业身份断言签发 token、托管式 B/S 审批/配置网关和网关选项控制台已完成。下一步优先推进真实企业身份/OIDC/KMS 接入、服务端会话、CSRF、防重放、密钥轮转/撤销和真实受限身份执行代理。
