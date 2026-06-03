"""
EMMC RTMS 测试日志解析引擎

将半结构化的 RTMS 日志文件解析为结构化的 ParseResult 对象。
包含 Section 分块、KV 提取、数值转换、Hex Dump 跳过等完整解析流程。

错误隔离原则：单文件/单Section/单KV 解析失败不中断整体流程。
"""
import os
import re
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


# ============================================================
# 数据结构
# ============================================================

@dataclass
class MetricEntry:
    """单个 KV 指标。"""

    section: str            # 所属 Section（如 "Wear_Detection"）
    key_raw: str            # 原始键名（如 "[SLC] WearGap"）
    key: str                # 清洗后键名（如 "WearGap"）
    raw_value: str          # 原始值字符串
    num_value: Optional[float] = None  # 数值（无法转换时为 None）
    value_type: str = "string"         # hex/decimal/float/string
    prefix: Optional[str] = None       # "SLC"/"TLC"/None
    array_index: Optional[str] = None  # "64"/"8"/None

    def as_tuple(self) -> tuple:
        """转为数据库插入元组。"""
        return (
            self.section, self.key, self.key_raw, self.raw_value,
            self.num_value, self.value_type, self.prefix, self.array_index,
        )


@dataclass
class ParseResult:
    """单个文件的解析结果。"""

    file_name: str
    file_path: str
    file_size: int
    file_mtime: float
    # 顶层元数据
    device_name: Optional[str] = None
    device_tool_name: Optional[str] = None
    device_config_name: Optional[str] = None
    # Start of test 关键字段
    fw_version: Optional[str] = None
    mp_tool_version: Optional[str] = None
    flash_id: Optional[str] = None
    original_bad_block: Optional[int] = None
    # Cycles
    cycles: int = 0
    # 所有指标
    metrics: list[MetricEntry] = field(default_factory=list)
    # 汇总
    overall_result: str = "Unknown"
    fail_sections: list[str] = field(default_factory=list)
    # Wear 关键指标
    wai: Optional[float] = None
    slc_pe_min: Optional[int] = None
    slc_pe_max: Optional[int] = None
    tlc_pe_min: Optional[int] = None
    tlc_pe_max: Optional[int] = None
    increase_bad_block: Optional[int] = None
    # 解析状态
    status: str = "Success"
    error: Optional[str] = None


# ============================================================
# 正则模式常量
# ============================================================

# Section Header：顶格、非缩进、冒号结尾
# 匹配 "Start of test:", "End of test:", "Wear_Detection:", "GM/BIT_comparison_garbage:" 等
_RE_SECTION_HEADER = re.compile(r'^([A-Za-z][\w/]*(?:\s+of\s+\w+)?(?:_[\w]+)*)\s*:\s*$')

# 顶层 KV：无缩进，Key 用空格 padding 对齐，冒号分隔
# "Device_Name              :DM3720.012.13"
_RE_TOP_KV = re.compile(r'^([A-Za-z_]\w*)\s+:(.*)$')

# 紧凑顶层 KV：无空格填充
# "Cycles:0"
_RE_COMPACT_KV = re.compile(r'^([A-Za-z_]\w+):(.+)$')

# 缩进 KV：4 空格缩进
# "    wPdmPostCnt            :0x0001"
# "    dwFreeTimeCollectFailCnt:0x00000000"（key与冒号间无空格）
# 键名仅允许编程标识符字符（\w/[]/()）和可选前缀 [XXX]，禁止任意空格
_RE_INDENT_KV = re.compile(r'^    (?:\[([A-Z]+)\] )?([\w\[\]\(\)]+?)\s*:(.*)$')

# Tab 缩进的 Result
# "\tResult                 :Pass!"
_RE_TAB_RESULT = re.compile(r'^\t(Result)\s*:(.*)$')

# 带前缀的键名：[SLC] WearGap
_RE_PREFIX = re.compile(r'^\[([A-Z]+)\]\s*(.+)$')

# 带数组下标的键名：bFWVersion[64]
_RE_ARRAY = re.compile(r'^(.+?)\[(\d+)\]$')

# Hex Dump 数据行：...DDD:  XX XX XX ...
_RE_HEX_DUMP_LINE = re.compile(r'^\s*\.\.\.\d+:\s+[\dA-Fa-f\s]+$')

# Hex Dump Offset 表头行
_RE_HEX_OFFSET_HEADER = re.compile(r'^\s*Offset:')

# 混合叙述行（非标准，不以已知格式开头）
# "    A GMZone contains multiple blocks in the MB table, GMZone:0x0"
_RE_NARRATIVE_LINE = re.compile(r'^    [A-Z][a-z]')


# ============================================================
# 数值转换
# ============================================================

def convert_value(raw_value: str) -> tuple[Optional[float], str]:
    """将原始字符串值转换为数值。

    转换优先级：
    1. "0x" 前缀 → int(value, 16) → type=hex
    2. 纯整数 → int(value) → type=decimal
    3. 浮点数 → float(value) → type=float
    4. 其他 → type=string, numeric=None

    Args:
        raw_value: 原始值字符串（已 strip）。

    Returns:
        (num_value, value_type) 元组。
    """
    v = raw_value.strip()
    if not v:
        return None, "string"

    # 十六进制
    if v.lower().startswith("0x"):
        try:
            return float(int(v, 16)), "hex"
        except ValueError:
            return None, "string"

    # 纯整数
    try:
        return float(int(v)), "decimal"
    except ValueError:
        pass

    # 浮点数
    try:
        return float(v), "float"
    except ValueError:
        pass

    return None, "string"


# ============================================================
# Section 分块
# ============================================================

@dataclass
class _SectionBlock:
    """内部使用：一个 Section 的原始文本块。"""

    name: str
    lines: list[str] = field(default_factory=list)


def _split_sections(lines: list[str]) -> list[_SectionBlock]:
    """将日志文本按 Section 切分。

    识别规则：
    - 文件头（Section Header 出现前的顶层 KV）→ "header"
    - "Start of test:" 等 → 对应 Section
    - "Cycles:N" → "Cycles"
    - 空行作为 Section 间分隔（不归属任何 Section）

    Args:
        lines: 日志文件的所有行。

    Returns:
        SectionBlock 列表。
    """
    blocks: list[_SectionBlock] = []
    current: Optional[_SectionBlock] = None

    for line in lines:
        stripped = line.rstrip()

        # 空行：不归属任何 Section，仅作为分隔
        if not stripped:
            continue

        # 检查是否为 Section Header
        header_match = _RE_SECTION_HEADER.match(stripped)
        if header_match:
            section_name = header_match.group(1).strip()
            current = _SectionBlock(name=section_name)
            blocks.append(current)
            continue

        # 检查是否为紧凑 KV（如 "Cycles:0"）
        compact_match = _RE_COMPACT_KV.match(stripped)
        if compact_match and not stripped.startswith(" ") and not stripped.startswith("\t"):
            key = compact_match.group(1)
            if key == "Cycles":
                # Cycles 行归入 "Cycles" section
                if current is None or current.name != "Cycles":
                    current = _SectionBlock(name="Cycles")
                    blocks.append(current)
                current.lines.append(stripped)
                continue

        # 其余行归入当前 Section；如果尚无 Section，创建 "header"
        if current is None:
            current = _SectionBlock(name="header")
            blocks.append(current)

        current.lines.append(stripped)

    return blocks


# ============================================================
# KV 提取
# ============================================================

def _parse_key(raw_key: str) -> tuple[str, Optional[str], Optional[str]]:
    """解析键名，返回 (clean_key, prefix, array_index)。

    示例:
        "[SLC] WearGap"   → ("WearGap", "SLC", None)
        "bFWVersion[64]"  → ("bFWVersion", None, "64")
        "wPdmPostCnt"     → ("wPdmPostCnt", None, None)

    Args:
        raw_key: 原始键名。

    Returns:
        (clean_key, prefix, array_index) 三元组。
    """
    key = raw_key.strip()
    prefix: Optional[str] = None
    array_index: Optional[str] = None

    # 提取前缀 [SLC] / [TLC]
    prefix_match = _RE_PREFIX.match(key)
    if prefix_match:
        prefix = prefix_match.group(1)
        key = prefix_match.group(2).strip()

    # 提取数组下标 [64]
    array_match = _RE_ARRAY.match(key)
    if array_match:
        key = array_match.group(1)
        array_index = array_match.group(2)

    return key, prefix, array_index


def _extract_kv_from_block(block: _SectionBlock) -> list[MetricEntry]:
    """从 SectionBlock 中提取所有 KV 指标。

    处理的格式：
    1. 顶层 KV（header section）
    2. 缩进 KV（4 空格缩进）
    3. Tab-Result
    4. 紧凑 KV（Cycles）
    5. 自由文本行（RTMS_EINFO 描述）
    6. 混合叙述行（"A GMZone contains..."）
    7. Hex Dump 块（跳过）

    Args:
        block: Section 文本块。

    Returns:
        MetricEntry 列表。
    """
    entries: list[MetricEntry] = []
    section = block.name
    lines = block.lines
    i = 0
    free_text_counter = 0

    while i < len(lines):
        line = lines[i]

        try:
            # ---- 1. Tab-Result ----
            tab_match = _RE_TAB_RESULT.match(line)
            if tab_match:
                raw_key = tab_match.group(1)
                raw_val = tab_match.group(2).strip()
                num_val, val_type = convert_value(raw_val)
                entries.append(MetricEntry(
                    section=section, key_raw=raw_key, key=raw_key,
                    raw_value=raw_val, num_value=num_val, value_type=val_type,
                ))
                i += 1
                continue

            # ---- 2. 缩进 KV（4 空格） ----
            indent_match = _RE_INDENT_KV.match(line)
            if indent_match:
                # 正则已内联前缀捕获：group(1)=前缀, group(2)=键名, group(3)=值
                inline_prefix = indent_match.group(1)  # 可能为 None
                raw_key_part = indent_match.group(2).strip()
                raw_val = indent_match.group(3).strip()
                # 构造完整的 raw_key 供存储
                raw_key = f"[{inline_prefix}] {raw_key_part}" if inline_prefix else raw_key_part

                # 检查是否为 Hex Dump 起始（值为空，下一行是 Offset 表头）
                if not raw_val and i + 1 < len(lines) and _RE_HEX_OFFSET_HEADER.match(lines[i + 1]):
                    # 跳过 Hex Dump 块：收集所有 dump 行作为整体值
                    dump_lines: list[str] = []
                    i += 2  # 跳过当前行和 Offset 表头行
                    while i < len(lines) and _RE_HEX_DUMP_LINE.match(lines[i]):
                        dump_lines.append(lines[i].strip())
                        i += 1
                    # 将整个 Hex Dump 存储为一条记录
                    hex_text = "\n".join(dump_lines)
                    entries.append(MetricEntry(
                        section=section, key_raw=raw_key, key=raw_key,
                        raw_value=hex_text, num_value=None, value_type="hexdump",
                    ))
                    continue

                # 正常缩进 KV
                # 前缀已由正则内联捕获，只需处理数组下标
                clean_key = raw_key_part
                array_index: Optional[str] = None
                array_match = _RE_ARRAY.match(clean_key)
                if array_match:
                    clean_key = array_match.group(1)
                    array_index = array_match.group(2)
                prefix = inline_prefix
                num_val, val_type = convert_value(raw_val)
                entries.append(MetricEntry(
                    section=section, key_raw=raw_key, key=clean_key,
                    raw_value=raw_val, num_value=num_val, value_type=val_type,
                    prefix=prefix, array_index=array_index,
                ))
                i += 1
                continue

            # ---- 3. 顶层 KV（header section） ----
            top_match = _RE_TOP_KV.match(line)
            if top_match:
                raw_key = top_match.group(1)
                raw_val = top_match.group(2).strip()
                clean_key, prefix, array_index = _parse_key(raw_key)
                num_val, val_type = convert_value(raw_val)
                entries.append(MetricEntry(
                    section=section, key_raw=raw_key, key=clean_key,
                    raw_value=raw_val, num_value=num_val, value_type=val_type,
                    prefix=prefix, array_index=array_index,
                ))
                i += 1
                continue

            # ---- 4. 紧凑 KV（Cycles） ----
            compact_match = _RE_COMPACT_KV.match(line)
            if compact_match and not line.startswith(" ") and not line.startswith("\t"):
                raw_key = compact_match.group(1)
                raw_val = compact_match.group(2).strip()
                num_val, val_type = convert_value(raw_val)
                entries.append(MetricEntry(
                    section=section, key_raw=raw_key, key=raw_key,
                    raw_value=raw_val, num_value=num_val, value_type=val_type,
                ))
                i += 1
                continue

            # ---- 5. Hex Dump 数据行（独立出现时跳过） ----
            if _RE_HEX_DUMP_LINE.match(line) or _RE_HEX_OFFSET_HEADER.match(line):
                i += 1
                continue

            # ---- 6. 混合叙述行 / 自由文本（非标准行） ----
            # 缩进但不匹配冒号分隔的行，整行存储
            if line.startswith("    ") or line.startswith("\t"):
                free_text_counter += 1
                free_key = f"free_text_{free_text_counter}"
                raw_val = line.strip()
                entries.append(MetricEntry(
                    section=section, key_raw=raw_val, key=free_key,
                    raw_value=raw_val, num_value=None, value_type="string",
                ))
                i += 1
                continue

            # ---- 7. 无法识别的行：记录日志后跳过 ----
            logger.debug("跳过无法识别的行 [%s L%d]: %s", section, i + 1, line)
            i += 1

        except Exception as exc:
            logger.warning("解析行失败 [%s L%d]: %s - %s", section, i + 1, line, exc)
            i += 1

    return entries


# ============================================================
# 主解析器
# ============================================================

class LogParser:
    """RTMS 测试日志解析器门面。

    编排 Section 分块、KV 提取、数值转换，完成单个文件的完整解析。
    """

    def parse_file(self, file_path: str) -> ParseResult:
        """解析单个日志文件。

        Args:
            file_path: 日志文件绝对路径。

        Returns:
            ParseResult 对象，包含所有解析出的指标和元数据。
        """
        file_name = os.path.basename(file_path)
        file_size = os.path.getsize(file_path)
        file_mtime = os.path.getmtime(file_path)

        result = ParseResult(
            file_name=file_name,
            file_path=file_path,
            file_size=file_size,
            file_mtime=file_mtime,
        )

        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.read().splitlines()
        except Exception as exc:
            result.status = "Failed"
            result.error = f"文件读取失败: {exc}"
            logger.error("文件读取失败 %s: %s", file_path, exc)
            return result

        try:
            # 1. Section 分块
            blocks = _split_sections(lines)

            # 2. 逐 Section 提取 KV
            all_metrics: list[MetricEntry] = []
            for block in blocks:
                try:
                    metrics = _extract_kv_from_block(block)
                    all_metrics.extend(metrics)
                except Exception as exc:
                    logger.warning("Section '%s' 解析失败: %s", block.name, exc)

            result.metrics = all_metrics

            # 3. 从指标中提取主表冗余字段
            self._extract_summary_fields(result)

        except Exception as exc:
            result.status = "Failed"
            result.error = f"解析异常: {exc}"
            logger.error("解析异常 %s: %s", file_path, exc, exc_info=True)

        return result

    def _extract_summary_fields(self, result: ParseResult) -> None:
        """从 metrics 列表中提取主表冗余字段。

        扫描所有指标，根据 section 和 key 提取高频使用的字段值到主表。

        Args:
            result: 待填充的 ParseResult。
        """
        # header section 中的顶层字段
        for m in result.metrics:
            if m.section == "header":
                if m.key == "Device_Name":
                    result.device_name = m.raw_value
                elif m.key == "Device_Tool_Name":
                    result.device_tool_name = m.raw_value
                elif m.key == "Device_Config_Name":
                    result.device_config_name = m.raw_value

        # Start of test 中的关键字段
        for m in result.metrics:
            if m.section == "Start of test":
                if m.key == "bFWVersion" and m.array_index == "64":
                    result.fw_version = m.raw_value
                elif m.key == "bMPToolVersion":
                    result.mp_tool_version = m.raw_value
                elif m.key == "bFlashID":
                    result.flash_id = m.raw_value
                elif m.key == "dwOriginalBadBlock":
                    result.original_bad_block = (
                        int(m.num_value) if m.num_value is not None else None
                    )

        # Cycles
        cycle_values = [
            int(m.num_value)
            for m in result.metrics
            if m.section == "Cycles" and m.key == "Cycles" and m.num_value is not None
        ]
        if cycle_values:
            result.cycles = max(cycle_values)

        # Wear_Detection 关键指标
        for m in result.metrics:
            if m.section == "Wear_Detection":
                if m.key == "WAI":
                    result.wai = m.num_value
                elif m.key == "wSLCMinPECycle":
                    result.slc_pe_min = int(m.num_value) if m.num_value is not None else None
                elif m.key == "wSLCMaxPECycle":
                    result.slc_pe_max = int(m.num_value) if m.num_value is not None else None
                elif m.key == "wTLCMinPECycle":
                    result.tlc_pe_min = int(m.num_value) if m.num_value is not None else None
                elif m.key == "wTLCMaxPECycle":
                    result.tlc_pe_max = int(m.num_value) if m.num_value is not None else None
                elif m.key == "dwIncreaseBadBlock" and m.prefix is None:
                    result.increase_bad_block = int(m.num_value) if m.num_value is not None else None

        # End of test 中的 dwIncreaseBadBlock（如果 Wear_Detection 中未取到）
        if result.increase_bad_block is None:
            for m in result.metrics:
                if m.section == "End of test" and m.key == "dwIncreaseBadBlock":
                    result.increase_bad_block = int(m.num_value) if m.num_value is not None else None
                    break

        # 汇总 Result：遍历所有 section 的 Result 指标
        fail_sections: list[str] = []
        has_pass = False
        has_fail = False
        for m in result.metrics:
            if m.key == "Result":
                val = m.raw_value.strip()
                if "Fail" in val:
                    has_fail = True
                    fail_sections.append(m.section)
                elif "Pass" in val:
                    has_pass = True

        result.fail_sections = fail_sections
        if has_fail:
            result.overall_result = "Fail"
        elif has_pass:
            result.overall_result = "Pass"
        else:
            result.overall_result = "Unknown"
