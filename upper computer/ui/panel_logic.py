"""主窗口面板的纯逻辑单元。

从 main_window.py 的界面构建函数中提取的、不依赖 Qt 的纯函数，
可脱离 QApplication 独立单测。
"""

from __future__ import annotations

from collections.abc import Sequence

# 复选框首行最多容纳的板子数量（超出部分折行到第二行）
CHECKBOX_FIRST_ROW_CAPACITY = 4


def format_board_config_desc(dut_count: int) -> str:
    """生成测试控制卡片的板子配置描述文本。

    Args:
        dut_count: 已配置的 DUT 数量。

    Returns:
        已配置板子的描述文本；数量为 0 时返回配置引导提示。
    """
    if dut_count > 0:
        return f"已配置 {dut_count} 个板子"
    return "请在 config.json 中配置 DUT"


def split_checkbox_rows(
    dut_indices: Sequence[int],
) -> tuple[list[int], list[int]]:
    """将 DUT 序号按首行容量拆分为两行复选框布局。

    Args:
        dut_indices: 已配置的 DUT 序号序列（保持原有顺序）。

    Returns:
        (首行序号列表, 次行序号列表)，首行最多
        CHECKBOX_FIRST_ROW_CAPACITY 个。
    """
    first_row = list(dut_indices[:CHECKBOX_FIRST_ROW_CAPACITY])
    second_row = list(dut_indices[CHECKBOX_FIRST_ROW_CAPACITY:])
    return first_row, second_row
