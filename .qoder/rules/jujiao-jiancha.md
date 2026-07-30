---
trigger: always_on
alwaysApply: true
---
# 修复/改动任务收尾聚焦检查规则

聚焦检查的权威定义为仓库根部 [AGENTS.md](../../AGENTS.md) 第十四节第 3 步，本规则只规定触发时机与留痕要求，不改变现有检查环节本身（check.bat、pre-commit hook 均保持不变）。

## 触发时机

任何修复/改动类任务（修改了仓库内 `.py` 文件或 `pyproject.toml`）在收尾前，必须机械执行以下聚焦检查，不得以"改动很小"或"已人工确认"为由跳过。

## 必须执行的命令

1. **ruff 聚焦检查**（所有代码改动必跑）：

   ```
   .venv\Scripts\python.exe -m ruff check <改动路径>
   ```

   `<改动路径>` 为本次任务实际修改的文件或目录列表。

2. **子项目 pytest**（涉及行为的改动加跑）：

   ```
   .venv\Scripts\python.exe -m pytest "<子项目>" -q
   ```

   `<子项目>` 为改动所属子项目根目录（`upper computer` / `database-analysis` / `Log-Download`）。仅注释、docstring、文档类改动可免跑 pytest，但需在收尾说明中声明。

## 留痕要求

- 检查命令必须在当前会话内实际执行，执行命令与结果输出必须保留在会话中可见，不得只口头声称"检查已通过"。
- 检查失败时，如实报告失败输出并按 AGENTS.md 第十四节停止规则处理；禁止通过添加 `# noqa` 或扩大豁免绕过。
