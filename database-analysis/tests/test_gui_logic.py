"""
gui_logic 模块单元测试

覆盖从 gui_app.py 提取的纯逻辑函数：
ID 解析、绘图模式判定、容量输入解析和容量显示格式化。
"""
import pytest
from gui_logic import (
    format_capacity_display,
    parse_capacity_input,
    parse_record_ids,
    resolve_draw_mode,
)


class TestParseRecordIds:
    """测试逗号分隔 ID 字符串解析。"""

    def test_single_id(self):
        assert parse_record_ids("8") == [8]

    def test_multiple_ids(self):
        assert parse_record_ids("8,9,10") == [8, 9, 10]

    def test_chinese_comma(self):
        assert parse_record_ids("8，9，10") == [8, 9, 10]

    def test_whitespace_tolerance(self):
        assert parse_record_ids(" 8 , 9 ") == [8, 9]

    def test_invalid_parts_ignored(self):
        assert parse_record_ids("8,abc,-3,9.5,10") == [8, 10]

    def test_empty_string(self):
        assert parse_record_ids("") == []


class TestResolveDrawMode:
    """测试绘图模式判定。"""

    def test_auto_indexed_multi_returns_line(self):
        assert resolve_draw_mode("自动", has_indexed=True, multi=True) == "line"

    def test_auto_indexed_single_returns_bar(self):
        assert resolve_draw_mode("自动", has_indexed=True, multi=False) == "bar"

    def test_auto_scalar_returns_bar(self):
        assert resolve_draw_mode("自动", has_indexed=False, multi=True) == "bar"

    @pytest.mark.parametrize("chart_type,expected", [
        ("折线图", "line"),
        ("柱状图", "bar"),
        ("散点图", "scatter"),
        ("阶梯图", "step"),
        ("面积图", "area"),
    ])
    def test_explicit_type_mapping(self, chart_type, expected):
        assert resolve_draw_mode(chart_type, has_indexed=True, multi=False) == expected

    def test_unknown_type_falls_back_to_line(self):
        assert resolve_draw_mode("未知类型", has_indexed=False, multi=False) == "line"


class TestParseCapacityInput:
    """测试容量输入解析（MB 与扇区数自动区分）。"""

    def test_mb_value(self):
        assert parse_capacity_input("59680") == (59680, None)

    def test_sector_value(self):
        assert parse_capacity_input("125042688") == (None, 125042688)

    def test_threshold_boundary(self):
        """恰好 1000000 视为 MB，超过视为扇区。"""
        assert parse_capacity_input("1000000") == (1000000, None)
        assert parse_capacity_input("1000001") == (None, 1000001)

    def test_empty_string(self):
        assert parse_capacity_input("") == (None, None)

    def test_whitespace_only(self):
        assert parse_capacity_input("   ") == (None, None)

    def test_non_numeric(self):
        assert parse_capacity_input("abc") == (None, None)


class TestFormatCapacityDisplay:
    """测试容量显示格式化。"""

    def test_mb_preferred(self):
        summary = {"capacity_mb": 59680, "capacity_sectors": 125042688}
        assert format_capacity_display(summary) == "59680 MB"

    def test_sectors_fallback(self):
        summary = {"capacity_mb": None, "capacity_sectors": 125042688}
        assert format_capacity_display(summary) == "125042688 Sec"

    def test_no_capacity(self):
        assert format_capacity_display({}) == ""

    def test_zero_values_treated_as_empty(self):
        """0 值视为无数据（与原 truthy 判断行为一致）。"""
        summary = {"capacity_mb": 0, "capacity_sectors": 0}
        assert format_capacity_display(summary) == ""
