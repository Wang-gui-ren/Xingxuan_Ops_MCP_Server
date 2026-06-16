# 审计生产化设计文档

本文档用于规划 `tmp_MCP` 审计能力的生产化增强。当前项目已经具备本地 JSONL 审计、敏感字段脱敏、`prev_hash / event_hash` 哈希链、`trace_id / session_id` 串联、本地 `anchors.jsonl` 外部锚点和可选 HMAC-SHA256 签名。下一阶段目标不是替换这些底座，而是在其上补齐日志轮转、集中查询、第三方透明日志或集中锚定，让审计从“本机可验证”推进到“生产可保留、可查询、可证明”。

## 当前状态

已落地能力：

- `AuditLogger` 按天写入 `audit-YYYYMMDD.jsonl`，默认目录来自 `TMP_MCP_AUDIT_DIR` 或 `tmp_MCP/data/audit`。
- 审计事件落盘前会脱敏，并追加 `prev_hash / event_hash`，形成单文件哈希链。
- `verify_audit_chain_tool` 可校验指定审计 JSONL 是否存在篡改、删行、断链或 hash 不匹配。
- `anchor_audit_chain_tool` 会为指定审计文件创建本地锚点，记录 `head_hash`、`file_sha256`、`file_size_bytes` 和 `checked_events`。
- `verify_audit_anchor_tool` 可校验当前审计文件是否仍匹配最近一次锚点。
- `TMP_MCP_AUDIT_ANCHOR_SECRET` 存在时，锚点使用 HMAC-SHA256 签名。
- `get_audit_events_tool` 支持查询最近事件，并按 `event_type / tool_name / risk_level / session_id / trace_id` 过滤。

生产化缺口：

- 没有按文件大小或保留周期轮转，长时间运行后单日文件可能过大。
- 没有跨文件 manifest，无法稳定表达“某一天由多个链段组成”。
- 查询仍以读取本地 JSONL 为主，不适合大量审计事件和 B/S 时间线检索。
- 锚点创建需要手工触发，尚未形成自动锚定策略。
- 锚点仍主要落在本机，尚未上传到集中审计服务、对象存储、Git 仓库或 Rekor/Sigstore 风格透明日志。

## 目标架构

生产化审计分三层推进。

```text
MCP Tools / Gateway / Approval Flow
        |
        v
AuditLogger append
        |
        +--> Audit Rotation
        |       audit-YYYYMMDD-N.jsonl
        |       audit-manifest-YYYYMMDD.json
        |
        +--> Central Audit Query
        |       readonly index
        |       search_audit_events_tool
        |
        +--> Anchor Sink
                local anchors.jsonl
                centralized HTTP anchor service
                transparency log adapter
```

### Audit Rotation

目标是让审计文件可长期运行、可归档、可逐段验证。

第一版策略：

- 继续保留 JSONL 原始日志作为事实源。
- 文件命名从单一 `audit-YYYYMMDD.jsonl` 扩展为 `audit-YYYYMMDD-N.jsonl`，其中 `N` 从 `1` 开始递增。
- 默认仍允许单日单文件；只有达到轮转条件时才生成下一个链段。
- 轮转条件建议支持：
  - `max_file_size_mb`：默认 64 MB。
  - `max_events_per_file`：默认不启用。
  - `rotate_at_day_boundary`：默认启用。
  - `retention_days`：默认 90 天，只影响归档清理，不影响最新写入。
- 每个 JSONL 文件内部仍从 `sha256:GENESIS` 开始形成独立哈希链。
- 跨文件关系由 manifest 表达，不把上一文件的 `event_hash` 强塞进下一文件的第一条事件，避免破坏现有 verifier 语义。

manifest 建议路径：

```text
tmp_MCP/data/audit/manifests/audit-manifest-YYYYMMDD.json
```

manifest 建议字段：

```json
{
  "date": "2026-06-11",
  "segments": [
    {
      "chain_segment_id": "audit-20260611-1",
      "audit_file": "audit-20260611-1.jsonl",
      "first_event_timestamp": "2026-06-11T00:00:01Z",
      "last_event_timestamp": "2026-06-11T08:30:00Z",
      "checked_events": 1024,
      "head_hash": "sha256:...",
      "file_sha256": "sha256:...",
      "file_size_bytes": 10485760,
      "anchor_id": "optional-anchor-id"
    }
  ],
  "version": "tmp-mcp-audit-manifest-v1"
}
```

轮转安全要求：

- 轮转只能在完成上一条事件写入后发生。
- 被轮转出的旧文件默认只读，不再追加事件。
- 对旧文件创建锚点后，任何追加、删改或重算都应被 `verify_audit_anchor_tool` 发现。
- manifest 是索引和目录，不是审计事实源；原始 JSONL 和锚点验证优先级更高。

### Central Audit Query

目标是让 B/S 网关、AstrBot 和人工审计可以稳定查询跨文件审计事件。

第一版建议使用只读索引层，不改变原始日志结构。索引实现可以选择 SQLite 或 JSONL 索引文件；推荐先用 SQLite，因为它能自然支持多字段过滤、分页和时间范围查询。

索引建议字段：

| 字段 | 说明 |
| --- | --- |
| `event_id` | 审计事件 ID |
| `timestamp` | 事件时间 |
| `event_type` | 事件类型 |
| `tool_name` | MCP 工具名 |
| `risk_level` | 风险等级 |
| `decision` | 护栏或审批决策 |
| `session_id` | 会话 ID |
| `trace_id` | 链路 ID |
| `approval_id` | 审批 ID，如事件中存在 |
| `audit_file` | 原始 JSONL 文件 |
| `line_number` | 原始文件行号 |
| `event_hash` | 当前事件 hash |
| `prev_hash` | 上一事件 hash |
| `chain_segment_id` | 审计链段 ID |
| `indexed_at` | 索引写入时间 |

查询工具建议：

- `search_audit_events_tool`：跨文件搜索审计事件，支持 `trace_id / session_id / event_type / tool_name / risk_level / approval_id / time_range / limit / cursor`。
- `get_audit_query_status_tool`：返回索引状态、已索引文件、最后索引时间、缺失链段和重建建议。
- `get_audit_events_tool` 保持兼容，继续用于最近事件查询；后续可以内部复用索引，但不改变调用契约。

查询返回约束：

- 默认返回脱敏后的审计事件。
- 默认按时间倒序。
- 每次查询限制最大 `limit`，建议上限 500。
- 查询结果应携带 `audit_file / line_number / event_hash`，方便回到原始 JSONL 复核。
- 查询工具只读，不写原始审计日志；如需记录查询行为，写入新的审计事件时不得递归触发无限查询审计。

### Anchor Sink

目标是把本地锚点升级为可复制、可集中校验、可接第三方透明日志的锚定通道。

第一版抽象：

```text
AnchorSink
  LocalJsonlAnchorSink
  HttpAnchorSink
  TransparencyLogAnchorSink
```

默认行为：

- 未配置外部 sink 时，继续写本地 `anchors.jsonl`。
- 配置 `TMP_MCP_AUDIT_ANCHOR_SECRET` 时，本地和外部锚点 payload 均使用 HMAC-SHA256 签名。
- 外部同步只上传锚点摘要，不上传完整审计事件。

锚点同步建议工具：

- `sync_audit_anchor_tool`：对指定审计文件或 manifest 中的链段创建锚点，并同步到配置的 sink。
- `verify_audit_anchor_tool`：继续校验本地锚点；后续可扩展 `source=local|remote|all`。
- `rotate_audit_logs_tool`：可手动触发轮转，并可选对旧链段创建锚点。

外部锚点 payload 建议包含：

```json
{
  "anchor_id": "uuid",
  "timestamp": "2026-06-11T10:00:00Z",
  "chain_segment_id": "audit-20260611-1",
  "audit_file": "audit-20260611-1.jsonl",
  "checked_events": 1024,
  "head_hash": "sha256:...",
  "file_sha256": "sha256:...",
  "file_size_bytes": 10485760,
  "signer": "tmp_MCP-local",
  "signature_algorithm": "hmac-sha256",
  "signature": "base64-or-hex",
  "transparency_log_hint": "local-jsonl-anchor",
  "version": "tmp-mcp-audit-anchor-v1"
}
```

失败处理：

- 外部 sink 不可用时，本地审计落盘不能被阻断。
- 同步失败必须写入 `audit_anchor_sync_failed` 审计事件，记录失败目标、错误摘要和待重试锚点 ID。
- 同步成功建议写入 `audit_anchor_synced` 审计事件，记录 sink 类型和远端回执摘要。
- 不在审计事件中记录外部服务 token、HMAC secret 或完整 Authorization header。

## MCP 接口方向

建议后续新增或扩展以下 MCP 工具。

| 工具 | 类型 | 说明 |
| --- | --- | --- |
| `rotate_audit_logs_tool` | 管理工具 | 手动触发轮转，返回新旧链段、manifest 和可选锚点结果 |
| `get_audit_query_status_tool` | 只读工具 | 查看索引状态、未索引文件、最后同步时间和错误 |
| `search_audit_events_tool` | 只读工具 | 跨文件审计检索，支持分页和多字段过滤 |
| `sync_audit_anchor_tool` | 管理工具 | 为审计链段创建本地锚点并同步到外部 sink |

兼容原则：

- 不移除 `get_audit_events_tool`。
- 不改变现有 `AuditEvent` 必填字段。
- 不改变现有 `prev_hash / event_hash` 计算方式。
- 新增生产化元数据以附加字段出现，例如 `audit_file`、`chain_segment_id`、`anchor_id`、`indexed_at`。
- 管理类工具需要进入审计日志；只读查询工具是否记录由后续配置决定，默认可记录摘要。

## 安全边界

- 轮转不能破坏单文件哈希链；每个链段必须能被 `verify_audit_chain` 独立校验。
- 集中查询层只读，不负责修改原始 JSONL、manifest 或锚点。
- 索引可重建，原始 JSONL、manifest 和锚点才是可信事实源。
- 第三方透明日志或集中锚定只上传锚点摘要，不上传完整审计事件。
- 外部同步失败不得阻断本地审计落盘。
- 任何外部同步错误都必须形成可追踪审计事件。
- HMAC secret、外部 API token、Cookie、Authorization 等凭据必须继续走现有脱敏规则。
- 透明日志适配器必须默认超时，避免 MCP 工具调用被外部网络长时间拖住。

## 建议开发顺序

第一阶段：轮转与 manifest。

- 新增轮转配置模型，默认不开启大小轮转，只保留按日兼容行为。
- 扩展 `AuditLogger._path_for_today()` 为可感知链段的路径选择函数。
- 新增 manifest 写入和读取模块。
- 新增 `rotate_audit_logs_tool` 和专项验证脚本。

第二阶段：集中查询索引。

- 新增只读索引构建器，支持从 JSONL 重建。
- 新增 `search_audit_events_tool` 和 `get_audit_query_status_tool`。
- 让 B/S 审批审核包后续可选消费集中查询，而不是只读最近事件。

第三阶段：Anchor Sink。

- 抽象 `AnchorSink`，保留本地 JSONL sink 作为默认实现。
- 新增 HTTP sink 配置和超时、重试、失败审计。
- 预留 Rekor/Sigstore 风格透明日志适配器，不在第一版强绑定外部服务。

第四阶段：生产验收和文档联动。

- 补充 `scripts/verify_audit_productionization.py`。
- 更新 `MCP_OPERATION_VERIFICATION.md` 的审计生产化用例。
- 更新 B/S 网关审计时间线说明。

## 验收测试计划

静态检查：

- `python -m compileall -q tmp_MCP/src/mcp_ops_server tmp_MCP/scripts` 通过。
- 新增脚本可在临时目录中运行，不污染真实 `data/audit`。

轮转验证：

- 连续生成多段审计文件后，每段 `verify_audit_chain` 均通过。
- 达到大小阈值或手动调用 `rotate_audit_logs_tool` 后，旧文件不再追加，新事件写入新链段。
- manifest 能列出所有链段，并记录每段的 `head_hash`、`file_sha256` 和事件数。
- 删除或篡改旧链段后，manifest 复核或锚点校验能定位异常。

集中查询验证：

- 索引重建后，事件总数与原始 JSONL 行数一致。
- `search_audit_events_tool(trace_id=...)` 可查回跨文件事件。
- `approval_id / event_type / tool_name / risk_level / time_range` 过滤稳定。
- 查询结果包含 `audit_file / line_number / event_hash`。
- 删除索引后可从原始 JSONL 重建，查询结果一致。

锚点同步验证：

- 本地锚点创建后，`verify_audit_anchor_tool` 通过。
- 配置 HTTP sink 后，`sync_audit_anchor_tool` 返回远端回执摘要。
- 锚点同步成功后，本地 `head_hash / file_sha256` 与远端回执一致。
- 模拟远端不可用时，本地审计继续写入，并产生 `audit_anchor_sync_failed` 事件。
- 错误 HMAC secret 或篡改 payload 时，签名校验失败。

回归验证：

- `get_audit_events_tool` 原有参数和返回结构保持兼容。
- 审批、网关、执行策略等已有审计事件继续落盘。
- 审计脱敏规则仍覆盖 token、secret、password、authorization、cookie 等敏感字段。

## 默认假设

- 第一版只规划文档和后续实现边界，不立即修改审计代码。
- 原始审计日志继续使用 JSONL，集中查询层只做索引和检索。
- 第三方透明日志第一阶段采用适配器抽象，不强绑定外部服务。
- 生产化优先保证“可证明未篡改”和“可查”，暂不引入复杂分布式日志系统。
- 审批账本生产化可复用同一思路，但本文档优先覆盖 `audit/` 审计日志。
