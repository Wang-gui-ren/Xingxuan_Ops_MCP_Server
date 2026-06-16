# 文档总览

本目录已经按 `星璇运维MCP` 品牌统一整理。阅读建议如下：

## 面向使用者

- [user/USAGE.md](user/USAGE.md)
  日常使用、审批台/配置台/网关设置页、环境变量和兼容迁移说明。
- [deployment/README.md](deployment/README.md)
  部署样例、systemd、sudoers、Kylin 参考入口。
- [testing/MCP_OPERATION_VERIFICATION.md](testing/MCP_OPERATION_VERIFICATION.md)
  验收矩阵、品牌迁移检查点和关键 smoke/verify 脚本。

## 面向开发者

- [developer/DEVELOPMENT.md](developer/DEVELOPMENT.md)
  代码结构、命名规则、兼容策略和本地验证建议。
- [history/CHANGELOG.md](history/CHANGELOG.md)
  版本与品牌迁移记录。

## 历史与专题资料

- `architecture/`
  历史设计稿、预研记录和架构拆解。
- `overview/`
  较完整的项目规格与开发背景说明。
- `reports/`
  汇报、竞赛和展示材料。
- `planning/`
  里程碑和 TODO。
- `references/`
  参考资料。

## 品牌迁移提示

当前文档体系遵循以下规则：

- 正式名称统一使用 `星璇运维MCP`
- 英文技术名统一使用 `xingxuan-mcp`
- 新环境变量统一使用 `XINGXUAN_MCP_*`
- 历史名只保留在兼容说明、迁移映射和必要 legacy 注释中
- 物理目录 `tmp_mcp` 与 Python 包 `mcp_ops_server` 保持不变
