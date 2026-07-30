"""存量基线豁免『只减不增』机械断言。

统计 pyproject.toml 中 [tool.ruff.lint.per-file-ignores] 的存量基线豁免，
分两层断言：

1. 对数断言：按（文件, 规则码）对计数，与 BASELINE_PAIRS 比较：
   - 条目数增加：以非零码退出，禁止提交（AGENTS.md 十三：豁免只减不增）；
   - 条目数减少：同样以非零码退出，要求同步下调本文件中的 BASELINE_PAIRS
     常量并更新 pyproject.toml 豁免段的违规计数快照，消除双账漂移窗口；
   - 条目数相等：通过。
2. 处数断言：对每个豁免（文件, 规则码）对，用 ruff check --isolated 统计
   实际违规处数，与 BASELINE_VIOLATIONS 快照双向比对：
   - 超过快照：失败，禁止在豁免文件内新增同规则违规；
   - 低于快照：同样失败，要求同步下调快照（与对数断言一致，
     防止快照过期后违规悄悄回升）；
   - 与快照相等：通过。

由 check.bat 调用；也可在仓库根手动运行：
    .venv\\Scripts\\python.exe tools\\check_exemption_baseline.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

import tomllib

# 基线豁免对数：2026-07-29 引入检查时为 11 个（文件, 规则码）对（对应 29 处违规）。
# 收紧豁免（删除规则码或整行条目）后应同步下调该值。
BASELINE_PAIRS = 7

# 每个豁免（文件, 规则码）对的违规处数快照（ruff check --isolated 机械核对，
# 合计 21）。修复豁免文件内的违规后应同步下调对应条目，并更新
# pyproject.toml 豁免段的快照注释；降至 0 后应删除豁免条目并下调 BASELINE_PAIRS。
BASELINE_VIOLATIONS: dict[tuple[str, str], int] = {
    ("database-analysis/database.py", "ANN201"): 1,
    ("database-analysis/gui_app.py", "ANN001"): 11,
    ("database-analysis/gui_app.py", "PLR0915"): 1,
    ("database-analysis/log_parser.py", "PLR0915"): 2,
    ("upper computer/router/gateway.py", "ANN001"): 3,
    ("upper computer/router/gateway.py", "PLR0915"): 1,
    ("upper computer/ui/components.py", "ANN001"): 2,
}

# 策略性忽略（测试代码不受公开 API 注解约束），不计入存量基线豁免
POLICY_KEYS = frozenset({"**/tests/**", "**/conftest.py"})

PYPROJECT_PATH = Path(__file__).resolve().parent.parent / "pyproject.toml"
REPO_ROOT = PYPROJECT_PATH.parent


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


def count_violations(file: str, rules: list[str]) -> dict[str, int]:
    """用 ruff check --isolated 统计单个文件内指定规则的实际违规处数。

    Args:
        file: 相对仓库根的文件路径。
        rules: 需统计的规则码列表。

    Returns:
        规则码到违规处数的映射（无违规的规则码不出现在结果中）。

    Raises:
        RuntimeError: ruff 执行失败或输出无法解析时。
    """
    cmd = [
        sys.executable, "-m", "ruff", "check", "--isolated", "--exit-zero",
        "--select", ",".join(rules), "--output-format", "json", file,
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8",
        cwd=REPO_ROOT, check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"ruff 检查 {file} 失败（退出码 {result.returncode}）：{result.stderr}"
        )
    try:
        violations = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"ruff 对 {file} 的 JSON 输出无法解析") from e
    return dict(Counter(item["code"] for item in violations))


def check_pair_count(exemptions: dict[str, list[str]]) -> list[str]:
    """对数断言：（文件, 规则码）对数必须与 BASELINE_PAIRS 一致。

    Args:
        exemptions: 文件路径到豁免规则码列表的映射。

    Returns:
        错误信息列表，空列表表示通过。
    """
    current_pairs = sum(len(rules) for rules in exemptions.values())
    if current_pairs > BASELINE_PAIRS:
        lines = [
            f"存量基线豁免对数 {current_pairs} 超过基线 {BASELINE_PAIRS}，"
            f"豁免只减不增，禁止新增豁免条目。当前豁免条目："
        ]
        lines.extend(
            f"  {file} = {rules}" for file, rules in sorted(exemptions.items())
        )
        return ["\n".join(lines)]
    if current_pairs < BASELINE_PAIRS:
        return [
            f"存量基线豁免对数已降至 {current_pairs}（基线 {BASELINE_PAIRS}），"
            f"基线记录已过期。请同步下调 tools/check_exemption_baseline.py 中的 "
            f"BASELINE_PAIRS，并更新 pyproject.toml 豁免段的违规计数快照。"
        ]
    return []


def check_violation_counts(exemptions: dict[str, list[str]]) -> list[str]:
    """处数断言：每对的实际违规处数必须与 BASELINE_VIOLATIONS 快照一致。

    Args:
        exemptions: 文件路径到豁免规则码列表的映射。

    Returns:
        错误信息列表，空列表表示通过。
    """
    errors: list[str] = []
    current_keys: set[tuple[str, str]] = set()
    for file, rules in sorted(exemptions.items()):
        counts = count_violations(file, rules)
        for rule in rules:
            current_keys.add((file, rule))
            baseline = BASELINE_VIOLATIONS.get((file, rule))
            actual = counts.get(rule, 0)
            if baseline is None:
                errors.append(
                    f"豁免对 ({file}, {rule}) 未记录在 BASELINE_VIOLATIONS 快照中，"
                    f"豁免只减不增，禁止新增豁免条目。"
                )
            elif actual > baseline:
                errors.append(
                    f"({file}, {rule}) 实际违规 {actual} 处超过快照 {baseline} 处，"
                    f"禁止在豁免文件内新增同规则违规。"
                )
            elif actual < baseline:
                errors.append(
                    f"({file}, {rule}) 实际违规已降至 {actual} 处（快照 {baseline}），"
                    f"快照已过期。请同步下调 BASELINE_VIOLATIONS 对应条目，"
                    f"并更新 pyproject.toml 豁免段的快照注释。"
                )
    errors.extend(
        f"BASELINE_VIOLATIONS 中的 ({file}, {rule}) 已不在 pyproject.toml 豁免段，"
        f"快照已过期。请同步删除该条目。"
        for file, rule in sorted(set(BASELINE_VIOLATIONS) - current_keys)
    )
    return errors


def main() -> int:
    """执行基线断言，返回进程退出码。

    Returns:
        0 表示通过；1 表示豁免对数或违规处数与基线不一致（超过或低于）。
    """
    exemptions = load_exemptions(PYPROJECT_PATH)
    errors = check_pair_count(exemptions)
    errors.extend(check_violation_counts(exemptions))

    if errors:
        for error in errors:
            print(f"[FAIL] {error}")
        return 1

    current_pairs = sum(len(rules) for rules in exemptions.values())
    total = sum(BASELINE_VIOLATIONS.values())
    print(
        f"[OK] 存量基线豁免对数 {current_pairs} 与基线一致，"
        f"各对违规处数与快照一致（合计 {total}）。"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
