"""
测试共享 fixture

提供临时数据库、参考日志解析结果等公共资源。
"""
import os
import sys
import tempfile

import pytest

# 将项目根目录加入 Python 路径，使测试可导入业务模块
_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_DIR not in sys.path:
    sys.path.insert(0, _PROJECT_DIR)

from database import DatabaseConnection, MetricsRepository
from log_parser import LogParser
from schema import init_database

# 参考日志文件路径
_LOG_DIR = os.path.join(_PROJECT_DIR, "测试参考日志")
LOG_FILE_1 = os.path.join(
    _LOG_DIR, "DM3720.026.04_1_8807_4348_2026-06-02 20-45-48 1554.txt"
)
LOG_FILE_2 = os.path.join(
    _LOG_DIR, "DM3720.033.07_1_8807_4348_2026-06-03 14-01-06 0012.txt"
)


@pytest.fixture()
def tmp_db(tmp_path):
    """创建临时数据库，返回 (DatabaseConnection, MetricsRepository) 元组。"""
    db_path = str(tmp_path / "test.db")
    db = DatabaseConnection(db_path)
    with db.connect() as conn:
        init_database(conn)
    repo = MetricsRepository(db)
    return db, repo


@pytest.fixture()
def parser():
    """返回 LogParser 实例。"""
    return LogParser()


@pytest.fixture()
def result_log1(parser):
    """解析参考日志 1（DM3720.026.04，Pass）。"""
    return parser.parse_file(LOG_FILE_1)


@pytest.fixture()
def result_log2(parser):
    """解析参考日志 2（DM3720.033.07，Pass）。"""
    return parser.parse_file(LOG_FILE_2)
