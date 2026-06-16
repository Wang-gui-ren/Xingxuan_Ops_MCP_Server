# 登录系统整合测试指南

## 概述
已将全局登录系统整合到审批台启动流程中。当 LLM 通过 `/approvals` 口令启动审批台时，会自动检查登录状态并引导用户登录。

## 修改的文件

### 1. `src/mcp_ops_server/web/gateway.py`
**新增 API 端点：** `GET /api/auth/sessions`
- 返回当前已登录的审批人列表
- 用于检查登录状态
- 响应格式：
  ```json
  {
    "ok": true,
    "schema_version": "hosted-bs-gateway-v1",
    "data": {
      "approvers": ["username1", "username2"]
    }
  }
  ```

**新增方法：** `_get_active_approvers()`
- 从 `user_config` 获取所有注册用户列表
- 返回用户名数组

### 2. `src/mcp_ops_server/tool_groups/gateway_tools.py`
**修改工具：** `open_approval_console_tool`
- 新增登录状态检查逻辑
- 在返回审批台 URL 前，先调用 `/api/auth/sessions` 检查是否有已登录用户
- 根据登录状态返回不同的 URL 和提示信息

**新增函数：** `_check_login_status()`
- 调用网关的 `/api/auth/sessions` API
- 检查是否有已登录的审批人
- 返回登录状态、审批人列表、登录 URL 和提示信息

**新增函数：** `_next_actions_with_login()`
- 根据登录状态生成不同的操作建议
- 未登录时引导用户先访问登录页
- 已登录时直接显示审批台 URL

## 工作流程

### 场景 1：无用户登录（首次使用）
1. LLM 调用 `open_approval_console_tool`
2. 工具启动网关，获取审批台 URL：`http://127.0.0.1:8765/approvals`
3. 工具调用 `/api/auth/sessions` 检查登录状态
4. 返回结果显示：**无已登录用户**
5. 工具返回登录页 URL：`http://127.0.0.1:8765/login`
6. **LLM 提示用户：**
   ```
   审批台已就绪，请先在浏览器打开并登录：
   http://127.0.0.1:8765/login
   
   登录后，审批台将自动可用。
   ```
7. **用户操作：** 访问登录页 → 注册/登录
8. **用户再次调用 `/approvals`** → 直接进入审批台

### 场景 2：已有用户登录
1. LLM 调用 `open_approval_console_tool`
2. 工具启动网关，获取审批台 URL
3. 工具调用 `/api/auth/sessions` 检查登录状态
4. 返回结果显示：**已有登录用户（例如：alice）**
5. **LLM 提示用户：**
   ```
   审批台已就绪，请在浏览器打开：
   http://127.0.0.1:8765/approvals
   
   当前已登录审批人：alice
   ```
6. **用户操作：** 直接访问审批台 → 自动识别身份

## 测试步骤

### 步骤 1：清理环境
```bash
# 删除用户配置文件（如果存在）
rm -f tmp_MCP/config/users.yaml
```

### 步骤 2：启动网关
```bash
cd tmp_MCP
python3 -m mcp_ops_server.web.gateway_launcher
```

或通过 LLM 口令启动：
```
/approvals
```

### 步骤 3：测试无登录状态
**预期 LLM 响应：**
```
审批台已就绪，请先在浏览器打开并登录：
http://127.0.0.1:8765/login

登录后，审批台将自动可用。
```

**用户操作：**
1. 在浏览器打开：`http://127.0.0.1:8765/login`
2. 看到登录页（Semi Design 风格）
3. 点击"注册"链接
4. 输入用户名和密码（例如：alice / password123）
5. 点击"注册"按钮
6. 自动登录并跳转到审批台

### 步骤 4：测试已登录状态
**再次通过 LLM 调用：**
```
/approvals
```

**预期 LLM 响应：**
```
审批台已就绪，请在浏览器打开：
http://127.0.0.1:8765/approvals

当前已登录审批人：alice
```

### 步骤 5：验证自动填充身份
1. 在浏览器打开审批台
2. 检查顶部右侧是否显示用户 chip：`alice ×`
3. 检查审批人输入框是否自动填充为：`alice`
4. 点击用户 chip 的 `×` 按钮
5. 验证是否跳转回登录页

## API 端点总览

### 新增端点
| 方法 | 路径 | 说明 | 需要登录 |
|------|------|------|---------|
| GET | `/api/auth/sessions` | 获取已登录审批人列表 | 否 |

### 已有端点（登录系统）
| 方法 | 路径 | 说明 | 需要登录 |
|------|------|------|---------|
| GET | `/login` | 登录页 | 否 |
| GET | `/register` | 注册页 | 否 |
| POST | `/api/auth/login` | 登录 API | 否 |
| POST | `/api/auth/register` | 注册 API | 否 |
| GET | `/approvals` | 审批台 | **是** |
| GET | `/config-admin` | 配置管理台 | **是** |

## 数据流图

```
LLM 口令 "/approvals"
    ↓
open_approval_console_tool
    ↓
启动/复用网关
    ↓
调用 GET /api/auth/sessions
    ↓
检查 users.yaml 中的用户
    ↓
┌─────────────────────────────┬──────────────────────────────┐
│ 无用户 / users.yaml 不存在    │ 有已登录用户                  │
├─────────────────────────────┼──────────────────────────────┤
│ 返回：                        │ 返回：                        │
│ - login_url                  │ - approvals_url              │
│ - login_required: true       │ - approvers: ["alice"]       │
│                              │ - login_required: false      │
├─────────────────────────────┼──────────────────────────────┤
│ LLM 提示：                    │ LLM 提示：                    │
│ "请先登录：                   │ "审批台已就绪：               │
│  http://...login"            │  http://...approvals"        │
│                              │ "当前已登录：alice"           │
└─────────────────────────────┴──────────────────────────────┘
```

## 技术细节

### 登录状态判断逻辑
目前的实现是：**检查 users.yaml 中是否有注册用户**。

这是简化的逻辑，因为：
1. 系统没有实现 session 持久化存储
2. 用户的 session 存储在前端 localStorage 中
3. 后端只能通过 users.yaml 判断是否有用户存在

**改进方向（可选）：**
- 在后端维护活跃 session 列表（内存或 Redis）
- 记录最后登录时间，判断 session 是否过期
- 但当前简化方案对于本地开发环境已经足够

### 安全考虑
- `/api/auth/sessions` 端点**不需要认证**，因为它只返回用户名列表，不包含敏感信息
- 实际的审批操作仍需要有效的 session token
- `/approvals` 和 `/config-admin` 路由仍有登录保护

## 错误处理

### 网关未启动
- `_check_login_status()` 捕获网络异常
- 返回 `has_approvers: false`
- 引导用户登录（登录页会触发网关启动）

### users.yaml 不存在
- `_get_active_approvers()` 捕获异常
- 返回空列表 `[]`
- LLM 引导用户注册

### 端点不可达
- 超时 3 秒后返回空列表
- 系统优雅降级，假设无登录用户

## 总结

✅ **已完成的整合：**
1. 网关添加 `/api/auth/sessions` API
2. `open_approval_console_tool` 检查登录状态
3. LLM 根据登录状态引导用户操作
4. 首次使用自动引导到登录页
5. 已登录用户直接显示审批台 URL

✅ **用户体验改进：**
- **Before:** LLM 直接返回审批台 URL → 用户访问 → 被重定向到登录页（困惑）
- **After:** LLM 先检查登录状态 → 未登录时直接引导到登录页 → 清晰明确

✅ **无需手动配置：**
- 用户不需要手动输入 token 和 approver
- 登录后身份自动识别和填充
- 真正实现"全局登录"体验
