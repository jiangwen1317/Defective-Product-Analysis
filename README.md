# Defective-Product-Analysis

缺陷品分析工具集，包含三个子项目：

| 目录 | 说明 |
|------|------|
| [`upper computer/`](upper%20computer/README.md) | PyQt5 上位机：机械臂/3720 测试仪网关与 UI |
| [`database-analysis/`](database-analysis/) | EMMC 日志解析、SQLite 存储与 RMA 报告 |
| [`Log-Download/`](Log-Download/README.md) | Playwright 日志下载自动化工具 |

## 克隆后初始化

推荐直接在仓库根执行一键初始化入口（封装下方步骤 1-5，可重复执行）：

```bat
setup.bat
```

若需手工分步执行，在仓库根依次执行以下步骤（`check.bat` 固定使用 `.venv\Scripts\python.exe`，虚拟环境必须建在仓库根且命名为 `.venv`）：

1. 创建虚拟环境（要求 Python ≥ 3.10，与根级 [pyproject.toml](pyproject.toml) 的 `target-version = "py310"` 一致）：

   ```bat
   python -m venv .venv
   ```

2. 安装仓库级开发/检查依赖：

   ```bat
   .venv\Scripts\python.exe -m pip install -r requirements-dev.txt
   ```

3. 依次安装三个子项目的运行依赖：

   ```bat
   .venv\Scripts\python.exe -m pip install -r "upper computer\requirements.txt"
   .venv\Scripts\python.exe -m pip install -r database-analysis\requirements.txt
   .venv\Scripts\python.exe -m pip install -r Log-Download\requirements.txt
   ```

4. 启用提交前门禁（**强制步骤**，pre-commit hook 调用 `check.bat`）：

   ```bat
   git config core.hooksPath githooks
   ```

   **警告：本步未执行时，本地 `git commit` 不会触发任何 pre-commit hook，
   提交完全无门禁**（ruff / 豁免基线 / pytest 均不会自动运行）。
   `check.bat` 开头会自检 `git config core.hooksPath` 是否为 `githooks`，
   未启用时直接以非零码失败并提示执行上述命令，因此本步必须先于第 5 步完成。

5. 运行检查入口验证环境：

   ```bat
   check.bat
   ```

## 开发约束与检查入口

- 项目权威约束（命名、类型注解、异常处理、测试等规范）见 [AGENTS.md](AGENTS.md)。
- 提交前必须在仓库根运行检查入口 [check.bat](check.bat)（hooksPath 自检 + ruff 静态检查 + 存量基线豁免只减不增断言 + 三个子项目 pytest 套件），失败则禁止提交。
