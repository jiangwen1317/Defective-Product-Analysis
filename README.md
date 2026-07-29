# Defective-Product-Analysis

缺陷品分析工具集，包含三个子项目：

| 目录 | 说明 |
|------|------|
| [`upper computer/`](upper%20computer/README.md) | PyQt5 上位机：机械臂/3720 测试仪网关与 UI |
| [`database-analysis/`](database-analysis/) | EMMC 日志解析、SQLite 存储与 RMA 报告 |
| [`Log-Download/`](Log-Download/README.md) | Playwright 日志下载自动化工具 |

## 开发约束与检查入口

- 项目权威约束（命名、类型注解、异常处理、测试等规范）见 [AGENTS.md](AGENTS.md)。
- 提交前必须在仓库根运行检查入口 [check.bat](check.bat)（ruff 静态检查 + 三个子项目 pytest 套件），失败则禁止提交。
