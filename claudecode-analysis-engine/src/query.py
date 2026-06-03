# -*- coding: utf-8 -*-
"""
查询接口模块

提供数据查询、对比分析、曲线数据提取等功能。
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

from .database import Database, get_database
from .models import TestMetric, TestSummary

logger = logging.getLogger(__name__)


class QueryBuilder:
    """查询构建器"""

    def __init__(self, db: Optional[Database] = None):
        """
        初始化查询构建器。

        Args:
            db: 数据库实例
        """
        self.db = db or get_database()

    # ==================== 基础查询 ====================

    def get_all_summaries(
        self,
        device_name: Optional[str] = None,
        fw_version: Optional[str] = None,
        parse_status: Optional[str] = None,
        test_result: Optional[str] = None,
    ) -> List[TestSummary]:
        """
        获取测试摘要列表。

        Args:
            device_name: 设备名称筛选
            fw_version: 固件版本筛选
            parse_status: 解析状态筛选
            test_result: 测试结果筛选

        Returns:
            TestSummary 列表
        """
        sql = "SELECT * FROM test_summary WHERE 1=1"
        params: List[Any] = []

        if device_name:
            sql += " AND device_name LIKE ?"
            params.append(f"%{device_name}%")
        if fw_version:
            sql += " AND fw_version LIKE ?"
            params.append(f"%{fw_version}%")
        if parse_status:
            sql += " AND parse_status = ?"
            params.append(parse_status)
        if test_result:
            sql += " AND test_result = ?"
            params.append(test_result)

        sql += " ORDER BY created_at DESC"

        rows = self.db.fetchall(sql, tuple(params))
        return [TestSummary.from_row(row) for row in rows]

    def get_summary_by_id(self, summary_id: int) -> Optional[TestSummary]:
        """
        根据 ID 获取测试摘要。

        Args:
            summary_id: 摘要 ID

        Returns:
            TestSummary 或 None
        """
        row = self.db.fetchone(
            "SELECT * FROM test_summary WHERE id = ?",
            (summary_id,)
        )
        return TestSummary.from_row(row) if row else None

    def get_metrics_by_summary(
        self,
        summary_id: int,
        section: Optional[str] = None,
    ) -> List[TestMetric]:
        """
        获取指定摘要的指标。

        Args:
            summary_id: 摘要 ID
            section: Section 筛选

        Returns:
            TestMetric 列表
        """
        sql = "SELECT * FROM test_metrics WHERE summary_id = ?"
        params: List[Any] = [summary_id]

        if section:
            sql += " AND section = ?"
            params.append(section)

        sql += " ORDER BY section, cycles, metric_key"

        rows = self.db.fetchall(sql, tuple(params))
        return [TestMetric.from_row(row) for row in rows]

    # ==================== 指标查询 ====================

    def query_metric(
        self,
        metric_key: str,
        device_name: Optional[str] = None,
        fw_version: Optional[str] = None,
        section: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        查询指定指标的值。

        Args:
            metric_key: 指标键名
            device_name: 设备名称筛选
            fw_version: 固件版本筛选
            section: Section 筛选

        Returns:
            指标列表 (包含设备信息和值)
        """
        sql = """
            SELECT
                s.device_name, s.fw_version, s.test_cycles,
                s.id AS summary_id, m.section, m.cycles,
                m.metric_key, m.raw_value, m.num_value, m.hex_value
            FROM test_summary s
            INNER JOIN test_metrics m ON s.id = m.summary_id
            WHERE m.metric_key = ?
        """
        params: List[Any] = [metric_key]

        if device_name:
            sql += " AND s.device_name LIKE ?"
            params.append(f"%{device_name}%")
        if fw_version:
            sql += " AND s.fw_version LIKE ?"
            params.append(f"%{fw_version}%")
        if section:
            sql += " AND m.section = ?"
            params.append(section)

        sql += " ORDER BY s.created_at DESC"

        rows = self.db.fetchall(sql, tuple(params))
        return [dict(row) for row in rows]

    def get_metric_values(
        self,
        summary_ids: List[int],
        metric_keys: List[str],
    ) -> Dict[int, Dict[str, Any]]:
        """
        批量获取指标的横向对比数据。

        Args:
            summary_ids: 摘要 ID 列表
            metric_keys: 指标键名列表

        Returns:
            {summary_id: {metric_key: value}}
        """
        if not summary_ids or not metric_keys:
            return {}

        # 分别创建 summary_id 和 metric_key 的占位符
        summary_placeholders = ",".join("?" * len(summary_ids))
        key_placeholders = ",".join("?" * len(metric_keys))
        sql = f"""
            SELECT summary_id, metric_key, raw_value, num_value
            FROM test_metrics
            WHERE summary_id IN ({summary_placeholders})
              AND metric_key IN ({key_placeholders})
        """
        params = summary_ids + metric_keys

        rows = self.db.fetchall(sql, tuple(params))

        result: Dict[int, Dict[str, Any]] = {sid: {} for sid in summary_ids}
        for row in rows:
            sid = row["summary_id"]
            key = row["metric_key"]
            result[sid][key] = {
                "raw": row["raw_value"],
                "num": row["num_value"],
            }

        return result

    def compare_section(
        self,
        summary_ids: List[int],
        section: str,
    ) -> Dict[int, List[TestMetric]]:
        """
        按 Section 过滤,批量拉取该模块下所有 KV 进行差异比对。

        Args:
            summary_ids: 摘要 ID 列表
            section: Section 名称

        Returns:
            {summary_id: [TestMetric列表]}
        """
        if not summary_ids:
            return {}

        placeholders = ",".join("?" * len(summary_ids))
        sql = f"""
            SELECT * FROM test_metrics
            WHERE summary_id IN ({placeholders})
              AND section = ?
            ORDER BY metric_key
        """
        params = summary_ids + [section]

        rows = self.db.fetchall(sql, tuple(params))

        result: Dict[int, List[TestMetric]] = {sid: [] for sid in summary_ids}
        for row in rows:
            metric = TestMetric.from_row(row)
            result[metric.summary_id].append(metric)

        return result

    # ==================== 曲线数据查询 ====================

    def get_wear_curve_data(
        self,
        device_names: Optional[List[str]] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        获取磨损曲线数据 (WAI, P/E Cycle, Bad Block 等)。

        Args:
            device_names: 设备名称列表 (为空则查询所有)
            limit: 限制返回条数

        Returns:
            磨损曲线数据列表
        """
        sql = """
            SELECT
                s.device_name, s.id AS summary_id, s.test_cycles,
                s.created_at,
                MAX(CASE WHEN m.metric_key = 'WAI' THEN m.num_value END) AS WAI,
                MAX(CASE WHEN m.metric_key = 'P/E_cycle' THEN m.num_value END) AS PE_cycle,
                MAX(CASE WHEN m.metric_key = 'dwDegreOfwear' THEN m.num_value END) AS degree_of_wear,
                MAX(CASE WHEN m.metric_key = 'dwIncreaseBadBlock' THEN m.num_value END) AS bad_block_count
            FROM test_summary s
            LEFT JOIN test_metrics m ON s.id = m.summary_id
            WHERE s.parse_status = 'Success'
        """
        params: List[Any] = []

        if device_names:
            placeholders = ",".join("?" * len(device_names))
            sql += f" AND s.device_name IN ({placeholders})"
            params.extend(device_names)

        sql += """
            GROUP BY s.id
            ORDER BY s.device_name, s.created_at
            LIMIT ?
        """
        params.append(limit)

        rows = self.db.fetchall(sql, tuple(params))
        return [dict(row) for row in rows]

    def get_ecc_curve_data(
        self,
        device_name: Optional[str] = None,
        summary_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        获取 ECC 曲线数据。

        Args:
            device_name: 设备名称
            summary_id: 摘要 ID (优先)

        Returns:
            ECC 曲线数据列表
        """
        sql = """
            SELECT
                s.device_name, s.id AS summary_id,
                m.metric_key, m.num_value, m.raw_value,
                m.section, m.cycles
            FROM test_summary s
            INNER JOIN test_metrics m ON s.id = m.summary_id
            WHERE m.metric_key LIKE '%ECC%'
              AND s.parse_status = 'Success'
        """
        params: List[Any] = []

        if summary_id:
            sql += " AND s.id = ?"
            params.append(summary_id)
        elif device_name:
            sql += " AND s.device_name LIKE ?"
            params.append(f"%{device_name}%")

        sql += " ORDER BY m.cycles, m.metric_key"

        rows = self.db.fetchall(sql, tuple(params))
        return [dict(row) for row in rows]

    # ==================== 统计分析 ====================

    def get_statistics(
        self,
        metric_key: str,
        section: Optional[str] = None,
    ) -> Dict[str, float]:
        """
        获取指标的统计信息。

        Args:
            metric_key: 指标键名
            section: Section 筛选

        Returns:
            统计信息 {min, max, avg, count}
        """
        sql = """
            SELECT
                MIN(num_value) AS min_val,
                MAX(num_value) AS max_val,
                AVG(num_value) AS avg_val,
                COUNT(*) AS count
            FROM test_metrics
            WHERE metric_key = ? AND num_value IS NOT NULL
        """
        params: List[Any] = [metric_key]

        if section:
            sql += " AND section = ?"
            params.append(section)

        row = self.db.fetchone(sql, tuple(params))

        if row and row["count"] > 0:
            return {
                "min": row["min_val"] or 0,
                "max": row["max_val"] or 0,
                "avg": row["avg_val"] or 0,
                "count": row["count"],
            }

        return {"min": 0, "max": 0, "avg": 0, "count": 0}

    def get_failed_summary(self) -> List[Dict[str, Any]]:
        """
        获取解析失败或测试失败的记录。

        Returns:
            失败记录列表
        """
        sql = """
            SELECT
                s.id, s.device_name, s.fw_version, s.file_name,
                s.parse_status, s.parse_error, s.test_result,
                s.created_at
            FROM test_summary s
            WHERE s.parse_status = 'Failed' OR s.test_result = 'Fail'
            ORDER BY s.created_at DESC
        """
        rows = self.db.fetchall(sql)
        return [dict(row) for row in rows]

    def get_unique_devices(self) -> List[Dict[str, str]]:
        """
        获取所有设备列表。

        Returns:
            设备列表 [{device_name, fw_version}]
        """
        sql = """
            SELECT DISTINCT device_name, fw_version
            FROM test_summary
            WHERE device_name IS NOT NULL AND device_name != ''
            ORDER BY device_name
        """
        rows = self.db.fetchall(sql)
        return [dict(row) for row in rows]

    def get_unique_sections(self) -> List[str]:
        """
        获取所有 Section 列表。

        Returns:
            Section 名称列表
        """
        sql = """
            SELECT DISTINCT section
            FROM test_metrics
            WHERE section IS NOT NULL
            ORDER BY section
        """
        rows = self.db.fetchall(sql)
        return [row["section"] for row in rows]

    def get_unique_metric_keys(self, section: Optional[str] = None) -> List[str]:
        """
        获取所有指标键名列表。

        Args:
            section: Section 筛选

        Returns:
            指标键名列表
        """
        if section:
            sql = """
                SELECT DISTINCT metric_key
                FROM test_metrics
                WHERE section = ?
                ORDER BY metric_key
            """
            rows = self.db.fetchall(sql, (section,))
        else:
            sql = """
                SELECT DISTINCT metric_key
                FROM test_metrics
                ORDER BY metric_key
            """
            rows = self.db.fetchall(sql)

        return [row["metric_key"] for row in rows]


def get_query(db: Optional[Database] = None) -> QueryBuilder:
    """
    获取查询构建器实例。

    Args:
        db: 数据库实例

    Returns:
        QueryBuilder 实例
    """
    return QueryBuilder(db)