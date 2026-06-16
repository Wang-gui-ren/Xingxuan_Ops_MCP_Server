# 开发说明

## 开发目标

`星璇运维MCP` 的开发原则很明确：

- 不暴露任意 shell 作为常规对外接口
- 先做结构化动作模板，再做执行
- 所有高风险写操作都走护栏、审批、审计
- B/S 界面只作为受控入口，不绕过后端策略

## 代码结构

- `src/mcp_ops_server/branding.py`
  品牌常量、兼容命名和环境变量别名解析。
- `src/mcp_ops_server/config/`
  审批身份配置、网关配置与兼容读取。
- `src/mcp_ops_server/approvals/`
  审批账本、审批锚点、审批身份 token 校验。
- `src/mcp_ops_server/audit/`
  审计日志、查询索引、轮转、锚点和同步。
- `src/mcp_ops_server/execution/`
  固定动作模板、执行策略、执行代理预检。
- `src/mcp_ops_server/web/`
  审批台、配置台、网关设置页和托管网关。
- `src/mcp_ops_server/tool_groups/`
  MCP 工具注册分组。

## 品牌与命名规则

### 正式命名

- 中文品牌：`星璇运维MCP`
- 英文技术名：`xingxuan-mcp`
- Python 包：`mcp_ops_server`

### 新旧兼容

开发时统一遵循：

```text
新接口写入：只产出 XINGXUAN_MCP_* / xingxuan-mcp / 星璇运维MCP
兼容读取：接受 TMP_MCP_* / tmp-mcp-* / tmp_mcp_*
```

### 不要再改的东西

- 不要把仓库物理目录改成别的名字
- 不要重命名 `mcp_ops_server`
- 不要删除 legacy 兼容读取逻辑，除非后续专门做二阶段清理

## 前端约定

### 页面名称

- `星璇运维MCP 审批台`
- `星璇运维MCP 配置管理`
- `星璇运维MCP Gateway Settings`

### 前端存储与请求

- locale 主键：`xingxuan_mcp_ui_locale`
- locale 兼容读取：`tmp_mcp_ui_locale`
- 写请求头主名：`X-XINGXUAN-MCP-Admin-Token`
- 后端兼容旧请求头：`X-TMP-MCP-Admin-Token`

## 打包与部署样例

新的样例文件：

- `packaging/systemd/xingxuan-mcp-ops.service`
- `packaging/sudoers/xingxuan-mcp-ops-agent`

新的控制台入口：

- `xingxuan-mcp-ops-server`
- `xingxuan-mcp-web-gateway`

## 本地验证建议

常用验证命令：

```powershell
python -m compileall -q src\mcp_ops_server scripts
python .\scripts\verify_web_gateway.py
python .\scripts\verify_approval_console.py
python .\scripts\verify_approval_identity_config.py
python .\scripts\verify_astrbot_ops_bridge_install.py
```

建议至少做三类检查：

- 搜索残留旧品牌，只允许出现在兼容层或迁移说明
- 用新前缀环境变量跑一遍主流程
- 用旧前缀环境变量做一遍兼容性抽查

## 品牌迁移与兼容说明

### 统一入口

如果新增配置读取，请不要直接写：

```python
os.environ.get("TMP_MCP_SOMETHING")
```

应该走 `branding.py` 提供的兼容读取辅助函数，保证：

- 新变量优先
- 旧变量可回退
- source_map 可追踪真实来源

### 需要保留 legacy 的场景

- 旧环境变量
- 旧请求头
- 旧 cookie
- 旧插件 ID
- 旧 CLI 名称

### 可以直接切新的场景

- 页面标题
- 按钮文案
- README / docs 主文档
- 安装脚本默认值
- 样例 service / sudoers 文件名
