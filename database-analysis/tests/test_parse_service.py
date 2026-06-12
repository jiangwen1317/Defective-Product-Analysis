"""
ParseService 集成测试

覆盖解析入库服务的完整流程：增量判断、跳过、解析、process_log 记录。
"""
import os

import pytest

from conftest import LOG_FILE_1, LOG_FILE_2
from database import DatabaseConnection, MetricsRepository
from parse_service import ParseService
from schema import init_database


@pytest.fixture()
def parse_env(tmp_path):
    """创建 ParseService 测试环境。"""
    db_path = str(tmp_path / "test.db")
    db = DatabaseConnection(db_path)
    with db.connect() as conn:
        init_database(conn)
    repo = MetricsRepository(db)
    service = ParseService(db, repo)
    return db, repo, service


class TestParseServiceIntegration:
    """ParseService 端到端集成测试。"""

    def test_parse_single_file(self, parse_env):
        """解析单个文件应成功入库。"""
        db, repo, service = parse_env
        logs: list[str] = []

        result = service.process_file(LOG_FILE_1, on_log=logs.append)

        assert result.action == "parsed"
        assert result.summary_id is not None
        assert result.metric_count > 0
        assert result.overall_result == "Pass"

        # 验证数据库中有数据
        with db.connect() as conn:
            summaries = repo.get_summaries(conn)
            assert len(summaries) == 1
            assert summaries[0]["device_name"] == "DM3720.026.04"

    def test_parse_same_file_twice_skips(self, parse_env):
        """重复解析相同文件应跳过（增量判断）。"""
        db, repo, service = parse_env

        # 第一次解析
        result1 = service.process_file(LOG_FILE_1)
        assert result1.action == "parsed"

        # 第二次解析应跳过
        result2 = service.process_file(LOG_FILE_1)
        assert result2.action == "skipped"

        # 验证只有一条记录
        with db.connect() as conn:
            summaries = repo.get_summaries(conn)
            assert len(summaries) == 1

    def test_parse_nonexistent_file(self, parse_env):
        """解析不存在的文件应返回 failed。"""
        _, _, service = parse_env

        result = service.process_file("/nonexistent/path/file.txt")
        assert result.action == "failed"
        assert "文件访问失败" in result.error

    def test_process_files_batch(self, parse_env):
        """批量处理多个文件。"""
        db, repo, service = parse_env
        logs: list[str] = []

        batch = service.process_files(
            [LOG_FILE_1, LOG_FILE_2],
            on_log=logs.append,
        )

        assert batch.success == 2
        assert batch.failed == 0
        assert batch.skipped == 0
        assert batch.total == 2

        with db.connect() as conn:
            summaries = repo.get_summaries(conn)
            assert len(summaries) == 2

    def test_process_files_with_invalid(self, parse_env):
        """批量处理中包含无效文件，有效文件仍应成功。"""
        _, _, service = parse_env

        batch = service.process_files(
            [LOG_FILE_1, "/nonexistent/file.txt"],
        )

        assert batch.success == 1
        assert batch.failed == 1
        assert batch.skipped == 0

    def test_process_log_records_parsed_action(self, parse_env):
        """解析成功后 process_log 应记录 parsed 动作。"""
        db, repo, service = parse_env

        service.process_file(LOG_FILE_1)

        with db.connect() as conn:
            logs = repo.get_all_process_logs(conn)
            parsed_logs = [l for l in logs if l["action"] == "parsed"]
            assert len(parsed_logs) >= 1

    def test_clear_then_reparse(self, parse_env):
        """清空数据库后可重新解析之前已处理的文件。"""
        db, repo, service = parse_env

        # 第一次解析
        result1 = service.process_file(LOG_FILE_1)
        assert result1.action == "parsed"

        # 清空数据库（DROP + 重建）
        with db.connect() as conn:
            conn.execute("PRAGMA foreign_keys=OFF")
            conn.execute("DROP TABLE IF EXISTS process_log")
            conn.execute("DROP TABLE IF EXISTS test_metrics")
            conn.execute("DROP TABLE IF EXISTS test_summary")
            init_database(conn)
            conn.execute("PRAGMA foreign_keys=ON")

        # 验证已清空
        with db.connect() as conn:
            assert len(repo.get_summaries(conn)) == 0
            assert len(repo.get_all_process_logs(conn)) == 0

        # 重新解析应成功（不再被跳过）
        result2 = service.process_file(LOG_FILE_1)
        assert result2.action == "parsed"
        assert result2.summary_id is not None

        with db.connect() as conn:
            summaries = repo.get_summaries(conn)
            assert len(summaries) == 1
