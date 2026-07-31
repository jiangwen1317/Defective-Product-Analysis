"""tools/check_exemption_baseline.py 的回归测试。

覆盖门禁脚本的四个纯逻辑函数与一个 subprocess 封装：

- load_exemptions：正常读取、剔除策略性忽略、缺少配置段抛 ValueError；
- check_pair_count：对数超过 / 低于 / 相等三分支；
- check_violation_counts：未记录 / 超过 / 低于 / 过期条目四分支；
- count_violations：用 unittest.mock 模拟 ruff 的 subprocess 输出，
  不依赖真实 ruff。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest import mock

import check_exemption_baseline as cb
import pytest


def _write_pyproject(tmp_path: Path, body: str) -> Path:
    """在临时目录写入 pyproject.toml 并返回其路径。

    Args:
        tmp_path: pytest 提供的临时目录。
        body: 要写入的 TOML 文本。

    Returns:
        写入后的 pyproject.toml 路径。
    """
    path = tmp_path / "pyproject.toml"
    path.write_text(body, encoding="utf-8")
    return path


class TestLoadExemptions:
    """load_exemptions 的读取与校验行为。"""

    def test_returns_exemptions_excluding_policy_keys(self, tmp_path: Path) -> None:
        """剔除策略性忽略条目后返回存量基线豁免映射。"""
        path = _write_pyproject(
            tmp_path,
            "[tool.ruff.lint.per-file-ignores]\n"
            '"**/tests/**" = ["ANN"]\n'
            '"**/conftest.py" = ["ANN"]\n'
            '"pkg/mod.py" = ["ANN201", "PLR0915"]\n',
        )

        result = cb.load_exemptions(path)

        assert result == {"pkg/mod.py": ["ANN201", "PLR0915"]}

    def test_missing_section_raises_value_error(self, tmp_path: Path) -> None:
        """缺少 per-file-ignores 配置段时抛出 ValueError。"""
        path = _write_pyproject(tmp_path, "[tool.ruff]\ntarget-version = \"py310\"\n")

        with pytest.raises(ValueError, match="per-file-ignores"):
            cb.load_exemptions(path)


class TestCheckPairCount:
    """check_pair_count 的对数断言三分支。"""

    def test_exceeds_baseline_reports_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """对数超过基线时返回错误信息。"""
        monkeypatch.setattr(cb, "BASELINE_PAIRS", 1)

        errors = cb.check_pair_count({"a.py": ["ANN201", "PLR0915"]})

        assert len(errors) == 1
        assert "超过基线" in errors[0]

    def test_below_baseline_reports_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """对数低于基线时返回过期提示错误。"""
        monkeypatch.setattr(cb, "BASELINE_PAIRS", 3)

        errors = cb.check_pair_count({"a.py": ["ANN201"]})

        assert len(errors) == 1
        assert "基线记录已过期" in errors[0]

    def test_equal_baseline_passes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """对数与基线相等时通过，无错误。"""
        monkeypatch.setattr(cb, "BASELINE_PAIRS", 2)

        errors = cb.check_pair_count({"a.py": ["ANN201", "PLR0915"]})

        assert errors == []


class TestCheckViolationCounts:
    """check_violation_counts 的处数断言四分支。"""

    def test_unrecorded_pair_reports_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """豁免对未记录在快照中时返回错误。"""
        monkeypatch.setattr(cb, "BASELINE_VIOLATIONS", {})
        monkeypatch.setattr(cb, "count_violations", lambda file, rules: {"ANN201": 1})

        errors = cb.check_violation_counts({"a.py": ["ANN201"]})

        assert len(errors) == 1
        assert "未记录在 BASELINE_VIOLATIONS" in errors[0]

    def test_actual_exceeds_snapshot_reports_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """实际违规处数超过快照时返回错误。"""
        monkeypatch.setattr(cb, "BASELINE_VIOLATIONS", {("a.py", "ANN201"): 1})
        monkeypatch.setattr(cb, "count_violations", lambda file, rules: {"ANN201": 3})

        errors = cb.check_violation_counts({"a.py": ["ANN201"]})

        assert len(errors) == 1
        assert "超过快照" in errors[0]

    def test_actual_below_snapshot_reports_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """实际违规处数低于快照时返回过期提示错误。"""
        monkeypatch.setattr(cb, "BASELINE_VIOLATIONS", {("a.py", "ANN201"): 3})
        monkeypatch.setattr(cb, "count_violations", lambda file, rules: {"ANN201": 1})

        errors = cb.check_violation_counts({"a.py": ["ANN201"]})

        assert len(errors) == 1
        assert "快照已过期" in errors[0]

    def test_stale_snapshot_entry_reports_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """快照中存在已不在豁免段的过期条目时返回错误。"""
        monkeypatch.setattr(
            cb,
            "BASELINE_VIOLATIONS",
            {("a.py", "ANN201"): 1, ("gone.py", "PLR0915"): 2},
        )
        monkeypatch.setattr(cb, "count_violations", lambda file, rules: {"ANN201": 1})

        errors = cb.check_violation_counts({"a.py": ["ANN201"]})

        assert len(errors) == 1
        assert "已不在 pyproject.toml 豁免段" in errors[0]
        assert "gone.py" in errors[0]

    def test_all_match_snapshot_passes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """所有豁免对与快照一致时通过，无错误。"""
        monkeypatch.setattr(cb, "BASELINE_VIOLATIONS", {("a.py", "ANN201"): 2})
        monkeypatch.setattr(cb, "count_violations", lambda file, rules: {"ANN201": 2})

        errors = cb.check_violation_counts({"a.py": ["ANN201"]})

        assert errors == []


class TestCountViolations:
    """count_violations 的 subprocess 封装（模拟 ruff 输出）。"""

    def test_parses_json_output_into_counts(self) -> None:
        """将 ruff 的 JSON 输出聚合为规则码到处数的映射。"""
        stdout = json.dumps(
            [{"code": "ANN201"}, {"code": "ANN201"}, {"code": "PLR0915"}]
        )
        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=stdout, stderr=""
        )

        with mock.patch.object(cb.subprocess, "run", return_value=completed) as run:
            result = cb.count_violations("a.py", ["ANN201", "PLR0915"])

        assert result == {"ANN201": 2, "PLR0915": 1}
        run.assert_called_once()

    def test_nonzero_return_code_raises_runtime_error(self) -> None:
        """ruff 以非零码退出时抛出 RuntimeError。"""
        completed = subprocess.CompletedProcess(
            args=[], returncode=2, stdout="", stderr="boom"
        )

        with mock.patch.object(cb.subprocess, "run", return_value=completed):
            with pytest.raises(RuntimeError, match="失败"):
                cb.count_violations("a.py", ["ANN201"])

    def test_invalid_json_raises_runtime_error(self) -> None:
        """ruff 输出无法解析为 JSON 时抛出 RuntimeError。"""
        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="not-json", stderr=""
        )

        with mock.patch.object(cb.subprocess, "run", return_value=completed):
            with pytest.raises(RuntimeError, match="无法解析"):
                cb.count_violations("a.py", ["ANN201"])
