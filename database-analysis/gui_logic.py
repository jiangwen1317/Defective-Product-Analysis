"""
GUI 纯逻辑模块

从 gui_app.py 提取的与界面框架无关的纯函数，
不依赖 Tkinter/CustomTkinter，可独立单元测试。
"""
from typing import Optional

# 容量输入判定阈值：扇区数通常 > 1000000，MB 值通常 < 1000000
_CAPACITY_SECTOR_THRESHOLD = 1_000_000

# 图表类型中文名 → 绘图模式映射
_CHART_TYPE_MAP = {
    "折线图": "line",
    "柱状图": "bar",
    "散点图": "scatter",
    "阶梯图": "step",
    "面积图": "area",
}


def parse_record_ids(raw: str) -> list[int]:
    """解析逗号分隔的记录 ID 字符串（兼容中文逗号）。

    Args:
        raw: 用户输入的 ID 字符串，如 "8" 或 "8,9,10"。

    Returns:
        解析出的整数 ID 列表，非数字片段被忽略。
    """
    ids: list[int] = []
    for part in raw.replace("，", ",").split(","):
        part = part.strip()
        if part.isdigit():
            ids.append(int(part))
    return ids


def resolve_draw_mode(chart_type: str, has_indexed: bool, multi: bool) -> str:
    """确定实际绘图模式。

    Args:
        chart_type: 用户选择的图表类型（中文名或 "自动"）。
        has_indexed: 是否包含索引序列数据。
        multi: 是否为多记录对比。

    Returns:
        绘图模式标识（line/bar/scatter/step/area）。
    """
    if chart_type == "自动":
        if has_indexed and multi:
            return "line"
        return "bar"
    return _CHART_TYPE_MAP.get(chart_type, "line")


def parse_capacity_input(cap_str: str) -> tuple[Optional[int], Optional[int]]:
    """解析容量输入值（支持 MB 和扇区数两种格式）。

    Args:
        cap_str: 用户输入的容量字符串。

    Returns:
        (capacity_mb, capacity_sectors) 二元组，无效输入时均为 None。
    """
    capacity_mb: Optional[int] = None
    capacity_sectors: Optional[int] = None
    cap_str = cap_str.strip()
    if cap_str:
        try:
            cap_val = int(cap_str)
            if cap_val > _CAPACITY_SECTOR_THRESHOLD:
                capacity_sectors = cap_val
            else:
                capacity_mb = cap_val
        except ValueError:
            pass
    return capacity_mb, capacity_sectors


def format_capacity_display(summary: dict) -> str:
    """格式化容量显示文本：优先 MB，其次扇区。

    Args:
        summary: 主表摘要记录（含 capacity_mb / capacity_sectors 字段）。

    Returns:
        显示文本，如 "59680 MB" 或 "125042688 Sec"，无数据时为空串。
    """
    if summary.get("capacity_mb"):
        return f"{summary['capacity_mb']} MB"
    if summary.get("capacity_sectors"):
        return f"{summary['capacity_sectors']} Sec"
    return ""
