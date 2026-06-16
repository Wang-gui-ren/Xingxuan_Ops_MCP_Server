# PR-D B/S 与外部审批身份通道预开发文档

本文档承接 `APPROVAL_ENHANCEMENT_IMPLEMENTATION_PLAN.md` 的 PR-D。当前阶段先把“可信审批人身份”和“审批页面只读物料”接入现有 MCP 审批链路，已提供自包含 B/S 审批控制台 bundle；独立托管的 HTTP 网关、正式登录态和企业 IAM/OA 集成留给后续 WebUI、OA、飞书、企业微信或 IAM 审批系统复用同一套服务端校验路径。

## 当前状态

截至 2026-06-10，本阶段已从“只读审核包预开发”推进到第一版 B/S 审批控制台 bundle 与企业身份断言桥：

- `src/mcp_ops_server/web/approval_console.py`
  - 新增 `build_approval_console_bundle()`，输出 `approval-console-bundle-v1`。
  - bundle 内包含审批队列、指标、审核工作区、策略摘要、账本血缘、trace 时间线、企业身份状态和只读 HTML。
  - 当前是 MCP 返回的自包含 HTML/JSON，不是独立托管的 HTTP Web 服务。
- `get_approval_console_bundle_tool`
  - 新增 B/S 审批页面 bundle 后端契约。
  - 聚合最近审批列表、选中审批的 `review_packet`、trace 审计事件和身份模式。
  - 只读，不创建审批、不记录审批结论、不签发 token。
- `approvals/external.py`
  - 在原有审批决策 token 基础上，新增企业身份断言创建与验证函数。
  - 支持 issuer allowlist、审批人角色、`approval_id / decision / approver` 绑定、过期时间和 HMAC-SHA256 签名校验。
- `issue_enterprise_approval_token_tool`
  - 新增企业身份断言换取 MCP 审批 token 的工具。
  - 默认关闭，必须显式启用 `TMP_MCP_ENABLE_ENTERPRISE_APPROVAL_TOKEN_ISSUER=true`。
  - 成功时只签发 `approval_token`，不直接写审批账本；最终落账仍必须调用 `record_operation_approval_tool`。
- `scripts/verify_approval_console.py`
  - 专项验证 B/S bundle、缺失企业断言拒绝、错误角色拒绝、合法断言签发 token、token 落账、身份摘要、审计事件和审批账本哈希链。

截至 2026-06-10，PR-D 预开发前两步已落地：

- `src/mcp_ops_server/approvals/external.py`
  - 定义 `ExternalApprovalClient` 预留接口。
  - 提供 HMAC-SHA256 审批决策 token 的创建与验证函数。
  - 支持强制开启审批身份校验。
- `record_operation_approval_tool`
  - 新增可选参数 `approval_token`。
  - 当开启强校验时，缺失或无效 token 不会写入审批账本。
  - token 验证通过后，身份摘要写入 `approver_history[].identity`。
  - 新增 `approval_identity_denied`、`approval_identity_verified` 审计事件。
- `scripts/verify_approval_identity.py`
  - 专项验证缺失 token、签名 token、错误审批人、错误 scope、篡改 token 和哈希链兼容。
- `scripts/verify_mcp_operations.py`
  - 新增 `approval_identity` 和 `approval_review_packet` 端到端用例，覆盖 MCP 工具路径。
- `get_approval_review_packet_tool`
  - 新增 B/S 审批页只读后端契约。
  - 按 `approval_id` 返回最新审批状态、同一审批的追加账本历史、同 `trace_id` 审计事件和合并时间线。
  - 返回 `review_packet.schema_version=approval-review-packet-v1`，包含 policy、lineage、identity、audit 和 timeline。
- `scripts/verify_approval_review_packet.py`
  - 专项验证审批审核包包含账本历史、trace 审计事件、时间线和 `data.human_report`。

## 目标

PR-D 预开发解决的问题：

1. `approver` 不再只能是裸字符串。
2. 普通会话即使拿到 `record_operation_approval_tool`，在强校验模式下也不能随意伪造审批人。
3. 审批身份结果进入审批账本和审计日志，后续可按 `trace_id` 回放。
4. 未来 B/S 或外部审批系统只需要签发同一格式的 `approval_token`，MCP Server 负责验证和落账。
5. 未来 B/S 审批页面不用直接读 `approvals.jsonl` 或审计 JSONL，可通过 `get_approval_review_packet_tool` 获取只读审核包，通过 `get_approval_console_bundle_tool` 获取审批控制台视图模型和自包含 HTML。

## 非目标

本阶段不做：

- 独立托管的 B/S 网关、HTTP 服务、正式登录态和 CSRF/会话管理。
- OAuth / LDAP / SSO 的真实接入。
- 飞书、企微、OA 的网络 API 调用。
- 把 token 签发能力暴露给普通用户会话；`issue_enterprise_approval_token_tool` 只能放在可信审批网关、管理员或企业身份通道。
- 让 B/S 页面直接写审批账本或绕过 MCP 工具落账。
- 放开 `critical` 风险审批。
- 绕过多级审批、审批策略、哈希链、锚点或 `ExecutionPolicy`。

## 环境变量

```powershell
$env:TMP_MCP_APPROVAL_IDENTITY_SECRET="your-external-approval-hmac-secret"
$env:TMP_MCP_REQUIRE_APPROVAL_IDENTITY="true"
$env:TMP_MCP_REQUIRE_APPROVAL_IDENTITY_SCOPE="true"
```

含义：

| 变量 | 作用 |
| --- | --- |
| `TMP_MCP_APPROVAL_IDENTITY_SECRET` | HMAC-SHA256 签名密钥。生产环境应来自密钥管理，不应写入仓库。 |
| `TMP_MCP_REQUIRE_APPROVAL_IDENTITY` | 为 `true` 时，`record_operation_approval_tool` 必须提供合法 `approval_token`。 |
| `TMP_MCP_REQUIRE_APPROVAL_IDENTITY_SCOPE` | 为 `true` 时，token 必须绑定审批记录 `scope_hash`。 |
| `TMP_MCP_ENABLE_ENTERPRISE_APPROVAL_TOKEN_ISSUER` | 为 `true` 时，允许 `issue_enterprise_approval_token_tool` 使用企业身份断言签发 MCP 审批 token。默认关闭。 |
| `TMP_MCP_ENTERPRISE_IDENTITY_ASSERTION_SECRET` | 企业身份断言 HMAC-SHA256 签名密钥。生产环境应由 B/S/IAM 或 KMS 托管。 |
| `TMP_MCP_ENTERPRISE_IDENTITY_ALLOWED_ISSUERS` | 可选 issuer 白名单，逗号分隔，例如 `corp-idp,approval-gateway`。 |
| `TMP_MCP_ENTERPRISE_APPROVER_ROLE` | 企业审批人必需角色，默认 `ops_approver`。 |

未开启强校验时，系统保持向后兼容，继续使用 PR-C 的本地审批人白名单、自批拦截和重复审批人拦截。

## Token 结构

外部审批系统签发的 token 是一个 JSON object，可直接传给 `record_operation_approval_tool(approval_token=...)`：

```json
{
  "version": "tmp-mcp-approval-identity-v1",
  "token_id": "hex id",
  "issuer": "approval-web-ui",
  "subject": "ops-admin@example.com",
  "approval_id": "appr_xxx",
  "decision": "grant",
  "approver": "verify-admin",
  "issued_at": "2026-06-10T10:00:00+00:00",
  "expires_at": "2026-06-10T10:15:00+00:00",
  "key_id": "approval-hmac-2026-06",
  "signature_algorithm": "hmac-sha256",
  "scope_hash": "sha256:...",
  "record_event_hash": "sha256:...",
  "signature": "hmac-sha256:..."
}
```

### 企业身份断言换取 token

当前第一版企业身份接入采用“两段式”桥接：

1. B/S、OA、IAM 或测试脚本生成企业身份断言，断言必须包含 `issuer / subject / roles / approval_id / decision / approver / expires_at / signature`。
2. `issue_enterprise_approval_token_tool` 校验断言、审批状态、审批范围和角色后，签发 MCP 内部 `approval_token`。
3. `record_operation_approval_tool` 再携带该 `approval_token` 记录 `grant` 或 `reject`，并把身份摘要写入 `approver_history[].identity`。

这样可以把“企业登录态是否可信”和“审批账本是否落账”拆开：签发工具不直接落账，落账工具不直接信任字符串审批人。

签名规则：

- 使用稳定 JSON：`sort_keys=True`、`separators=(",", ":")`、`ensure_ascii=False`。
- 签名 payload 不包含 `signature` 字段。
- 签名算法为 HMAC-SHA256。
- `decision` 归一化为 `grant` 或 `reject`。

## 校验规则

`verify_approval_decision_token()` 会检查：

- token 版本和签名算法。
- HMAC 签名是否匹配。
- `approval_id` 是否等于当前审批。
- `decision` 是否等于当前记录动作。
- `approver` 是否等于当前审批人参数。
- `issued_at` 不能明显来自未来。
- `expires_at` 必须未过期。
- 如果 token 包含 `scope_hash`，必须等于审批记录 `scope_hash`。
- 如果 token 包含 `record_event_hash`，必须等于当前审批记录 `event_hash`。
- 开启 `TMP_MCP_REQUIRE_APPROVAL_IDENTITY_SCOPE=true` 时，必须携带 `scope_hash`。

验证失败时：

- `record_operation_approval_tool` 返回 `ok=false`。
- 不追加审批账本记录。
- 写入 `approval_identity_denied` 审计事件。

验证成功时：

- 继续执行原有 PR-C 审批策略校验。
- 写入 `approval_identity_verified` 审计事件。
- 将身份摘要写入 `approver_history[].identity`。

## 后续 B/S 接入边界

未来 B/S 管理端建议只做三件事：

1. 调用 `list_operation_approvals_tool` 或 `get_approval_review_packet_tool` 查询待审批列表、审批详情和 trace 时间线。
2. 用真实登录态、角色和审批页面生成 `approval_token`。
3. 调用 `record_operation_approval_tool`，传入 `approval_id / decision / approver / approval_token`。

B/S 管理端不应直接写 `approvals.jsonl`。所有审批状态变化仍由 `ApprovalStore` 追加写入，并继续进入哈希链、锚点和审计链。

### 审批审核包契约

`get_approval_review_packet_tool(approval_id, include_audit_events=true, audit_limit=50)` 返回：

| 字段 | 说明 |
| --- | --- |
| `approval` | 当前最新审批记录，仍以 `ApprovalStore.get_latest()` 为准 |
| `ledger_history` | 同一 `approval_id` 的追加账本历史，按写入顺序排列 |
| `audit_events` | 同 `trace_id` 的审计事件，供页面展示 guardrail、身份校验和审批结果 |
| `timeline` | 合并后的页面时间线，`source` 为 `approval_ledger` 或 `audit` |
| `review_packet.policy` | `required_approvals / granted_approvals / remaining_approvals` 等策略摘要 |
| `review_packet.lineage` | `prev_hash / event_hash / created_at / updated_at / expires_at` 等账本血缘 |
| `review_packet.identity` | 已验证身份摘要，例如 `provider / subject / token_id / key_id` |

该工具是只读能力，不创建审批、不记录审批结论、不签发 token。

### B/S 审批控制台 bundle 契约

`get_approval_console_bundle_tool(approval_id=None, limit=20, status=None, include_audit_events=true, audit_limit=50, include_html=true)` 返回：

| 字段 | 说明 |
| --- | --- |
| `console_bundle.schema_version` | 当前为 `approval-console-bundle-v1` |
| `console_bundle.state.approvals` | 页面队列所需的审批摘要 |
| `console_bundle.state.review_packet` | 选中审批的只读审核包 |
| `console_bundle.state.audit_events` | 同 trace 审计事件 |
| `console_bundle.state.identity_mode` | 审批身份、企业断言签发、issuer allowlist 和必需角色状态 |
| `console_bundle.state.mcp_contract` | 页面需要调用的 MCP 工具契约说明 |
| `console_bundle.html` | 自包含 HTML，可由上层 B/S 网关或调试工具渲染 |

该 bundle 仍是只读页面物料，不等价于生产 B/S 网关。生产接入时应由真实 Web 服务负责登录态、CSRF、防重放、权限菜单、密钥托管和工具暴露隔离。

## AstrBot 暴露建议

普通用户会话：

```text
request_operation_approval_tool
get_operation_approval_tool
get_approval_review_packet_tool
get_approval_console_bundle_tool
list_operation_approvals_tool
verify_approval_chain_tool
verify_approval_anchor_tool
```

审批人、管理员或外部审批通道：

```text
record_operation_approval_tool
issue_enterprise_approval_token_tool
renew_operation_approval_tool
revoke_operation_approval_tool
cleanup_expired_operation_approvals_tool
anchor_approval_chain_tool
```

开启 `TMP_MCP_REQUIRE_APPROVAL_IDENTITY=true` 后，即使 `record_operation_approval_tool` 暴露给普通会话，缺少合法 `approval_token` 也无法落账；但生产上仍建议隔离工具暴露边界。

## 验收命令

```powershell
$env:PYTHONPATH="G:\完整mcp\tmp_MCP\src"
D:\miniconda\envs\astrbot\python.exe -m compileall -q tmp_MCP\src\mcp_ops_server tmp_MCP\scripts
D:\miniconda\envs\astrbot\python.exe tmp_MCP\scripts\verify_approval_identity.py
D:\miniconda\envs\astrbot\python.exe tmp_MCP\scripts\verify_approval_review_packet.py
D:\miniconda\envs\astrbot\python.exe tmp_MCP\scripts\verify_approval_console.py
D:\miniconda\envs\astrbot\python.exe tmp_MCP\scripts\verify_mcp_operations.py
```

预期：

- `verify_approval_identity.py` 输出 `15 / 15 PASS`。
- `verify_approval_review_packet.py` 输出 `13 / 13 PASS`。
- `verify_approval_console.py` 输出 `25 / 25 PASS`。
- `verify_mcp_operations.py` 输出 `passed = total`，并包含 `approval_identity` 和 `approval_review_packet` 用例；当前目标为 `58 / 58 PASS`。

## 后续增强

1. 将当前 self-contained HTML bundle 包装成真实 B/S 网关，补齐登录态、路由、会话、CSRF、防重放、权限菜单和工具暴露隔离。
2. 将 HMAC 企业断言替换或增强为真实 IAM / OIDC / OAuth / LDAP / mTLS 或 KMS 托管签名。
3. 为企业断言与审批 token 增加 key rotation、撤销列表、短期 nonce、防重放缓存和审计导出。
4. 把审批身份与真实最小权限执行代理串联，形成“可信审批 -> 受限身份执行 -> 后置校验 -> 锚定”的闭环。
