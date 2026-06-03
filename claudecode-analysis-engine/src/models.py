# -*- coding: utf-8 -*-
"""
数据模型模块

定义 test_summary 和 test_metrics 的数据结构。
"""

from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class TestSummary:
    """测试摘要模型 (对应 test_summary 表)"""
    id: Optional[int] = None
    file_name: str = ""
    file_path: str = ""
    file_size: int = 0
    file_mtime: float = 0.0

    device_name: str = ""
    fw_version: str = ""
    tool_version: str = ""
    flash_id: str = ""

    test_cycles: int = 0
    test_result: str = ""  # Pass/Fail

    parse_status: str = "Pending"  # Pending/Success/Failed
    parse_error: str = ""
    parse_time: float = 0.0

    created_at: float = 0.0
    updated_at: Optional[float] = None

    def to_tuple(self) -> tuple:
        """转换为数据库插入元组"""
        return (
            self.file_name,
            self.file_path,
            self.file_size,
            self.file_mtime,
            self.device_name,
            self.fw_version,
            self.tool_version,
            self.flash_id,
            self.test_cycles,
            self.test_result,
            self.parse_status,
            self.parse_error,
            self.parse_time,
            self.created_at,
        )

    @classmethod
    def from_row(cls, row) -> "TestSummary":
        """从数据库行创建对象"""
        return cls(
            id=row["id"],
            file_name=row["file_name"],
            file_path=row["file_path"],
            file_size=row["file_size"],
            file_mtime=row["file_mtime"],
            device_name=row["device_name"] or "",
            fw_version=row["fw_version"] or "",
            tool_version=row["tool_version"] or "",
            flash_id=row["flash_id"] or "",
            test_cycles=row["test_cycles"] or 0,
            test_result=row["test_result"] or "",
            parse_status=row["parse_status"] or "Pending",
            parse_error=row["parse_error"] or "",
            parse_time=row["parse_time"] or 0.0,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


@dataclass
class TestMetric:
    """测试指标模型 (对应 test_metrics 表)"""
    id: Optional[int] = None
    summary_id: int = 0

    section: str = ""       # Section 名称
    cycles: int = 0         # 测试循环次数

    metric_key: str = ""    # 指标键名
    raw_value: str = ""     # 原始字符串值

    num_value: Optional[float] = None  # 数值
    str_value: str = ""     # 字符串值(用于纯文本)
    hex_value: str = ""     # 十六进制原始值

    result: str = ""        # 该 Section 的测试结果 Pass/Fail

    created_at: float = 0.0

    def to_tuple(self) -> tuple:
        """转换为数据库插入元组"""
        return (
            self.summary_id,
            self.section,
            self.cycles,
            self.metric_key,
            self.raw_value,
            self.num_value,
            self.str_value,
            self.hex_value,
            self.result,
            self.created_at,
        )

    @classmethod
    def from_row(cls, row) -> "TestMetric":
        """从数据库行创建对象"""
        return cls(
            id=row["id"],
            summary_id=row["summary_id"],
            section=row["section"] or "",
            cycles=row["cycles"] or 0,
            metric_key=row["metric_key"] or "",
            raw_value=row["raw_value"] or "",
            num_value=row["num_value"],
            str_value=row["str_value"] or "",
            hex_value=row["hex_value"] or "",
            result=row["result"] or "",
            created_at=row["created_at"],
        )


@dataclass
class ParseLog:
    """解析日志模型 (对应 parse_logs 表)"""
    id: Optional[int] = None
    summary_id: Optional[int] = None
    file_name: str = ""
    log_level: str = "INFO"  # INFO/WARNING/ERROR
    message: str = ""
    created_at: float = 0.0

    def to_tuple(self) -> tuple:
        """转换为数据库插入元组"""
        return (
            self.summary_id,
            self.file_name,
            self.log_level,
            self.message,
            self.created_at,
        )


@dataclass
class ParseResult:
    """解析结果封装"""
    summary: TestSummary
    metrics: List[TestMetric] = field(default_factory=list)
    logs: List[ParseLog] = field(default_factory=list)
    success: bool = True
    error_message: str = ""
