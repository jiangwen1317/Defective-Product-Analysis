"""存量基线豁免『只减不增』机械断言。

统计 pyproject.toml 中 [tool.ruff.lint.per-file-ignores] 的存量基线豁免，
按（文件, 规则码）对计数，与记录的基线数比较：

- 条目数增加：以非零码退出，禁止提交（AGENTS.md 十三：豁免只减不增）；
- 条目数减少：同样以非零码退出，要求同步下调本文件中的 BASELINE_PAIRS 常量
  并更新 pyproject.toml 豁免段的违规计数快照，消除双账漂移窗口；
- 条目数相等：通过。

由 check.bat 调用；也可在仓库根手动运行：
    .venv\\Scripts\\python.exe tools\\check_exemption_baseline.py
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

# 基线豁免对数：2026-07-29 引入检查时的 29 处违规，对应 11 个（文件, 规则码）对。
# 收紧豁免（删除规则码或整行条目）后应同步下调该值。
BASELINE_PAIRS = 11

# 策略性忽略（测试代码不受公开 API 注解约束），不计入存量基线豁免
POLICY_KEYS = frozenset({"**/tests/**", "**/conftest.py"})

PYPROJECT_PATH = Path(__file__).resolve().parent.parent / "pyproject.toml"


def load_exemptions(pyproject_path: Path) -> dict[str, list[str]]:
    """读取 per-file-ignores 中的存量基线豁免条目。

    Args:
        pyproject_path: 仓库根 pyproject.toml 的路径。

    Returns:
        文件路径到豁免规则码列表的映射（已剔除策略性忽略条目）。

    Raises:
        ValueError: pyproject.toml 缺少 per-file-ignores 配置段时。
    """
    with pyproject_path.open("rb") as fp:
        data = tomllib.load(fp)
    try:
        ignores = data["tool"]["ruff"]["lint"]["per-file-ignores"]
    except KeyError as e:
        raise ValueError(
            f"{pyproject_path} 缺少 [tool.ruff.lint.per-file-ignores] 配置段"
        ) from e
    return {
        file: list(rules)
        for file, rules in ignores.items()
        if file not in POLICY_KEYS
    }


def main() -> int:
    """执行基线断言，返回进程退出码。

    Returns:
        0 表示通过；1 表示豁免条目数与基线不一致（超过或低于）。
    """
    exemptions = load_exemptions(PYPROJECT_PATH)
    current_pairs = sum(len(rules) for rules in exemptions.values())

    if current_pairs > BASELINE_PAIRS:
        print(
            f"[FAIL] 存量基线豁免对数 {current_pairs} 超过基线 {BASELINE_PAIRS}，"
            f"豁免只减不增，禁止新增豁免条目。"
        )
        print("当前豁免条目：")
        for file, rules in sorted(exemptions.items()):
            print(f"  {file} = {rules}")
        return 1

    if current_pairs < BASELINE_PAIRS:
        print(
            f"[FAIL] 存量基线豁免对数已降至 {current_pairs}（基线 {BASELINE_PAIRS}），"
            f"基线记录已过期。请同步下调 tools/check_exemption_baseline.py 中的 "
            f"BASELINE_PAIRS，并更新 pyproject.toml 豁免段的违规计数快照。"
        )
        return 1

    print(f"[OK] 存量基线豁免对数 {current_pairs} 与基线一致。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
