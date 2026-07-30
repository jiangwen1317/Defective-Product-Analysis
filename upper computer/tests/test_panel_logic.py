"""ui.panel_logic 纯逻辑单元测试。

从 main_window.py 界面构建函数中提取的纯函数，可脱离 QApplication 独立验证。
"""

from ui.panel_logic import (
    CHECKBOX_FIRST_ROW_CAPACITY,
    format_board_config_desc,
    split_checkbox_rows,
)


class TestFormatBoardConfigDesc:
    """format_board_config_desc 的描述文本生成测试。"""

    def test_positive_count_returns_configured_desc(self):
        """数量为正时返回已配置板子数量描述。"""
        assert format_board_config_desc(3) == "已配置 3 个板子"

    def test_single_board(self):
        """单板配置的描述文本。"""
        assert format_board_config_desc(1) == "已配置 1 个板子"

    def test_zero_count_returns_config_hint(self):
        """数量为 0 时返回配置引导提示。"""
        assert format_board_config_desc(0) == "请在 config.json 中配置 DUT"


class TestSplitCheckboxRows:
    """split_checkbox_rows 的两行拆分测试。"""

    def test_empty_indices_returns_two_empty_rows(self):
        """空序列拆分为两行空列表。"""
        assert split_checkbox_rows([]) == ([], [])

    def test_within_capacity_all_in_first_row(self):
        """不超过首行容量时全部落在首行。"""
        first, second = split_checkbox_rows([1, 2, 3])
        assert first == [1, 2, 3]
        assert second == []

    def test_exact_capacity_second_row_empty(self):
        """恰好等于首行容量时次行为空。"""
        indices = list(range(1, CHECKBOX_FIRST_ROW_CAPACITY + 1))
        first, second = split_checkbox_rows(indices)
        assert first == indices
        assert second == []

    def test_over_capacity_overflow_to_second_row(self):
        """超过首行容量的部分按原顺序折行到次行。"""
        first, second = split_checkbox_rows([1, 2, 3, 4, 5, 6, 7, 8])
        assert first == [1, 2, 3, 4]
        assert second == [5, 6, 7, 8]

    def test_preserves_original_order(self):
        """非连续序号保持传入顺序不被排序。"""
        first, second = split_checkbox_rows([8, 3, 5, 1, 7])
        assert first == [8, 3, 5, 1]
        assert second == [7]
