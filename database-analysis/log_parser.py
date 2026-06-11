"""
EMMC RTMS 测试日志解析引擎

将半结构化的 RTMS 日志文件解析为结构化的 ParseResult 对象。
采用扁平化逐行分类解析策略，直接产出 MetricEntry 列表。

错误隔离原则：单文件/单行 解析失败不中断整体流程。
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

    section: str            # 所属 Section（如 "header"、"Wear_Detection"）
    key_raw: str            # 原始键名（如 "bFWVersion[64]"）
    key: str                # 清洗后键名（如 "bFWVersion"）
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
    # 关键字段
    fw_version: Optional[str] = None
    mp_tool_version: Optional[str] = None
    flash_id: Optional[str] = None
    original_bad_block: Optional[int] = None
    # Cycles
    cycles: int = 0
    # 设备扩展信息
    controller: Optional[str] = None
    capacity_mb: Optional[int] = None
    capacity_sectors: Optional[int] = None
    part_number: Optional[str] = None
    task_link: Optional[str] = None
    # 测试参数
    test_cycle: int = 0
    test_case: int = 0
    # 最终结果
    rtms_result: Optional[str] = None
    rtms_code: Optional[str] = None
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

# 紧凑 KV：键名支持数组下标，允许键名与冒号间有 padding 空格
# "Device_Name:DM3720.026.04"
# "WAI                    :161.136"
# "dwBlockPECycle[0000]:0000"
_RE_COMPACT_KV = re.compile(r'^([A-Za-z_][\w\[\]]+)\s*:(.+)$')

# 内联测试结果：SectionName:Pass 或 SectionName:Fail
# "Wear_Detection:Pass"
# "GM/BIT_comparison_garbage:Pass"
_RE_INLINE_SECTION_RESULT = re.compile(r'^([\w/]+(?:_[\w]+)*):(Pass|Fail)\s*$')

# Ext_CSD 解码字段：Ext_CSD[N] Field Name: value
# "Ext_CSD[0]   Reserved_0[0-6]:   0x0"
# "Ext_CSD[253] PWR_CL_DDR_200_360:  (4 bit bus)..."
_RE_EXT_CSD_KV = re.compile(r'^Ext_CSD\[(\d+(?:-\d+)?)\]\s+(.+?)\s*:\s*(.*)$')

# Platform 系列 KV：键名含空格
# "Platform Keys: VCC = 3343 mv"
# "Platform Info: [eMMC Cap] YW"
# "Platform info:VCC 3345 mv"
_RE_PLATFORM_KV = re.compile(r'^(Platform\s+\w+)\s*:\s*(.*)$')

# Hex Dump 数据行：...DDD:  XX XX XX ...
_RE_HEX_DUMP_LINE = re.compile(r'^\s*\.\.\.\d+:\s+[\dA-Fa-f\s]+$')

# Hex Dump Offset 表头行
_RE_HEX_OFFSET_HEADER = re.compile(r'^\s*Offset:')

# 带数组下标的键名：bFWVersion[64]
_RE_ARRAY = re.compile(r'^(.+?)\[(\d+)\]$')

# rtms_str_var / rtms_get_var 配对行
# "rtms_str_var:dwDegreOfwear"
# "rtms_get_var:27"
_RE_RTMS_VAR = re.compile(r'^(rtms_str_var|rtms_get_var):(.+)$')

# 从 info:Capacity:NNN Sec 格式提取扇区数
# "info:Capacity:122224640 Sec"
_RE_INFO_CAPACITY_SECTORS = re.compile(r'^Capacity\s*:\s*(\d+)\s*Sec')

# 已知的测试 Section 名称白名单（用于内联结果识别，避免误匹配普通 KV）
_KNOWN_TEST_SECTIONS: set[str] = {
    "Wear_Detection",
    "EmptyBlk_Detection",
    "GarbageDetection",
    "Cold_and_heat",
    "PM_mapping_validity_detection",
    "GM_table_match",
    "BM_table_match",
    "GM/BIT_comparison_garbage",
    "PDMI_legitimacy_detection",
    "PDMI_index_legitimacy_detection",
    "PDMBlockGarbComparison",
    "Check_Partition_Data",
    "RTMS_StackUtilization",
}


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


def _extract_array_index(raw_key: str) -> tuple[str, Optional[str]]:
    """从键名中提取数组下标。

    Args:
        raw_key: 原始键名（如 "bFWVersion[64]"）。

    Returns:
        (clean_key, array_index) 元组。
    """
    match = _RE_ARRAY.match(raw_key)
    if match:
        return match.group(1), match.group(2)
    return raw_key, None


# ============================================================
# 逐行分类解析
# ============================================================

def _parse_lines(lines: list[str]) -> list[MetricEntry]:
    """逐行分类解析日志，直接产出 MetricEntry 列表。

    匹配优先级（从高到低）：
    1. Hex Dump 块（eMMC_EXT_CSD/eMMC_CSD + Offset + 数据行）
    2. Ext_CSD 解码字段（Ext_CSD[N] Field: value）
    3. rtms_str_var / rtms_get_var 配对行
    4. Platform 系列 KV（Platform Keys/Info/info）
    5. 内联测试结果（SectionName:Pass/Fail）
    6. 顶层紧凑 KV（Key:Value）
    7. 自由文本行

    Section 归属规则：
    - 默认为 "header"
    - 遇到内联测试结果时切换为该 Section 名
    - Ext_CSD 解码字段始终归入 "Ext_CSD"
    - Hex Dump 块归入 "eMMC_EXT_CSD"

    Args:
        lines: 日志文件的所有行。

    Returns:
        MetricEntry 列表。
    """
    entries: list[MetricEntry] = []
    current_section = "header"
    free_text_counter = 0
    i = 0

    while i < len(lines):
        line = lines[i].rstrip()

        # 空行跳过
        if not line:
            i += 1
            continue

        try:
            # ---- 1. Hex Dump 块 ----
            # 检测 eMMC_EXT_CSD: 或 eMMC_CSD: 后跟 Offset 表头 + 数据行
            if (
                (line.startswith("eMMC_EXT_CSD") or line.startswith("eMMC_CSD"))
                and i + 1 < len(lines)
                and _RE_HEX_OFFSET_HEADER.match(lines[i + 1].rstrip())
            ):
                dump_lines: list[str] = []
                i += 2  # 跳过当前行和 Offset 表头行
                while i < len(lines) and _RE_HEX_DUMP_LINE.match(lines[i].rstrip()):
                    dump_lines.append(lines[i].strip())
                    i += 1
                hex_text = "\n".join(dump_lines)
                key_raw = line.rstrip()
                entries.append(MetricEntry(
                    section="eMMC_EXT_CSD", key_raw=key_raw, key=key_raw,
                    raw_value=hex_text, num_value=None, value_type="hexdump",
                ))
                continue

            # ---- 2. Ext_CSD 解码字段 ----
            ext_csd_match = _RE_EXT_CSD_KV.match(line)
            if ext_csd_match:
                offset = ext_csd_match.group(1)
                field_name = ext_csd_match.group(2).strip()
                raw_val = ext_csd_match.group(3).strip()
                raw_key = f"Ext_CSD[{offset}] {field_name}"
                num_val, val_type = convert_value(raw_val)
                entries.append(MetricEntry(
                    section="Ext_CSD", key_raw=raw_key, key=field_name,
                    raw_value=raw_val, num_value=num_val, value_type=val_type,
                    array_index=offset,
                ))
                i += 1
                continue

            # ---- 3. rtms_str_var / rtms_get_var ----
            rtms_var_match = _RE_RTMS_VAR.match(line)
            if rtms_var_match:
                var_type = rtms_var_match.group(1)
                raw_val = rtms_var_match.group(2).strip()
                entries.append(MetricEntry(
                    section=current_section, key_raw=line.strip(), key=var_type,
                    raw_value=raw_val, num_value=None, value_type="string",
                ))
                i += 1
                continue

            # ---- 4. Platform 系列 KV ----
            plat_match = _RE_PLATFORM_KV.match(line)
            if plat_match:
                plat_key = plat_match.group(1).strip()
                raw_val = plat_match.group(2).strip()
                entries.append(MetricEntry(
                    section=current_section, key_raw=line.strip(), key=plat_key,
                    raw_value=raw_val, num_value=None, value_type="string",
                ))
                i += 1
                continue

            # ---- 5. 内联测试结果（切换 Section） ----
            inline_match = _RE_INLINE_SECTION_RESULT.match(line)
            if inline_match:
                section_name = inline_match.group(1).strip()
                if section_name in _KNOWN_TEST_SECTIONS:
                    current_section = section_name
                    raw_val = line.strip()
                    entries.append(MetricEntry(
                        section=current_section, key_raw=raw_val, key=raw_val,
                        raw_value=raw_val, num_value=None, value_type="string",
                    ))
                    i += 1
                    continue

            # ---- 6. 顶层紧凑 KV（主力匹配） ----
            compact_match = _RE_COMPACT_KV.match(line)
            if compact_match:
                raw_key = compact_match.group(1)
                raw_val = compact_match.group(2).strip()
                clean_key, array_index = _extract_array_index(raw_key)
                num_val, val_type = convert_value(raw_val)
                entries.append(MetricEntry(
                    section=current_section, key_raw=raw_key, key=clean_key,
                    raw_value=raw_val, num_value=num_val, value_type=val_type,
                    array_index=array_index,
                ))
                i += 1
                continue

            # ---- 7. 独立 Hex Dump 行（跳过） ----
            if _RE_HEX_DUMP_LINE.match(line) or _RE_HEX_OFFSET_HEADER.match(line):
                i += 1
                continue

            # ---- 8. 自由文本行（整行存储） ----
            free_text_counter += 1
            free_key = f"free_text_{free_text_counter}"
            raw_val = line.strip()
            entries.append(MetricEntry(
                section=current_section, key_raw=raw_val, key=free_key,
                raw_value=raw_val, num_value=None, value_type="string",
            ))
            i += 1

        except Exception as exc:
            logger.warning("解析行失败 [L%d]: %s - %s", i + 1, line, exc)
            i += 1

    return entries


# ============================================================
# 主解析器
# ============================================================

class LogParser:
    """RTMS 测试日志解析器门面。

    采用扁平化逐行分类解析，完成单个文件的完整解析。
    """

    def parse_file(self, file_path: str) -> ParseResult:
        """解析单个日志文件。

        Args:
            file_path: 日志文件绝对路径。

        Returns:
            ParseResult 对象，包含所有解析出的指标和元数据。
        """
        result = ParseResult(
            file_name=os.path.basename(file_path),
            file_path=file_path,
            file_size=0,
            file_mtime=0.0,
        )

        try:
            file_size = os.path.getsize(file_path)
            file_mtime = os.path.getmtime(file_path)
            result.file_size = file_size
            result.file_mtime = file_mtime
        except OSError as exc:
            result.status = "Failed"
            result.error = f"文件访问失败: {exc}"
            logger.error("文件访问失败 %s: %s", file_path, exc)
            return result

        try:
            # 使用 utf-8-sig 自动处理 Windows BOM
            with open(file_path, "r", encoding="utf-8-sig", errors="replace") as f:
                lines = f.read().splitlines()
        except Exception as exc:
            result.status = "Failed"
            result.error = f"文件读取失败: {exc}"
            logger.error("文件读取失败 %s: %s", file_path, exc)
            return result

        try:
            # 逐行分类解析
            result.metrics = _parse_lines(lines)

            # 从指标中提取主表冗余字段
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
        # 磨损指标的候选 section（新格式中磨损数据在 header，
        # Wear_Detection 内联结果行之后可能有少量补充数据）
        _wear_sections = {"header", "Wear_Detection"}

        for m in result.metrics:
            # ---- 设备基本信息（header section） ----
            if m.section == "header":
                if m.key == "Device_Name":
                    result.device_name = m.raw_value
                elif m.key == "Device_Tool_Name":
                    result.device_tool_name = m.raw_value
                elif m.key == "Device_Config_Name":
                    result.device_config_name = m.raw_value
                elif m.key == "bFWVersion" and m.array_index == "64":
                    result.fw_version = m.raw_value
                elif m.key == "bMPToolVersion" and result.mp_tool_version is None:
                    result.mp_tool_version = m.raw_value
                elif m.key == "bFlashID" and result.flash_id is None:
                    result.flash_id = m.raw_value
                elif m.key == "dwOriginalBadBlock" and result.original_bad_block is None:
                    result.original_bad_block = (
                        int(m.num_value) if m.num_value is not None else None
                    )
                elif m.key == "Controller" and result.controller is None:
                    result.controller = m.raw_value
                elif m.key == "Capacity" and result.capacity_mb is None:
                    try:
                        result.capacity_mb = int(m.raw_value)
                    except (ValueError, TypeError):
                        pass
                elif m.key == "PNM" and result.part_number is None:
                    result.part_number = m.raw_value
                elif m.key == "TaskLink" and result.task_link is None:
                    result.task_link = m.raw_value
                elif m.key == "TestCycle" and result.test_cycle == 0:
                    try:
                        result.test_cycle = int(m.raw_value)
                    except (ValueError, TypeError):
                        pass
                elif m.key == "TestCase" and result.test_case == 0:
                    try:
                        result.test_case = int(m.raw_value)
                    except (ValueError, TypeError):
                        pass
                elif m.key == "RTMS_Result" and result.rtms_result is None:
                    result.rtms_result = m.raw_value
                elif m.key == "RTMS_Code" and result.rtms_code is None:
                    result.rtms_code = m.raw_value

        # RTMS_Result / RTMS_Code 全局备用查找
        if result.rtms_result is None or result.rtms_code is None:
            for m in result.metrics:
                if m.key == "RTMS_Result" and result.rtms_result is None:
                    result.rtms_result = m.raw_value
                elif m.key == "RTMS_Code" and result.rtms_code is None:
                    result.rtms_code = m.raw_value

        # 从 info:Capacity:NNN Sec 格式提取扇区数
        if result.capacity_sectors is None:
            for m in result.metrics:
                if m.key == "info" and result.capacity_sectors is None:
                    cap_match = _RE_INFO_CAPACITY_SECTORS.match(m.raw_value)
                    if cap_match:
                        try:
                            result.capacity_sectors = int(cap_match.group(1))
                        except (ValueError, TypeError):
                            pass

        # Wear_Detection 关键指标
        for m in result.metrics:
            if m.section in _wear_sections:
                if m.key == "WAI" and result.wai is None:
                    result.wai = m.num_value
                elif m.key == "wSLCMinPECycle" and result.slc_pe_min is None:
                    result.slc_pe_min = int(m.num_value) if m.num_value is not None else None
                elif m.key == "wSLCMaxPECycle" and result.slc_pe_max is None:
                    result.slc_pe_max = int(m.num_value) if m.num_value is not None else None
                elif m.key == "wTLCMinPECycle" and result.tlc_pe_min is None:
                    result.tlc_pe_min = int(m.num_value) if m.num_value is not None else None
                elif m.key == "wTLCMaxPECycle" and result.tlc_pe_max is None:
                    result.tlc_pe_max = int(m.num_value) if m.num_value is not None else None
                elif m.key == "dwIncreaseBadBlock" and m.prefix is None and result.increase_bad_block is None:
                    result.increase_bad_block = int(m.num_value) if m.num_value is not None else None

        # 汇总测试结果：
        # 1. 从内联 Section 结果中汇总（如 Wear_Detection:Pass）
        fail_sections: list[str] = []
        has_pass = False
        has_fail = False
        for m in result.metrics:
            if m.section in _KNOWN_TEST_SECTIONS and m.key_raw == m.raw_value:
                inline_match = _RE_INLINE_SECTION_RESULT.match(m.raw_value)
                if inline_match:
                    section_name = inline_match.group(1)
                    section_result = inline_match.group(2)
                    if section_result == "Fail":
                        has_fail = True
                        if section_name not in fail_sections:
                            fail_sections.append(section_name)
                    elif section_result == "Pass":
                        has_pass = True

        # 2. RTMS_Result 作为最终结果的最高优先级判断
        if result.rtms_result:
            rtms_upper = result.rtms_result.strip().upper()
            if "FAIL" in rtms_upper:
                has_fail = True
            elif "PASS" in rtms_upper:
                has_pass = True

        result.fail_sections = fail_sections
        if has_fail:
            result.overall_result = "Fail"
        elif has_pass:
            result.overall_result = "Pass"
        else:
            result.overall_result = "Unknown"
