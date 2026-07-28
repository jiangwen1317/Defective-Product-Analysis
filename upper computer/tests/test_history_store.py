"""HistoryStore 测试历史持久化测试。"""

import json
import sqlite3
from contextlib import closing

from storage import HistoryStore


class TestHistoryStoreInit:
    """初始化与建表测试。"""

    def test_creates_db_and_table(self, tmp_path):
        """初始化应创建数据库文件与 test_records 表。"""
        db_path = tmp_path / "data" / "history.db"

        HistoryStore(db_path)

        assert db_path.exists()
        with closing(sqlite3.connect(str(db_path))) as conn:
            names = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )]
        assert "test_records" in names

    def test_init_on_existing_db_is_idempotent(self, tmp_path):
        """对已存在的数据库重复初始化不应报错或丢数据。"""
        db_path = tmp_path / "history.db"
        store = HistoryStore(db_path)
        store.save_record("00", {1: "0000"}, 1.0)

        HistoryStore(db_path)  # 再次初始化

        assert store.load_stats()["total"] == 1


class TestHistoryStoreSaveAndLoad:
    """记录保存与统计恢复测试。"""

    def test_empty_db_stats_are_zero(self, tmp_path):
        """空库统计应全为 0。"""
        store = HistoryStore(tmp_path / "history.db")

        assert store.load_stats() == {"total": 0, "success": 0, "failed": 0}

    def test_save_and_load_stats_roundtrip(self, tmp_path):
        """保存成功/失败会话后，统计应正确恢复。"""
        store = HistoryStore(tmp_path / "history.db")

        store.save_record("00", {1: "0000", 2: "0000"}, 2.5)  # 成功
        store.save_record("00", {1: "0000", 2: "0904"}, 3.0)  # 失败
        store.save_record("00", {1: "EEEE"}, 60.0)            # 失败

        assert store.load_stats() == {"total": 3, "success": 1, "failed": 2}

    def test_empty_results_recorded_as_failed(self, tmp_path):
        """空结果会话（异常中止）应记为失败。"""
        store = HistoryStore(tmp_path / "history.db")

        store.save_record("00", {}, 0.1)

        assert store.load_stats() == {"total": 1, "success": 0, "failed": 1}

    def test_record_fields_written_correctly(self, tmp_path):
        """记录的 bitmask、error_codes、duration_ms 字段应正确。"""
        db_path = tmp_path / "history.db"
        store = HistoryStore(db_path)

        store.save_record("00", {1: "0000", 3: "0904"}, 2.5)

        with closing(sqlite3.connect(str(db_path))) as conn:
            row = conn.execute(
                "SELECT group_id, bitmask, dut_count, error_codes, duration_ms, success "
                "FROM test_records"
            ).fetchone()

        assert row[0] == "00"
        assert row[1] == "10100000"
        assert row[2] == 2
        codes = json.loads(row[3])
        assert codes[0] == "0000"
        assert codes[2] == "0904"
        assert codes[1] == "----"  # 未受测占位
        assert row[4] == 2500
        assert row[5] == 0  # 含非 0000 错误码，记失败
