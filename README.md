# 星璇运维 MCP (Xingxuan MCP)

> 一个面向生产环境的安全运维 MCP Server，为 AI Agent 提供结构化运维工具、多重防护栏和完整审计链。

**星璇运维 MCP** 是一个基于 [Model Context Protocol](https://modelcontextprotocol.io) 的运维工具服务器，专为需要安全执行运维操作的 AI Agent 设计。它不是简单地暴露 shell 命令，而是提供：

- ✅ **结构化工具**：将常见运维操作封装为类型安全的 MCP 工具
- 🛡️ **三重防护栏**：风险评估 → 人工审批 → 执行后检查
- 📝 **完整审计链**：所有操作可追溯、可验证、支持外部审计
- 🌐 **托管 Web 界面**：审批台、配置管理、登录系统，开箱即用
- 🤖 **Agent 友好**：为 Claude Desktop、AstrBot 等提供即插即用集成

## 快速开始

### 1. 安装

```bash
pip install -e .
```

### 2. 启动 MCP Server

```bash
# 方式 1：直接启动（用于 MCP 客户端连接）
xingxuan-mcp-ops-server

# 方式 2：启动 Web 网关（用于浏览器访问和远程集成）
export XINGXUAN_MCP_GATEWAY_ADMIN_TOKEN="your-secret-token"
xingxuan-mcp-web-gateway
```

### 3. 集成到 Agent

#### 集成到 Claude Desktop

编辑 Claude Desktop 配置文件：

**macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`  
**Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "xingxuan-ops": {
      "command": "xingxuan-mcp-ops-server",
      "args": []
    }
  }
}
```

重启 Claude Desktop，你将看到新的运维工具。

#### 集成到其他 MCP 客户端

任何支持 MCP 协议的客户端都可以通过 stdio 传输连接：

```typescript
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

const transport = new StdioClientTransport({
  command: "xingxuan-mcp-ops-server",
  args: []
});

const client = new Client({
  name: "my-agent",
  version: "1.0.0"
}, {
  capabilities: {}
});

await client.connect(transport);
```

#### 集成到 AstrBot

我们提供了 AstrBot 插件，支持通过 QQ/Discord 等平台进行审批和运维：

```bash
# 安装文件系统插件
python scripts/install_astrbot_filesystem_plugin.py

# 安装审批插件
python scripts/install_astrbot_approvals_plugin.py
```

详见：[AstrBot 集成文档](docs/user/USAGE.md#astrbot-集成)

## 核心功能

### 🔧 结构化运维工具

不同于直接执行 shell，我们提供类型安全、参数校验的运维工具：

```python
# ❌ 不安全：直接 shell
run_command("rm -rf /important/data")

# ✅ 安全：结构化工具 + 审批
delete_directory_tool(
    path="/tmp/cache",
    require_approval=True,
    reason="清理临时缓存"
)
```

**可用工具类别**：

- 文件系统操作（读取、创建、删除、移动）
- 系统诊断（进程、磁盘、网络、日志）
- 审批流程（提交审批、查询状态、记录决策）
- 审计查询（操作历史、审计日志、合规报告）
- 配置管理（身份配置、策略配置、密钥轮转）

### 🛡️ 三重防护栏

#### 第一层：风险评估引擎

```yaml
# config/approvals/policies.yaml
- name: delete_protection
  pattern: "delete_*"
  risk: HIGH
  require_approval: true
  require_reason: true
```

#### 第二层：人工审批

```bash
# Web 审批台
http://localhost:8765/approvals

# 或通过 AstrBot 在 QQ/Discord 审批
```

#### 第三层：执行后检查

```python
# 自动验证执行结果
check_directory_exists("/tmp/cache")  # 应该返回 False
```

### 📝 完整审计链

所有操作自动记录，支持：
- **不可篡改审计日志**：使用 HMAC 签名防止事后修改
- **外部审计存储**：可配置推送到 S3/SFTP/Webhook
- **审计索引和查询**：按时间、操作、审批人快速检索
- **合规报告生成**：自动生成符合标准的审计报告

### 🌐 托管 Web 界面

启动网关后，通过浏览器访问：

| 路径 | 功能 |
|------|------|
| `/login` | 审批人登录/注册 |
| `/approvals` | 审批队列管理 |
| `/config-admin` | 配置管理控制台 |
| `/gateway-settings` | 网关设置 |

**特性**：

- ✅ 基于 Session Cookie 的登录系统
- ✅ 管理员 Token 保护写操作
- ✅ 响应式设计，支持移动端
- ✅ 中英双语界面

## 架构设计

```
┌─────────────────────────────────────────────────────┐
│              AI Agent (Claude/ChatGPT/etc)          │
└────────────────────┬────────────────────────────────┘
                     │ MCP Protocol
┌────────────────────▼────────────────────────────────┐
│           星璇运维 MCP Server                        │
│  ┌──────────────────────────────────────────────┐  │
│  │ 第一层：风险评估引擎                          │  │
│  │  - 基于规则的风险分级                        │  │
│  │  - 参数校验和边界检查                        │  │
│  └──────────────┬───────────────────────────────┘  │
│                 │ HIGH risk → 需要审批              │
│  ┌──────────────▼───────────────────────────────┐  │
│  │ 第二层：人工审批流程                          │  │
│  │  - Web 审批台 / AstrBot 集成                 │  │
│  │  - 多级审批人身份校验                        │  │
│  └──────────────┬───────────────────────────────┘  │
│                 │ 审批通过 → 执行                   │
│  ┌──────────────▼───────────────────────────────┐  │
│  │ 执行代理                                       │  │
│  │  - 最小权限执行                              │  │
│  │  - 超时和资源限制                            │  │
│  └──────────────┬───────────────────────────────┘  │
│                 │ 执行完成 → 后检查                 │
│  ┌──────────────▼───────────────────────────────┐  │
│  │ 第三层：执行后检查                            │  │
│  │  - 结果验证                                   │  │
│  │  - 副作用检测                                │  │
│  └──────────────┬───────────────────────────────┘  │
│                 │ 全流程记录 → 审计                 │
│  ┌──────────────▼───────────────────────────────┐  │
│  │ 审计系统                                       │  │
│  │  - 不可篡改日志                              │  │
│  │  - 外部审计存储                              │  │
│  │  - 合规报告生成                              │  │
│  └──────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────┘
```

## 配置说明

### 环境变量

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `XINGXUAN_MCP_GATEWAY_ADMIN_TOKEN` | 网关管理员 Token（保护写操作和注册） | `qingxuan` |
| `XINGXUAN_MCP_GATEWAY_HOST` | 网关监听地址 | `127.0.0.1` |
| `XINGXUAN_MCP_GATEWAY_PORT` | 网关监听端口 | `8765` |
| `XINGXUAN_MCP_USERS_CONFIG` | 用户配置文件路径 | `config/users.yaml` |
| `XINGXUAN_MCP_APPROVAL_IDENTITY_CONFIG` | 审批身份配置路径 | `config/approval_identity.yaml` |

### 审批策略配置

编辑 `config/approvals/policies.yaml`：

```yaml
policies:
  - name: high_risk_requires_approval
    description: 高风险操作需要审批
    pattern: "delete_*|modify_system_*"
    risk: HIGH
    require_approval: true
    require_reason: true
    min_approvers: 1

  - name: read_only_auto_approve
    description: 只读操作自动通过
    pattern: "read_*|list_*|get_*"
    risk: LOW
    require_approval: false
```

## 生产部署

### systemd 服务

```bash
# 复制服务文件
sudo cp packaging/systemd/xingxuan-mcp-ops.service /etc/systemd/system/

# 编辑配置
sudo systemctl edit xingxuan-mcp-ops

# 启动服务
sudo systemctl enable --now xingxuan-mcp-ops
```

### Docker 部署

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN pip install -e .
ENV XINGXUAN_MCP_GATEWAY_ADMIN_TOKEN=change-me
EXPOSE 8765
CMD ["xingxuan-mcp-web-gateway"]
```

```bash
docker build -t xingxuan-mcp .
docker run -p 8765:8765 -v ./config:/app/config xingxuan-mcp
```

## 开发指南

### 项目结构

```
.
├── src/mcp_ops_server/        # 核心实现
│   ├── approvals/              # 审批流程
│   ├── audit/                  # 审计系统
│   ├── config/                 # 配置管理
│   ├── execution/              # 执行代理
│   ├── guardrails/             # 防护栏引擎
│   ├── tool_groups/            # MCP 工具定义
│   └── web/                    # Web 界面
├── config/                     # 配置文件示例
├── scripts/                    # 安装和验证脚本
├── integrations/               # 第三方集成
│   ├── astrbot_approvals_command/
│   └── astrbot_filesystem_command/
├── docs/                       # 文档
└── tests/                      # 测试

```

### 添加新工具

1. 在 `src/mcp_ops_server/tool_groups/` 创建工具定义
2. 使用 `@mcp.tool()` 装饰器注册
3. 添加风险评估规则到 `config/approvals/policies.yaml`
4. 编写验证脚本到 `scripts/verify_*.py`

示例：

```python
from mcp.server import FastMCP

def register_my_tools(mcp: FastMCP) -> None:
    @mcp.tool()
    def my_operation(path: str, reason: str = "") -> dict:
        """执行我的自定义运维操作"""
        # 实现逻辑
        return {"ok": True, "result": "操作成功"}
```

### 运行测试

```bash
# 验证 MCP 基础功能
python scripts/verify_mcp_operations.py

# 验证审批流程
python scripts/verify_approval_console.py

# 验证 Web 网关
python scripts/verify_web_gateway.py

# 验证审计系统
python scripts/verify_audit_productionization.py
```

## 安全注意事项

1. **管理员 Token 保护**：生产环境必须修改 `XINGXUAN_MCP_GATEWAY_ADMIN_TOKEN`
2. **网络隔离**：建议网关仅监听内网地址，通过反向代理暴露
3. **审批人管理**：定期审查 `config/users.yaml` 中的审批人列表
4. **审计日志备份**：配置审计日志外部存储，防止丢失
5. **最小权限原则**：为执行代理配置最小必要的系统权限

## 兼容性说明

本项目已完成品牌升级（`tmp-mcp` → `xingxuan-mcp`），但保留向后兼容：

| 新标识 | 旧标识（仍可用） |
|--------|------------------|
| `XINGXUAN_MCP_*` | `TMP_MCP_*` |
| `xingxuan-mcp-ops-server` | `tmp-mcp-ops-server` |
| `X-XINGXUAN-MCP-Admin-Token` | `X-TMP-MCP-Admin-Token` |

优先级：`XINGXUAN_MCP_*` > `TMP_MCP_*` > 默认值

## 文档

- 📖 [使用说明](docs/user/USAGE.md)
- 🔧 [开发指南](docs/developer/DEVELOPMENT.md)
- 🚀 [部署文档](docs/deployment/README.md)
- ✅ [测试验收](docs/testing/MCP_OPERATION_VERIFICATION.md)
- 📝 [更新日志](docs/history/CHANGELOG.md)
- 🏗️ [架构设计](docs/architecture/HOSTED_BS_GATEWAY_MVP.md)

## 贡献

欢迎贡献！请查看 [DEVELOPMENT.md](docs/developer/DEVELOPMENT.md) 了解开发规范。

## 许可证

本项目采用 MIT 许可证。详见 [LICENSE](LICENSE) 文件。

## 致谢

- [Model Context Protocol](https://modelcontextprotocol.io) - MCP 协议规范
- [AstrBot](https://github.com/Soulter/AstrBot) - QQ/Discord Bot 框架
- 所有贡献者和使用者

---

**Made with ❤️ by 云梦**
