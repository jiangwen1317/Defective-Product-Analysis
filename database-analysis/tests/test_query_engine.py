"""
查询引擎测试

覆盖 QueryEngine 的趋势分析（批量查询）、异常检测（样本方差）和日期过滤。
"""
import pytest

from database import DatabaseConnection, MetricsRepository
from query_engine import QueryEngine
from schema import init_database


@pytest.fixture()
def seeded_db(tmp_path):
    """创建包含两条记录的数据库并返回 (db, repo, engine, sid1, sid2)。"""
    db_path = str(tmp_path / "test.db")
    db = DatabaseConnection(db_path)
    with db.connect() as conn:
        init_database(conn)
    repo = MetricsRepository(db)
    engine = QueryEngine(db)

    with db.connect() as conn:
        sid1 = repo.insert_summary(
            conn,
            file_name="log1.txt",
            file_path="/tmp/log1.txt",
            file_size=100,
            file_mtime=1000.0,
            device_name="DEV_A",
            fw_version="V1.0",
            overall_result="Pass",
            wai=100.0,
        )
        sid2 = repo.insert_summary(
            conn,
            file_name="log2.txt",
            file_path="/tmp/log2.txt",
            file_size=200,
            file_mtime=2000.0,
            device_name="DEV_B",
            fw_version="V1.0",
            overall_result="Pass",
            wai=200.0,
        )
        # 插入 WAI 指标
        repo.insert_metrics_batch(conn, sid1, [
            ("header", "WAI", "WAI", "100.0", 100.0, "float", None, None),
        ])
        repo.insert_metrics_batch(conn, sid2, [
            ("header", "WAI", "WAI", "200.0", 200.0, "float", None, None),
        ])
        # 插入磨损指标
        repo.insert_metrics_batch(conn, sid1, [
            ("Wear_Detection", "wSLCMinPECycle", "wSLCMinPECycle", "0", 0.0, "decimal", None, None),
            ("Wear_Detection", "wTLCMaxPECycle", "wTLCMaxPECycle", "5", 5.0, "decimal", None, None),
        ])
        repo.insert_metrics_batch(conn, sid2, [
            ("Wear_Detection", "wSLCMinPECycle", "wSLCMinPECycle", "1", 1.0, "decimal", None, None),
            ("Wear_Detection", "wTLCMaxPECycle", "wTLCMaxPECycle", "10", 10.0, "decimal", None, None),
        ])

    return db, repo, engine, sid1, sid2


# ================================================================
# _get_trend_data_batch 批量趋势查询
# ================================================================

class TestBatchTrendData:
    """测试批量趋势数据查询（单次连接优化）。"""

    def test_batch_returns_all_keys(self, seeded_db):
        _, _, engine, _, _ = seeded_db
        results = engine._get_trend_data_batch(["WAI", "wSLCMinPECycle"])
        assert len(results) >= 3  # 2 WAI + 1+ wSLCMinPECycle

    def test_batch_empty_keys(self, seeded_db):
        _, _, engine, _, _ = seeded_db
        results = engine._get_trend_data_batch([])
        assert results == []

    def test_batch_with_section_filter(self, seeded_db):
        _, _, engine, _, _ = seeded_db
        results = engine._get_trend_data_batch(
            ["wSLCMinPECycle", "wTLCMaxPECycle"],
            section="Wear_Detection",
        )
        assert len(results) == 4  # 2 devices × 2 keys
        for r in results:
            assert r["section"] == "Wear_Detection"

    def test_batch_with_device_filter(self, seeded_db):
        _, _, engine, _, _ = seeded_db
        results = engine._get_trend_data_batch(
            ["WAI"],
            device_name="DEV_A",
        )
        assert len(results) == 1
        assert results[0]["device_name"] == "DEV_A"

    def test_wear_trend(self, seeded_db):
        _, _, engine, _, _ = seeded_db
        results = engine.get_wear_trend()
        # 应返回 wSLCMinPECycle 和 wTLCMaxPECycle（其余 5 个 key 无数据）
        keys = {r["metric_key"] for r in results}
        assert "wSLCMinPECycle" in keys
        assert "wTLCMaxPECycle" in keys

    def test_ecc_trend_no_data(self, seeded_db):
        """无 ECC 指标数据时应返回空列表。"""
        _, _, engine, _, _ = seeded_db
        results = engine.get_ecc_trend()
        assert results == []


# ================================================================
# detect_anomalies 异常检测
# ================================================================

class TestDetectAnomalies:
    """测试异常检测（样本方差和边界保护）。"""

    @pytest.fixture()
    def anomaly_engine(self, tmp_path):
        """创建包含特定数值数据的引擎，用于异常检测测试。

        数据：9 个 10.0 + 1 个 50.0
        样本标准差 ≈ 12.65，mean + 2*std ≈ 39.3，50 > 39.3 可被检出。
        """
        db_path = str(tmp_path / "anomaly.db")
        db = DatabaseConnection(db_path)
        with db.connect() as conn:
            init_database(conn)
        repo = MetricsRepository(db)
        engine = QueryEngine(db)

        values = [10.0] * 9 + [50.0]
        for i, val in enumerate(values):
            with db.connect() as conn:
                sid = repo.insert_summary(
                    conn,
                    file_name=f"file_{i}.txt",
                    file_path=f"/tmp/file_{i}.txt",
                    file_size=100 + i,
                    file_mtime=1000.0 + i,
                    device_name=f"DEV_{i}",
                )
                repo.insert_metrics_batch(conn, sid, [
                    ("header", "TestMetric", "TestMetric", str(val), val, "float", None, None),
                ])

        return engine

    def test_fixed_threshold(self, anomaly_engine):
        """固定阈值模式：返回超过阈值的记录。"""
        results = anomaly_engine.detect_anomalies("TestMetric", threshold=30.0)
        assert len(results) == 1
        assert results[0]["num_value"] == 50.0

    def test_statistical_anomaly_detection(self, anomaly_engine):
        """统计模式：样本方差应正确识别异常值。"""
        results = anomaly_engine.detect_anomalies("TestMetric", std_factor=2.0)
        # 50.0 > mean + 2*std ≈ 39.3，应被检出
        assert len(results) >= 1
        assert any(r["num_value"] == 50.0 for r in results)

    def test_anomaly_metadata(self, anomaly_engine):
        """异常记录应包含统计元数据。"""
        results = anomaly_engine.detect_anomalies("TestMetric", std_factor=2.0)
        assert len(results) >= 1
        r = results[0]
        assert "anomaly_threshold" in r
        assert "mean" in r
        assert "std" in r

    def test_single_sample_returns_empty(self, tmp_path):
        """样本数 < 2 时无法计算样本标准差，应返回空列表。"""
        db_path = str(tmp_path / "single.db")
        db = DatabaseConnection(db_path)
        with db.connect() as conn:
            init_database(conn)
        repo = MetricsRepository(db)
        engine = QueryEngine(db)

        with db.connect() as conn:
            sid = repo.insert_summary(
                conn,
                file_name="single.txt",
                file_path="/tmp/single.txt",
                file_size=100,
                file_mtime=1000.0,
            )
            repo.insert_metrics_batch(conn, sid, [
                ("header", "WAI", "WAI", "50.0", 50.0, "float", None, None),
            ])

        # 无 threshold 且 n=1，应返回空
        results = engine.detect_anomalies("WAI")
        assert results == []

    def test_no_data_returns_empty(self, seeded_db):
        """无数据时应返回空列表。"""
        _, _, engine, _, _ = seeded_db
        results = engine.detect_anomalies("NonexistentMetric")
        assert results == []


# ================================================================
# date_to 日期过滤
# ================================================================

class TestDateFilter:
    """测试 date_to 边界处理（使用 date() 函数）。"""

    @pytest.fixture()
    def date_db(self, tmp_path):
        """创建包含不同日期记录的数据库。"""
        db_path = str(tmp_path / "dates.db")
        db = DatabaseConnection(db_path)
        with db.connect() as conn:
            init_database(conn)
        repo = MetricsRepository(db)

        # 手动插入带特定 parsed_at 的记录
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO test_summary "
                "(file_name, file_path, file_size, file_mtime, parsed_at) "
                "VALUES (?, ?, ?, ?, ?)",
                ("jan1.txt", "/tmp/jan1.txt", 100, 1000.0, "2026-01-01 10:30:00"),
            )
            conn.execute(
                "INSERT INTO test_summary "
                "(file_name, file_path, file_size, file_mtime, parsed_at) "
                "VALUES (?, ?, ?, ?, ?)",
                ("jan31.txt", "/tmp/jan31.txt", 200, 2000.0, "2026-01-31 23:59:59"),
            )
            conn.execute(
                "INSERT INTO test_summary "
                "(file_name, file_path, file_size, file_mtime, parsed_at) "
                "VALUES (?, ?, ?, ?, ?)",
                ("feb1.txt", "/tmp/feb1.txt", 300, 3000.0, "2026-02-01 00:00:01"),
            )

        return db, repo

    def test_date_to_includes_end_of_day(self, date_db):
        """date_to='2026-01-31' 应包含当天 23:59:59 的记录。"""
        db, repo = date_db
        with db.connect() as conn:
            rows = repo.get_summaries(conn, date_to="2026-01-31")
            file_names = {r["file_name"] for r in rows}
            assert "jan1.txt" in file_names
            assert "jan31.txt" in file_names
            assert "feb1.txt" not in file_names

    def test_date_from_and_to(self, date_db):
        """同时指定 date_from 和 date_to。"""
        db, repo = date_db
        with db.connect() as conn:
            rows = repo.get_summaries(
                conn, date_from="2026-01-15", date_to="2026-01-31"
            )
            assert len(rows) == 1
            assert rows[0]["file_name"] == "jan31.txt"

    def test_date_to_excludes_next_day(self, date_db):
        """date_to='2026-01-31' 不应包含 2026-02-01 的记录。"""
        db, repo = date_db
        with db.connect() as conn:
            rows = repo.get_summaries(conn, date_to="2026-01-31")
            for r in rows:
                assert not r["parsed_at"].startswith("2026-02")
