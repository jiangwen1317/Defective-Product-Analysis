# -*- coding: utf-8 -*-
"""
claudecode-analysis-engine

EMMC 测试日志数据库分析系统
"""

from .config import Config, load_config
from .database import Database, get_database
from .export import ReportExporter, export_report
from .models import ParseLog, ParseResult, TestMetric, TestSummary
from .parser import LogParser, parse_logs
from .query import QueryBuilder, get_query

__version__ = "1.0.0"

__all__ = [
    "Config",
    "load_config",
    "Database",
    "get_database",
    "ReportExporter",
    "export_report",
    "ParseLog",
    "ParseResult",
    "TestMetric",
    "TestSummary",
    "LogParser",
    "parse_logs",
    "QueryBuilder",
    "get_query",
]
