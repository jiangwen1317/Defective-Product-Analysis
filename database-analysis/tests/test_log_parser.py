"""
日志解析器单元测试

覆盖 convert_value、_extract_array_index、_parse_lines 及 LogParser.parse_file。
"""
import os

import pytest

from log_parser import (
    LogParser,
    MetricEntry,
    ParseResult,
    _extract_array_index,
    _parse_lines,
    convert_value,
)


# ================================================================
# convert_value 数值转换
# ================================================================

class TestConvertValue:
    """测试 convert_value 函数对各类型值的转换。"""

    def test_hex_value(self):
        assert convert_value("0x00000001") == (1.0, "hex")

    def test_hex_value_uppercase(self):
        assert convert_value("0xFF") == (255.0, "hex")

    def test_hex_invalid(self):
        assert convert_value("0xGGG") == (None, "string")

    def test_integer_value(self):
        assert convert_value("12345") == (12345.0, "decimal")

    def test_negative_integer(self):
        assert convert_value("-42") == (-42.0, "decimal")

    def test_float_value(self):
        assert convert_value("161.136") == (161.136, "float")

    def test_string_value(self):
        assert convert_value("DM3720.026.04") == (None, "string")

    def test_empty_string(self):
        assert convert_value("") == (None, "string")

    def test_whitespace_only(self):
        assert convert_value("   ") == (None, "string")

    def test_fw_version_string(self):
        val, vtype = convert_value("TL600E -V3.2.9-Jun  2 2026 19:33:31")
        assert vtype == "string"
        assert val is None


# ================================================================
# _extract_array_index 数组下标提取
# ================================================================

class TestExtractArrayIndex:
    """测试 _extract_array_index 键名清洗。"""

    def test_with_array_index(self):
        key, idx = _extract_array_index("bFWVersion[64]")
        assert key == "bFWVersion"
        assert idx == "64"

    def test_without_array_index(self):
        key, idx = _extract_array_index("WAI")
        assert key == "WAI"
        assert idx is None

    def test_zero_index(self):
        key, idx = _extract_array_index("dwBlockPECycle[0000]")
        assert key == "dwBlockPECycle"
        assert idx == "0000"


# ================================================================
# _parse_lines 逐行解析
# ================================================================

class TestParseLines:
    """测试 _parse_lines 的行分类逻辑。"""

    def test_compact_kv(self):
        entries = _parse_lines(["Device_Name:DM3720.026.04"])
        assert len(entries) == 1
        assert entries[0].key == "Device_Name"
        assert entries[0].raw_value == "DM3720.026.04"
        assert entries[0].section == "header"

    def test_inline_section_pass(self):
        entries = _parse_lines(["Wear_Detection:Pass"])
        assert len(entries) == 1
        assert entries[0].section == "Wear_Detection"

    def test_inline_section_fail(self):
        entries = _parse_lines(["Wear_Detection:Fail"])
        assert len(entries) == 1
        assert entries[0].section == "Wear_Detection"

    def test_section_switch(self):
        lines = [
            "WAI:161.136",
            "Wear_Detection:Pass",
            "wBlockTotalNum:0x171",
        ]
        entries = _parse_lines(lines)
        assert entries[0].section == "header"
        assert entries[1].section == "Wear_Detection"
        assert entries[2].section == "Wear_Detection"

    def test_hex_dump_block(self):
        lines = [
            "eMMC_EXT_CSD:",
            "Offset:  00 01 02 03",
            "...000:  00 00 00 00",
            "...016:  39 03 00 80",
        ]
        entries = _parse_lines(lines)
        assert len(entries) == 1
        assert entries[0].section == "eMMC_EXT_CSD"
        assert entries[0].value_type == "hexdump"

    def test_ext_csd_decoded_field(self):
        line = "Ext_CSD[212] SEC_COUNT:        0x07490000"
        entries = _parse_lines([line])
        assert len(entries) == 1
        assert entries[0].section == "Ext_CSD"
        assert entries[0].key == "SEC_COUNT"
        assert entries[0].array_index == "212"

    def test_rtms_var_pair(self):
        lines = [
            "rtms_str_var:dwDegreOfwear",
            "rtms_get_var:27",
        ]
        entries = _parse_lines(lines)
        assert len(entries) == 2
        assert entries[0].key == "rtms_str_var"
        assert entries[1].key == "rtms_get_var"

    def test_platform_kv(self):
        line = "Platform Keys: VCC = 3343 mv"
        entries = _parse_lines([line])
        assert len(entries) == 1
        assert entries[0].key == "Platform Keys"
        assert entries[0].raw_value == "VCC = 3343 mv"

    def test_free_text(self):
        """纯文本行（不含冒号或不匹配任何正则）归入 free_text。"""
        line = "=== test output begins ==="
        entries = _parse_lines([line])
        assert len(entries) == 1
        assert entries[0].key == "free_text_1"

    def test_sys_colon_kv_not_free_text(self):
        """SYS:Start 被紧凑 KV 正则匹配为 key=SYS，而非自由文本。"""
        entries = _parse_lines(["SYS:Start"])
        assert len(entries) == 1
        assert entries[0].key == "SYS"
        assert entries[0].raw_value == "Start"

    def test_empty_lines_skipped(self):
        entries = _parse_lines(["", "  ", "Device_Name:TEST"])
        assert len(entries) == 1

    def test_array_index_extraction_in_kv(self):
        entries = _parse_lines(["bFWVersion[64]:TL600E -V3.2.9"])
        assert entries[0].key == "bFWVersion"
        assert entries[0].array_index == "64"

    def test_prefix_kv(self):
        """带 [SLC] / [TLC] 前缀的 KV 行。"""
        entries = _parse_lines(["[SLC] WearGap          :0x0"])
        assert len(entries) == 1


# ================================================================
# LogParser.parse_file 完整文件解析
# ================================================================

class TestLogParserFile:
    """基于参考日志文件的完整解析验证。"""

    # ---- 日志 1: DM3720.026.04 ----

    def test_log1_parse_status(self, result_log1):
        assert result_log1.status == "Success"

    def test_log1_device_name(self, result_log1):
        assert result_log1.device_name == "DM3720.026.04"

    def test_log1_fw_version(self, result_log1):
        assert result_log1.fw_version == "TL600E -V3.2.9-Jun  2 2026 19:33:31"

    def test_log1_mp_tool_version(self, result_log1):
        assert result_log1.mp_tool_version == "V1.0.9"

    def test_log1_flash_id(self, result_log1):
        assert result_log1.flash_id == "0x45433545413838463838433100000000"

    def test_log1_original_bad_block(self, result_log1):
        assert result_log1.original_bad_block == 1

    def test_log1_controller(self, result_log1):
        assert result_log1.controller == "600"

    def test_log1_capacity_mb(self, result_log1):
        assert result_log1.capacity_mb == 59680

    def test_log1_capacity_sectors(self, result_log1):
        assert result_log1.capacity_sectors == 122224640

    def test_log1_part_number(self, result_log1):
        assert result_log1.part_number == "D8A61C"

    def test_log1_task_link(self, result_log1):
        assert result_log1.task_link == "10.2.3.145/device/27582/false/316903"

    def test_log1_test_cycle(self, result_log1):
        assert result_log1.test_cycle == 1

    def test_log1_test_case(self, result_log1):
        assert result_log1.test_case == 13

    def test_log1_rtms_result(self, result_log1):
        assert result_log1.rtms_result == "PASS"

    def test_log1_rtms_code(self, result_log1):
        """RTMS_Code 的值经过 strip 后为 '0'（原始行 'RTMS_Code: 0'）。"""
        assert result_log1.rtms_code == "0"

    def test_log1_overall_result(self, result_log1):
        assert result_log1.overall_result == "Pass"

    def test_log1_fail_sections_empty(self, result_log1):
        assert result_log1.fail_sections == []

    def test_log1_wai(self, result_log1):
        assert result_log1.wai == pytest.approx(161.136)

    def test_log1_slc_pe(self, result_log1):
        assert result_log1.slc_pe_min == 0
        assert result_log1.slc_pe_max == 0

    def test_log1_tlc_pe(self, result_log1):
        assert result_log1.tlc_pe_min == 0
        assert result_log1.tlc_pe_max == 1

    def test_log1_increase_bad_block(self, result_log1):
        assert result_log1.increase_bad_block == 0

    def test_log1_metrics_count(self, result_log1):
        """日志 1 应解析出大量指标（含 dwBlockPECycle 数组 369 条）。"""
        assert len(result_log1.metrics) > 500

    def test_log1_has_ext_csd_section(self, result_log1):
        ext_csd = [m for m in result_log1.metrics if m.section == "Ext_CSD"]
        assert len(ext_csd) > 50

    def test_log1_has_hexdump(self, result_log1):
        hexdump = [m for m in result_log1.metrics if m.value_type == "hexdump"]
        assert len(hexdump) >= 1

    def test_log1_block_pe_cycle_count(self, result_log1):
        """dwBlockPECycle 数组应有 369 条（索引 0000-0368）。"""
        pe_cycles = [
            m for m in result_log1.metrics
            if m.key == "dwBlockPECycle" and m.array_index is not None
        ]
        assert len(pe_cycles) == 369

    def test_log1_wear_detection_pass(self, result_log1):
        """Wear_Detection section 应包含 Pass 结果。"""
        wear_entries = [
            m for m in result_log1.metrics
            if m.section == "Wear_Detection" and "Pass" in m.raw_value
        ]
        assert len(wear_entries) >= 1

    # ---- 日志 2: DM3720.033.07 ----

    def test_log2_parse_status(self, result_log2):
        assert result_log2.status == "Success"

    def test_log2_device_name(self, result_log2):
        assert result_log2.device_name == "DM3720.033.07"

    def test_log2_fw_version(self, result_log2):
        assert result_log2.fw_version == "TL600E -V2.3.20-Mar  4 2026 20:14:00"

    def test_log2_original_bad_block(self, result_log2):
        assert result_log2.original_bad_block == 3

    def test_log2_part_number(self, result_log2):
        assert result_log2.part_number == "C3F901"

    def test_log2_wai(self, result_log2):
        assert result_log2.wai == pytest.approx(149.2)

    def test_log2_slc_pe(self, result_log2):
        assert result_log2.slc_pe_min == 0
        assert result_log2.slc_pe_max == 1

    def test_log2_overall_result(self, result_log2):
        assert result_log2.overall_result == "Pass"

    def test_log2_capacity_sectors(self, result_log2):
        assert result_log2.capacity_sectors == 122224640

    def test_log2_block_pe_cycle_count(self, result_log2):
        """日志 2 的 dwBlockPECycle 数组应有 370 条（索引 0000-0369）。"""
        pe_cycles = [
            m for m in result_log2.metrics
            if m.key == "dwBlockPECycle" and m.array_index is not None
        ]
        assert len(pe_cycles) == 370

    def test_log2_has_rtms_winfo(self, result_log2):
        """日志 2 包含 RTMS_WINFO 行。"""
        winfo = [m for m in result_log2.metrics if "WINFO" in m.key_raw or "WINFO" in m.raw_value]
        assert len(winfo) >= 1

    # ---- 边界场景 ----

    def test_nonexistent_file(self, parser):
        """parse_file 在 try 之前调用 os.path.getsize，不存在时抛 FileNotFoundError。

        注意：这是当前实现的行为，后续可考虑将 getsize 移入 try 块。
        """
        with pytest.raises(FileNotFoundError):
            parser.parse_file("/nonexistent/path/file.txt")

    def test_empty_file(self, parser, tmp_path):
        empty_file = tmp_path / "empty.txt"
        empty_file.write_text("", encoding="utf-8")
        result = parser.parse_file(str(empty_file))
        assert result.status == "Success"
        assert len(result.metrics) == 0
        assert result.overall_result == "Unknown"

    def test_file_metadata(self, result_log1):
        """验证文件元数据（file_name, file_size, file_mtime）。"""
        assert result_log1.file_name.endswith(".txt")
        assert result_log1.file_size > 0
        assert result_log1.file_mtime > 0


# ================================================================
# MetricEntry.as_tuple
# ================================================================

class TestMetricEntry:
    """测试 MetricEntry 数据结构和序列化。"""

    def test_as_tuple(self):
        entry = MetricEntry(
            section="header", key_raw="WAI", key="WAI",
            raw_value="161.136", num_value=161.136,
            value_type="float", prefix=None, array_index=None,
        )
        t = entry.as_tuple()
        assert len(t) == 8
        assert t == ("header", "WAI", "WAI", "161.136", 161.136, "float", None, None)

    def test_as_tuple_with_prefix(self):
        entry = MetricEntry(
            section="header", key_raw="[SLC] WearGap", key="WearGap",
            raw_value="0x0", num_value=0.0,
            value_type="hex", prefix="SLC", array_index=None,
        )
        t = entry.as_tuple()
        assert t[6] == "SLC"
