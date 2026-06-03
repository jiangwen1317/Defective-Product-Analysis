# -*- coding: utf-8 -*-
"""
日志解析引擎

解析 EMMC 测试日志文件，提取 KV 指标存入数据库。
支持增量解析、错误隔离、Section 识别等功能。
"""

import logging
import os
import re
import time
from dataclasses import asdict
from typing import Dict, List, Optional, Tuple

from .config import Config, load_config
from .database import Database, get_database
from .models import ParseLog, ParseResult, TestMetric, TestSummary

logger = logging.getLogger(__name__)


class LogParser:
    """日志解析器"""

    # Section Header 正则: [SectionName]
    SECTION_PATTERN = re.compile(r"^\[([\w/_\-]+)\]$")

    # KV 提取正则: 支持 "Key : Value" 和 "Key = Value"
    KV_PATTERN = re.compile(r"^\s*([\w\[\]]+)\s*[:=]\s*(.+)$")

    # Cycles 行: Cycles:0
    CYCLES_PATTERN = re.compile(r"^Cycles:(\d+)$")

    # 结果行: Result : Pass! 或 Result:Pass
    RESULT_PATTERN = re.compile(r"Result\s*[:=]\s*(Pass|Fail)", re.IGNORECASE)

    # Hex Dump 行判断:
    # - Offset: 00 01 02 ... (表头)
    # - ...000: 00 01 02 ... (数据行)
    # - 纯十六进制: 00 01 02 03 (无前缀)
    HEX_DUMP_OFFSET = re.compile(r"^Offset:\s*")
    HEX_DUMP_DATA = re.compile(r"^\.\.\.\d+:\s*")
    HEX_DUMP_ROW = re.compile(r"^([0-9a-fA-F]{2})(\s+[0-9a-fA-F]{2})*\s*$")

    # 需要跳过的 Section (如 eMMC_EXT_CSD 的 hex dump)
    SKIP_SECTIONS = {"eMMC_EXT_CSD", "eMMC_CSD", "eMMC_CID"}

    def __init__(self, db: Optional[Database] = None, config: Optional[Config] = None):
        """
        初始化解析器。

        Args:
            db: 数据库实例
            config: 配置对象
        """
        self.config = config or load_config()
        self.db = db or get_database()

    def _is_hex_dump_line(self, line: str) -> bool:
        """
        判断是否为 Hex Dump 行。

        Args:
            line: 行内容

        Returns:
            是否为 Hex Dump 行
        """
        stripped = line.strip()
        if not stripped:
            return False

        # 跳过表头和数据行标记
        if self.HEX_DUMP_OFFSET.match(stripped):
            return True
        if self.HEX_DUMP_DATA.match(stripped):
            return True

        # 跳过纯十六进制数据行 (如 "00 01 02 03")
        if self.HEX_DUMP_ROW.match(stripped):
            return True

        return False

    def _normalize_key(self, key: str) -> str:
        """
        规范化键名。

        - 去除数组下标: bFWVersion[64] -> bFWVersion
        - 去除方括号前缀: [SLC] WearGap -> SLC_WearGap
        - 去除首尾空格

        Args:
            key: 原始键名

        Returns:
            规范化后的键名
        """
        key = key.strip()

        # 去除数组下标: bFWVersion[64] -> bFWVersion
        key = re.sub(r"\[\d+\]", "", key)

        # 去除方括号前缀: [SLC] WearGap -> SLC_WearGap
        key = re.sub(r"^\[([^\]]+)\]\s*", r"\1_", key)

        return key.strip()

    def _convert_value(self, value: str) -> Tuple[Optional[float], Optional[str], str]:
        """
        转换值。

        - 尝试转为浮点数
        - 支持十六进制 (0x...) 自动转十进制
        - 转换失败则保留原始字符串

        Args:
            value: 原始值

        Returns:
            (num_value, str_value, hex_value)
        """
        value = value.strip()
        hex_value = ""
        num_value = None
        str_value = ""

        # 判断是否为十六进制
        hex_match = re.match(r"^(0x[0-9a-fA-F]+)$", value)
        if hex_match:
            hex_value = value
            try:
                num_value = int(value, 16)
                # 如果是浮点数格式的十六进制(如某些浮点表示)
                if "." in value:
                    num_value = float.fromhex(value)
                else:
                    num_value = float(num_value)
            except (ValueError, AttributeError):
                pass

        # 尝试转为浮点数
        if num_value is None:
            try:
                # 处理可能的逗号分隔(如 1,000.00)
                clean_value = value.replace(",", "")
                num_value = float(clean_value)
            except ValueError:
                # 转换失败,保留为字符串
                str_value = value

        return num_value, str_value, hex_value

    def _is_skip_section(self, section: str) -> bool:
        """判断是否需要跳过的 Section"""
        return section in self.SKIP_SECTIONS or section in self.config.parser.skip_sections

    def _extract_global_info(self, lines: List[str]) -> Dict[str, str]:
        """
        从日志头部提取全局信息。

        Args:
            lines: 日志行列表

        Returns:
            全局信息字典
        """
        info: Dict[str, str] = {}

        for line in lines[:50]:  # 只扫描前 50 行
            match = self.KV_PATTERN.match(line)
            if match:
                key = self._normalize_key(match.group(1))
                value = match.group(2).strip()

                if key in ("Device_Name", "Device_Tool_Name", "Device_Config_Name"):
                    info[key] = value
                elif key in ("bFWVersion", "bMPToolVersion", "bFlashID", "dwOriginalBadBlock"):
                    info[key] = value

        return info

    def parse_file(self, file_path: str) -> ParseResult:
        """
        解析单个日志文件。

        Args:
            file_path: 日志文件路径

        Returns:
            ParseResult 解析结果

        Raises:
            FileNotFoundError: 文件不存在
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"文件不存在: {file_path}")

        logger.info(f"开始解析: {file_path}")

        # 准备结果对象
        start_time = time.time()
        result = ParseResult(
            summary=TestSummary(
                file_path=file_path,
                file_name=os.path.basename(file_path),
                created_at=time.time(),
            ),
        )

        try:
            # 读取文件
            encoding = self.config.parser.encoding
            with open(file_path, "r", encoding=encoding, errors="replace") as f:
                lines = f.readlines()

            # 获取文件信息
            stat = os.stat(file_path)
            result.summary.file_size = stat.st_size
            result.summary.file_mtime = stat.st_mtime

            # 提取全局信息
            global_info = self._extract_global_info(lines)
            result.summary.device_name = global_info.get("Device_Name", "")
            result.summary.tool_version = global_info.get("bMPToolVersion", "")

            # 解析 FWVersion (优先用带日期的完整版本)
            fw64 = global_info.get("bFWVersion", "")
            if fw64:
                result.summary.fw_version = fw64.strip()
            else:
                fw8 = global_info.get("bFWVersion", "")
                if fw8:
                    result.summary.fw_version = fw8.strip()

            result.summary.flash_id = global_info.get("bFlashID", "")

            # 状态: 解析中
            result.summary.parse_status = "Parsing"

            # 解析 KV 指标
            current_section = "Start_of_test"
            current_cycles = 0
            in_skip_section = False
            skip_section_data: List[str] = []

            for line in lines:
                line = line.rstrip("\r\n")

                # 空行处理
                if not line.strip():
                    continue

                # 检查 Hex Dump Section
                if in_skip_section:
                    if self._is_hex_dump_line(line):
                        skip_section_data.append(line)
                        continue
                    else:
                        # Hex Dump 结束,保存为一条记录
                        if skip_section_data:
                            hex_text = "\n".join(skip_section_data)
                            metric = TestMetric(
                                summary_id=0,  # 待填充
                                section=current_section,
                                cycles=current_cycles,
                                metric_key="HexDump",
                                raw_value=hex_text[:1000],  # 截断过长内容
                                str_value=hex_text,
                                result=result.summary.test_result,
                                created_at=time.time(),
                            )
                            result.metrics.append(metric)
                            skip_section_data = []
                        in_skip_section = False

                # Section Header 检测
                section_match = self.SECTION_PATTERN.match(line.strip())
                if section_match:
                    current_section = section_match.group(1)
                    logger.debug(f"进入 Section: {current_section}")

                    # 检查是否需要跳过的 Section
                    if self._is_skip_section(current_section):
                        in_skip_section = True
                        logger.debug(f"跳过 Section 内容: {current_section}")

                    continue

                # Cycles 行检测
                cycles_match = self.CYCLES_PATTERN.match(line.strip())
                if cycles_match:
                    current_cycles = int(cycles_match.group(1))
                    result.summary.test_cycles = current_cycles
                    logger.debug(f"测试循环: {current_cycles}")
                    continue

                # 结果行检测
                result_match = self.RESULT_PATTERN.search(line)
                if result_match:
                    section_result = result_match.group(1)
                    # 如果是最后一个 Result,更新全局结果
                    result.summary.test_result = section_result
                    continue

                # KV 行解析
                kv_match = self.KV_PATTERN.match(line)
                if kv_match:
                    key = self._normalize_key(kv_match.group(1))
                    raw_value = kv_match.group(2).strip()
                    num_value, str_value, hex_value = self._convert_value(raw_value)

                    metric = TestMetric(
                        summary_id=0,  # 待填充
                        section=current_section,
                        cycles=current_cycles,
                        metric_key=key,
                        raw_value=raw_value,
                        num_value=num_value,
                        str_value=str_value,
                        hex_value=hex_value,
                        result="",  # 结果由 Section 的 Result 行确定
                        created_at=time.time(),
                    )
                    result.metrics.append(metric)

            # 处理末尾的 Hex Dump
            if in_skip_section and skip_section_data:
                hex_text = "\n".join(skip_section_data)
                metric = TestMetric(
                    summary_id=0,
                    section=current_section,
                    cycles=current_cycles,
                    metric_key="HexDump",
                    raw_value=hex_text[:1000],
                    str_value=hex_text,
                    result=result.summary.test_result,
                    created_at=time.time(),
                )
                result.metrics.append(metric)

            # 解析成功
            result.summary.parse_status = "Success"
            result.summary.parse_time = time.time() - start_time
            result.success = True

            logger.info(
                f"解析成功: {result.summary.file_name}, "
                f"提取 {len(result.metrics)} 个指标, "
                f"耗时 {result.summary.parse_time:.2f}s"
            )

        except Exception as e:
            # 解析失败
            result.success = False
            result.error_message = str(e)
            result.summary.parse_status = "Failed"
            result.summary.parse_error = str(e)
            result.summary.parse_time = time.time() - start_time

            logger.error(f"解析失败: {file_path}, 错误: {e}")

            # 添加错误日志
            result.logs.append(ParseLog(
                file_name=result.summary.file_name,
                log_level="ERROR",
                message=f"解析失败: {e}",
                created_at=time.time(),
            ))

        return result

    def _is_file_changed(self, file_path: str, summary: TestSummary) -> bool:
        """
        判断文件是否已变更(用于增量解析)。

        Args:
            file_path: 文件路径
            summary: 已存在的记录

        Returns:
            文件是否变更
        """
        if not os.path.exists(file_path):
            return False

        stat = os.stat(file_path)
        # 比较文件大小和修改时间
        return stat.st_size != summary.file_size or stat.st_mtime != summary.file_mtime

    def parse_and_save(self, file_path: str) -> ParseResult:
        """
        解析日志文件并保存到数据库。

        Args:
            file_path: 日志文件路径

        Returns:
            ParseResult 解析结果
        """
        result = self.parse_file(file_path)

        # 保存到数据库
        with self.db.transaction() as conn:
            cursor = conn.cursor()

            # 1. 检查是否已存在记录
            existing = cursor.execute(
                "SELECT id, file_size, file_mtime FROM test_summary WHERE file_path = ?",
                (file_path,)
            ).fetchone()

            summary_id: int

            if existing:
                # 文件已存在,检查是否变更
                summary_id = existing["id"]
                if not self._is_file_changed(file_path, TestSummary.from_row(existing)):
                    logger.info(f"文件未变更,跳过: {file_path}")
                    result.summary.id = summary_id
                    return result

                # 文件已变更,更新记录
                result.summary.id = summary_id
                cursor.execute("""
                    UPDATE test_summary SET
                        file_size = ?, file_mtime = ?, device_name = ?, fw_version = ?,
                        tool_version = ?, flash_id = ?, test_cycles = ?, test_result = ?,
                        parse_status = ?, parse_error = ?, parse_time = ?, updated_at = ?
                    WHERE id = ?
                """, (
                    result.summary.file_size, result.summary.file_mtime,
                    result.summary.device_name, result.summary.fw_version,
                    result.summary.tool_version, result.summary.flash_id,
                    result.summary.test_cycles, result.summary.test_result,
                    result.summary.parse_status, result.summary.parse_error,
                    result.summary.parse_time, result.summary.created_at,
                    summary_id
                ))

                # 删除旧的指标记录
                cursor.execute("DELETE FROM test_metrics WHERE summary_id = ?", (summary_id,))
                logger.info(f"文件已更新,重新解析: {file_path}")
            else:
                # 新文件,插入记录
                cursor.execute("""
                    INSERT INTO test_summary (
                        file_name, file_path, file_size, file_mtime,
                        device_name, fw_version, tool_version, flash_id,
                        test_cycles, test_result, parse_status, parse_error,
                        parse_time, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, result.summary.to_tuple())
                summary_id = cursor.lastrowid
                result.summary.id = summary_id
                logger.info(f"新增文件: {file_path}")

            # 2. 插入指标记录
            for metric in result.metrics:
                metric.summary_id = summary_id
                cursor.execute("""
                    INSERT INTO test_metrics (
                        summary_id, section, cycles, metric_key, raw_value,
                        num_value, str_value, hex_value, result, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, metric.to_tuple())

            # 3. 插入解析日志
            for log in result.logs:
                log.summary_id = summary_id
                cursor.execute("""
                    INSERT INTO parse_logs (summary_id, file_name, log_level, message, created_at)
                    VALUES (?, ?, ?, ?, ?)
                """, log.to_tuple())

        return result

    def parse_directory(self, directory: str, pattern: str = "*.txt") -> List[ParseResult]:
        """
        解析目录下所有匹配的日志文件。

        Args:
            directory: 目录路径
            pattern: 文件匹配模式

        Returns:
            解析结果列表
        """
        import glob

        results = []
        search_pattern = os.path.join(directory, pattern)

        for file_path in glob.glob(search_pattern):
            # 跳过隐藏文件和非日志文件
            basename = os.path.basename(file_path)
            if basename.startswith("."):
                continue

            try:
                result = self.parse_and_save(file_path)
                results.append(result)
            except Exception as e:
                logger.error(f"解析文件失败: {file_path}, 错误: {e}")
                results.append(ParseResult(
                    summary=TestSummary(file_path=file_path, file_name=basename),
                    success=False,
                    error_message=str(e),
                ))

        return results


def parse_logs(
    directory: Optional[str] = None,
    file_path: Optional[str] = None,
    db_path: Optional[str] = None,
) -> List[ParseResult]:
    """
    便捷函数: 解析日志文件或目录。

    Args:
        directory: 监控目录路径
        file_path: 单个文件路径
        db_path: 数据库文件路径

    Returns:
        解析结果列表
    """
    parser = LogParser(db=get_database(db_path) if db_path else None)

    if file_path:
        return [parser.parse_and_save(file_path)]
    elif directory:
        return parser.parse_directory(directory)
    else:
        config = load_config()
        return parser.parse_directory(config.monitor.directory)
