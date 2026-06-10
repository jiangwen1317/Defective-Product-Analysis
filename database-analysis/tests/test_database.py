"""
数据库层集成测试

覆盖 schema 初始化、DatabaseConnection、MetricsRepository 的全部 CRUD 操作，
以及解析→入库→查询的端到端流程。
"""
import json

import pytest
import sqlite3

from database import DatabaseConnection, MetricsRepository
from schema import init_database


# ================================================================
# Schema 初始化
# ================================================================

class TestSchemaInit:
    """测试数据库建表建索引和迁移。"""

    def test_tables_created(self, tmp_db):
        db, _ = tmp_db
        with db.connect() as conn:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
            table_names = {row[0] for row in tables}
            assert "test_summary" in table_names
            assert "test_metrics" in table_names
            assert "process_log" in table_names

    def test_indexes_created(self, tmp_db):
        db, _ = tmp_db
        with db.connect() as conn:
            indexes = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"
            ).fetchall()
            assert len(indexes) >= 10

    def test_init_idempotent(self, tmp_db):
        """重复调用 init_database 不应报错。"""
        db, _ = tmp_db
        with db.connect() as conn:
            init_database(conn)  # 第二次调用
            init_database(conn)  # 第三次调用


# ================================================================
# DatabaseConnection
# ================================================================

class TestDatabaseConnection:
    """测试连接管理器。"""

    def test_connect_and_commit(self, tmp_db):
        db, _ = tmp_db
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO test_summary (file_name, file_path, file_size, file_mtime) "
                "VALUES (?, ?, ?, ?)",
                ("test.txt", "/tmp/test.txt", 100, 1000.0),
            )
        # 验证已提交
        with db.connect() as conn:
            row = conn.execute("SELECT COUNT(*) FROM test_summary").fetchone()
            assert row[0] == 1

    def test_connect_rollback_on_error(self, tmp_db):
        db, _ = tmp_db
        with pytest.raises(ValueError):
            with db.connect() as conn:
                conn.execute(
                    "INSERT INTO test_summary (file_name, file_path, file_size, file_mtime) "
                    "VALUES (?, ?, ?, ?)",
                    ("test.txt", "/tmp/test.txt", 100, 1000.0),
                )
                raise ValueError("模拟异常")
        # 验证已回滚
        with db.connect() as conn:
            row = conn.execute("SELECT COUNT(*) FROM test_summary").fetchone()
            assert row[0] == 0

    def test_row_factory(self, tmp_db):
        db, _ = tmp_db
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO test_summary (file_name, file_path, file_size, file_mtime) "
                "VALUES (?, ?, ?, ?)",
                ("test.txt", "/tmp/test.txt", 100, 1000.0),
            )
        with db.connect() as conn:
            row = conn.execute("SELECT * FROM test_summary").fetchone()
            # row_factory 为 sqlite3.Row，支持按列名访问
            assert row["file_name"] == "test.txt"


# ================================================================
# MetricsRepository - 写入
# ================================================================

class TestRepositoryInsert:
    """测试 Repository 的写入操作。"""

    def test_insert_summary_returns_id(self, tmp_db):
        db, repo = tmp_db
        with db.connect() as conn:
            sid = repo.insert_summary(
                conn,
                file_name="test.txt",
                file_path="/tmp/test.txt",
                file_size=100,
                file_mtime=1000.0,
                device_name="DM3720",
            )
            assert sid is not None
            assert isinstance(sid, int)
            assert sid > 0

    def test_insert_metrics_batch(self, tmp_db):
        db, repo = tmp_db
        with db.connect() as conn:
            sid = repo.insert_summary(
                conn,
                file_name="test.txt",
                file_path="/tmp/test.txt",
                file_size=100,
                file_mtime=1000.0,
            )
            metrics = [
                ("header", "WAI", "WAI", "161.136", 161.136, "float", None, None),
                ("header", "Wear", "wSLCMinPECycle", "0x0", 0.0, "hex", None, None),
            ]
            repo.insert_metrics_batch(conn, sid, metrics)

        with db.connect() as conn:
            rows = repo.get_metrics(conn, summary_id=sid)
            assert len(rows) == 2

    def test_insert_metrics_batch_empty(self, tmp_db):
        """空列表不应报错。"""
        db, repo = tmp_db
        with db.connect() as conn:
            repo.insert_metrics_batch(conn, 1, [])

    def test_insert_process_log(self, tmp_db):
        db, repo = tmp_db
        with db.connect() as conn:
            # 先插入 summary 以满足外键约束
            sid = repo.insert_summary(
                conn,
                file_name="test.txt",
                file_path="/tmp/test.txt",
                file_size=100,
                file_mtime=1000.0,
            )
            repo.insert_process_log(
                conn,
                file_path="/tmp/test.txt",
                file_size=100,
                file_mtime=1000.0,
                action="parsed",
                summary_id=sid,
            )
        with db.connect() as conn:
            logs = repo.get_all_process_logs(conn)
            assert len(logs) == 1
            assert logs[0]["action"] == "parsed"

    def test_insert_process_log_without_summary(self, tmp_db):
        """summary_id 为 None 时也应正常插入。"""
        db, repo = tmp_db
        with db.connect() as conn:
            repo.insert_process_log(
                conn,
                file_path="/tmp/test.txt",
                file_size=100,
                file_mtime=1000.0,
                action="failed",
                error_message="解析异常",
            )
        with db.connect() as conn:
            logs = repo.get_all_process_logs(conn)
            assert len(logs) == 1
            assert logs[0]["error_message"] == "解析异常"


# ================================================================
# MetricsRepository - 查询
# ================================================================

class TestRepositoryQuery:
    """测试 Repository 的查询操作。"""

    @pytest.fixture(autouse=True)
    def _seed_data(self, tmp_db):
        """预置两条测试记录。"""
        db, repo = tmp_db
        self.db = db
        self.repo = repo

        with db.connect() as conn:
            self.sid1 = repo.insert_summary(
                conn,
                file_name="log1.txt",
                file_path="/tmp/log1.txt",
                file_size=100,
                file_mtime=1000.0,
                device_name="DM3720.026.04",
                fw_version="V3.2.9",
                overall_result="Pass",
                controller="600",
                capacity_mb=59680,
                wai=161.136,
            )
            self.sid2 = repo.insert_summary(
                conn,
                file_name="log2.txt",
                file_path="/tmp/log2.txt",
                file_size=200,
                file_mtime=2000.0,
                device_name="DM3720.033.07",
                fw_version="V2.3.20",
                overall_result="Fail",
                fail_sections=json.dumps(["Wear_Detection"]),
                controller="600",
                capacity_mb=59680,
                wai=149.2,
            )
            metrics1 = [
                ("header", "WAI", "WAI", "161.136", 161.136, "float", None, None),
            ]
            metrics2 = [
                ("header", "WAI", "WAI", "149.2", 149.2, "float", None, None),
                ("Wear_Detection", "wSLCMinPECycle", "wSLCMinPECycle", "0", 0.0, "decimal", None, None),
            ]
            repo.insert_metrics_batch(conn, self.sid1, metrics1)
            repo.insert_metrics_batch(conn, self.sid2, metrics2)

    def test_get_summaries_all(self):
        with self.db.connect() as conn:
            rows = self.repo.get_summaries(conn)
            assert len(rows) == 2

    def test_get_summaries_filter_device(self):
        with self.db.connect() as conn:
            rows = self.repo.get_summaries(conn, device_name="DM3720.026.04")
            assert len(rows) == 1
            assert rows[0]["device_name"] == "DM3720.026.04"

    def test_get_summaries_filter_result(self):
        with self.db.connect() as conn:
            rows = self.repo.get_summaries(conn, overall_result="Fail")
            assert len(rows) == 1
            assert rows[0]["overall_result"] == "Fail"

    def test_get_summaries_filter_fw(self):
        with self.db.connect() as conn:
            rows = self.repo.get_summaries(conn, fw_version="V3.2.9")
            assert len(rows) == 1

    def test_get_summaries_filter_controller(self):
        with self.db.connect() as conn:
            rows = self.repo.get_summaries(conn, controller="600")
            assert len(rows) == 2

    def test_get_summaries_limit(self):
        with self.db.connect() as conn:
            rows = self.repo.get_summaries(conn, limit=1)
            assert len(rows) == 1

    def test_get_summaries_offset(self):
        with self.db.connect() as conn:
            rows = self.repo.get_summaries(conn, limit=1, offset=1)
            assert len(rows) == 1

    def test_get_metrics_by_summary_id(self):
        with self.db.connect() as conn:
            rows = self.repo.get_metrics(conn, summary_id=self.sid2)
            assert len(rows) == 2

    def test_get_metrics_by_section(self):
        with self.db.connect() as conn:
            rows = self.repo.get_metrics(
                conn, summary_id=self.sid2, section="Wear_Detection"
            )
            assert len(rows) == 1

    def test_get_metrics_by_key(self):
        with self.db.connect() as conn:
            rows = self.repo.get_metrics(conn, metric_key="WAI")
            assert len(rows) == 2

    def test_get_fail_summary(self):
        with self.db.connect() as conn:
            rows = self.repo.get_fail_summary(conn)
            assert len(rows) == 1
            assert rows[0]["overall_result"] == "Fail"

    def test_compare_metrics(self):
        with self.db.connect() as conn:
            rows = self.repo.compare_metrics(
                conn, [self.sid1, self.sid2], section="header"
            )
            assert len(rows) >= 2

    def test_compare_metrics_empty_ids(self):
        with self.db.connect() as conn:
            rows = self.repo.compare_metrics(conn, [])
            assert rows == []

    def test_get_metric_values_across_devices(self):
        with self.db.connect() as conn:
            rows = self.repo.get_metric_values_across_devices(
                conn, metric_key="WAI"
            )
            assert len(rows) == 2


# ================================================================
# 增量判断与删除
# ================================================================

class TestIncrementalAndDelete:
    """测试增量判断和按文件名删除。"""

    def test_is_file_processed_true(self, tmp_db):
        db, repo = tmp_db
        with db.connect() as conn:
            repo.insert_process_log(
                conn,
                file_path="/tmp/test.txt",
                file_size=100,
                file_mtime=1000.0,
                action="parsed",
            )
        with db.connect() as conn:
            assert repo.is_file_processed(conn, "/tmp/test.txt", 100, 1000.0) is True

    def test_is_file_processed_false_different_mtime(self, tmp_db):
        db, repo = tmp_db
        with db.connect() as conn:
            repo.insert_process_log(
                conn,
                file_path="/tmp/test.txt",
                file_size=100,
                file_mtime=1000.0,
                action="parsed",
            )
        with db.connect() as conn:
            assert repo.is_file_processed(conn, "/tmp/test.txt", 100, 2000.0) is False

    def test_is_file_processed_false_failed_action(self, tmp_db):
        db, repo = tmp_db
        with db.connect() as conn:
            repo.insert_process_log(
                conn,
                file_path="/tmp/test.txt",
                file_size=100,
                file_mtime=1000.0,
                action="failed",
            )
        with db.connect() as conn:
            assert repo.is_file_processed(conn, "/tmp/test.txt", 100, 1000.0) is False

    def test_delete_summary_by_filename(self, tmp_db):
        db, repo = tmp_db
        with db.connect() as conn:
            sid = repo.insert_summary(
                conn,
                file_name="test.txt",
                file_path="/tmp/test.txt",
                file_size=100,
                file_mtime=1000.0,
            )
            metrics = [
                ("header", "WAI", "WAI", "161.136", 161.136, "float", None, None),
            ]
            repo.insert_metrics_batch(conn, sid, metrics)

        with db.connect() as conn:
            deleted = repo.delete_summary_by_filename(conn, "test.txt")
            assert deleted is True

        # 验证主表和指标均已删除（CASCADE）
        with db.connect() as conn:
            rows = repo.get_summaries(conn)
            assert len(rows) == 0
            metrics = repo.get_metrics(conn, summary_id=sid)
            assert len(metrics) == 0

    def test_delete_summary_nonexistent(self, tmp_db):
        db, repo = tmp_db
        with db.connect() as conn:
            deleted = repo.delete_summary_by_filename(conn, "no_such_file.txt")
            assert deleted is False


# ================================================================
# 端到端：解析 → 入库 → 查询
# ================================================================

class TestEndToEnd:
    """测试从日志解析到数据库查询的完整流程。"""

    def test_parse_and_store_log1(self, tmp_db, result_log1):
        db, repo = tmp_db
        with db.connect() as conn:
            sid = repo.insert_summary(
                conn,
                file_name=result_log1.file_name,
                file_path=result_log1.file_path,
                file_size=result_log1.file_size,
                file_mtime=result_log1.file_mtime,
                device_name=result_log1.device_name,
                fw_version=result_log1.fw_version,
                overall_result=result_log1.overall_result,
                wai=result_log1.wai,
                controller=result_log1.controller,
                capacity_mb=result_log1.capacity_mb,
                capacity_sectors=result_log1.capacity_sectors,
            )
            repo.insert_metrics_batch(
                conn, sid, [m.as_tuple() for m in result_log1.metrics]
            )
            repo.insert_process_log(
                conn,
                file_path=result_log1.file_path,
                file_size=result_log1.file_size,
                file_mtime=result_log1.file_mtime,
                action="parsed",
                summary_id=sid,
            )

        # 查询验证
        with db.connect() as conn:
            summaries = repo.get_summaries(conn, device_name="DM3720.026.04")
            assert len(summaries) == 1
            assert summaries[0]["wai"] == pytest.approx(161.136)

            metrics = repo.get_metrics(conn, summary_id=sid, metric_key="WAI")
            assert len(metrics) >= 1

    def test_reparse_same_file(self, tmp_db, result_log1):
        """模拟文件内容变化后重解析：delete + insert 不冲突。"""
        db, repo = tmp_db

        # 第一次入库
        with db.connect() as conn:
            sid1 = repo.insert_summary(
                conn,
                file_name=result_log1.file_name,
                file_path=result_log1.file_path,
                file_size=result_log1.file_size,
                file_mtime=result_log1.file_mtime,
                device_name=result_log1.device_name,
                overall_result=result_log1.overall_result,
            )

        # 模拟文件变化后重解析（先删除旧记录再插入）
        with db.connect() as conn:
            repo.delete_summary_by_filename(conn, result_log1.file_name)
            sid2 = repo.insert_summary(
                conn,
                file_name=result_log1.file_name,
                file_path=result_log1.file_path,
                file_size=result_log1.file_size + 100,
                file_mtime=result_log1.file_mtime + 10.0,
                device_name=result_log1.device_name,
                overall_result=result_log1.overall_result,
            )

        # 验证新记录存在且 ID 不同
        assert sid2 != sid1
        with db.connect() as conn:
            rows = repo.get_summaries(conn)
            assert len(rows) == 1
            assert rows[0]["file_size"] == result_log1.file_size + 100

    def test_unique_constraint_without_delete(self, tmp_db, result_log1):
        """验证不删除旧记录时重复插入会触发 UNIQUE 冲突。"""
        db, repo = tmp_db

        with db.connect() as conn:
            repo.insert_summary(
                conn,
                file_name=result_log1.file_name,
                file_path=result_log1.file_path,
                file_size=result_log1.file_size,
                file_mtime=result_log1.file_mtime,
            )

        with pytest.raises(sqlite3.IntegrityError):
            with db.connect() as conn:
                repo.insert_summary(
                    conn,
                    file_name=result_log1.file_name,
                    file_path=result_log1.file_path,
                    file_size=result_log1.file_size,
                    file_mtime=result_log1.file_mtime,
                )

    def test_store_both_logs(self, tmp_db, result_log1, result_log2):
        """两个日志文件入库后可按设备名区分查询。"""
        db, repo = tmp_db

        for result in (result_log1, result_log2):
            with db.connect() as conn:
                sid = repo.insert_summary(
                    conn,
                    file_name=result.file_name,
                    file_path=result.file_path,
                    file_size=result.file_size,
                    file_mtime=result.file_mtime,
                    device_name=result.device_name,
                    fw_version=result.fw_version,
                    overall_result=result.overall_result,
                    wai=result.wai,
                )
                repo.insert_metrics_batch(
                    conn, sid, [m.as_tuple() for m in result.metrics]
                )

        with db.connect() as conn:
            all_rows = repo.get_summaries(conn)
            assert len(all_rows) == 2

            device1 = repo.get_summaries(conn, device_name="DM3720.026.04")
            assert len(device1) == 1

            device2 = repo.get_summaries(conn, device_name="DM3720.033.07")
            assert len(device2) == 1
