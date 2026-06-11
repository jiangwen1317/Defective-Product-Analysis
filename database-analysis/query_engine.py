"""
查询引擎模块

提供 QueryEngine 类，支持：
1. 组合筛选查询（device_name + fw_version + section + metric_key + date_range）
2. 多设备/多周期指标对比
3. 按固件版本对比统计值
4. 趋势数据提取（WAI/PE/BadBlock/ECC）
"""
import logging
from typing import Optional

from database import DatabaseConnection, MetricsRepository

logger = logging.getLogger(__name__)


class QueryEngine:
    """查询与分析引擎。

    封装常用的查询模式，提供灵活的指标筛选、对比和趋势分析功能。
    """

    def __init__(self, db: DatabaseConnection) -> None:
        self._db = db
        self._repo = MetricsRepository(db)

    # ---- 组合筛选查询 ----

    def query_metrics(
        self,
        *,
        device_name: Optional[str] = None,
        fw_version: Optional[str] = None,
        flash_id: Optional[str] = None,
        section: Optional[str] = None,
        metric_key: Optional[str] = None,
        metric_keys: Optional[list[str]] = None,
        overall_result: Optional[str] = None,
        capacity_mb: Optional[int] = None,
        capacity_sectors: Optional[int] = None,
        controller: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict]:
        """组合筛选查询指标数据。

        先按主表条件筛选 summary，再 JOIN metrics 表返回指标详情。

        Args:
            device_name: 设备名过滤。
            fw_version: 固件版本过滤。
            flash_id: Flash ID 精确查询。
            section: Section 名过滤。
            metric_key: 单个指标名过滤。
            metric_keys: 多个指标名过滤（IN 查询）。
            overall_result: 综合结果过滤（Pass/Fail）。
            capacity_mb: 容量 MB 过滤。
            capacity_sectors: 扇区数过滤。
            controller: 主控型号过滤。
            date_from: 起始日期（YYYY-MM-DD）。
            date_to: 截止日期（YYYY-MM-DD）。
            limit: 返回条数上限。

        Returns:
            指标字典列表，包含 summary 和 metrics 字段。
        """
        with self._db.connect() as conn:
            summaries = self._repo.get_summaries(
                conn,
                device_name=device_name,
                fw_version=fw_version,
                flash_id=flash_id,
                overall_result=overall_result,
                capacity_mb=capacity_mb,
                capacity_sectors=capacity_sectors,
                controller=controller,
                date_from=date_from,
                date_to=date_to,
                limit=limit,
            )

            if not summaries:
                return []

            # 批量查询所有 summary 的 metrics（解决 N+1 问题）
            summary_ids = [s["id"] for s in summaries]
            all_metrics = self._repo.get_metrics_by_summary_ids(
                conn,
                summary_ids,
                section=section,
                metric_key=metric_key,
            )

            # 多指标名过滤
            if metric_keys and not metric_key:
                all_metrics = [m for m in all_metrics if m["metric_key"] in metric_keys]

            # 构建 summary_id → summary 的映射
            summary_map = {s["id"]: s for s in summaries}

            results: list[dict] = []
            for m in all_metrics:
                s = summary_map.get(m["summary_id"])
                if s is None:
                    continue
                row = {
                    "summary_id": s["id"],
                    "device_name": s.get("device_name"),
                    "fw_version": s.get("fw_version"),
                    "parsed_at": s.get("parsed_at"),
                    "overall_result": s.get("overall_result"),
                    "section": m["section"],
                    "metric_key": m["metric_key"],
                    "metric_key_raw": m["metric_key_raw"],
                    "raw_value": m["raw_value"],
                    "num_value": m.get("num_value"),
                    "value_type": m["value_type"],
                    "prefix": m.get("prefix"),
                }
                results.append(row)

            return results

    def query_summaries(
        self,
        *,
        device_name: Optional[str] = None,
        fw_version: Optional[str] = None,
        flash_id: Optional[str] = None,
        overall_result: Optional[str] = None,
        capacity_mb: Optional[int] = None,
        capacity_sectors: Optional[int] = None,
        controller: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict]:
        """查询主表摘要记录。

        Args:
            device_name: 设备名过滤。
            fw_version: 固件版本过滤。
            flash_id: Flash ID 精确查询。
            overall_result: 综合结果过滤。
            capacity_mb: 容量 MB 过滤。
            capacity_sectors: 扇区数过滤。
            controller: 主控型号过滤。
            date_from: 起始日期。
            date_to: 截止日期。
            limit: 返回条数上限。

        Returns:
            摘要字典列表。
        """
        with self._db.connect() as conn:
            return self._repo.get_summaries(
                conn,
                device_name=device_name,
                fw_version=fw_version,
                flash_id=flash_id,
                overall_result=overall_result,
                capacity_mb=capacity_mb,
                capacity_sectors=capacity_sectors,
                controller=controller,
                date_from=date_from,
                date_to=date_to,
                limit=limit,
            )

    # ---- 对比分析 ----

    def compare_devices(
        self,
        summary_ids: list[int],
        section: Optional[str] = None,
    ) -> list[dict]:
        """多设备/多周期指标对比。

        将多个 summary_id 的指标按 (section, metric_key) 对齐，
        计算差异和差异百分比。

        Args:
            summary_ids: 待对比的主表 ID 列表。
            section: 可选按 Section 过滤。

        Returns:
            对比结果列表，每项包含各 ID 的值和差异信息。
        """
        with self._db.connect() as conn:
            all_metrics = self._repo.compare_metrics(conn, summary_ids, section=section)

        if not all_metrics:
            return []

        # 按 (section, metric_key_raw) 分组
        from collections import defaultdict
        grouped: dict[str, dict[int, dict]] = defaultdict(dict)
        for m in all_metrics:
            key = f"{m['section']}|{m['metric_key_raw']}"
            grouped[key][m["summary_id"]] = m

        results: list[dict] = []
        for key, sid_map in grouped.items():
            section_name, metric_name = key.split("|", 1)
            row: dict = {
                "section": section_name,
                "metric_key_raw": metric_name,
            }

            values: list[Optional[float]] = []
            for sid in summary_ids:
                if sid in sid_map:
                    m = sid_map[sid]
                    row[f"value_{sid}"] = m["raw_value"]
                    row[f"num_value_{sid}"] = m.get("num_value")
                    values.append(m.get("num_value"))
                else:
                    row[f"value_{sid}"] = "N/A"
                    row[f"num_value_{sid}"] = None
                    values.append(None)

            # 计算差异
            nums = [v for v in values if v is not None]
            if len(nums) >= 2:
                row["diff"] = nums[-1] - nums[0]
                if nums[0] != 0:
                    row["diff_pct"] = round((nums[-1] - nums[0]) / abs(nums[0]) * 100, 2)
                else:
                    row["diff_pct"] = None

            results.append(row)

        return results

    def compare_by_fw_version(
        self,
        fw_version_a: str,
        fw_version_b: str,
        metric_keys: list[str],
        section: Optional[str] = None,
    ) -> list[dict]:
        """按固件版本分组对比指定指标的统计值。

        对每个 metric_key 计算两个固件版本的均值、最大值、最小值。

        Args:
            fw_version_a: 固件版本 A。
            fw_version_b: 固件版本 B。
            metric_keys: 待对比的指标名列表。
            section: 可选 Section 过滤。

        Returns:
            对比结果列表。
        """
        with self._db.connect() as conn:
            results: list[dict] = []

            for key in metric_keys:
                sql = """
                    SELECT s.fw_version,
                           AVG(m.num_value) as avg_val,
                           MAX(m.num_value) as max_val,
                           MIN(m.num_value) as min_val,
                           COUNT(*) as sample_count
                    FROM test_metrics m
                    JOIN test_summary s ON m.summary_id = s.id
                    WHERE m.metric_key = ? AND s.fw_version IN (?, ?)
                """
                params: list = [key, fw_version_a, fw_version_b]
                if section:
                    sql += " AND m.section = ?"
                    params.append(section)
                sql += " GROUP BY s.fw_version"

                rows = conn.execute(sql, params).fetchall()
                for row in rows:
                    results.append({
                        "metric_key": key,
                        "fw_version": row["fw_version"],
                        "avg": row["avg_val"],
                        "max": row["max_val"],
                        "min": row["min_val"],
                        "count": row["sample_count"],
                    })

            return results

    # ---- 趋势分析 ----

    def get_trend_data(
        self,
        metric_key: str,
        *,
        section: Optional[str] = None,
        device_name: Optional[str] = None,
        fw_version: Optional[str] = None,
    ) -> list[dict]:
        """获取指定指标的趋势数据。

        按时间顺序提取某一指标的值，用于绘制趋势图。

        Args:
            metric_key: 指标名。
            section: Section 名（可选）。
            device_name: 设备名（可选）。
            fw_version: 固件版本（可选）。

        Returns:
            趋势数据列表，每项包含 parsed_at, device_name, num_value 等。
        """
        with self._db.connect() as conn:
            sql = """
                SELECT s.device_name, s.fw_version, s.parsed_at, s.overall_result,
                       m.section, m.metric_key_raw, m.raw_value, m.num_value, m.prefix
                FROM test_metrics m
                JOIN test_summary s ON m.summary_id = s.id
                WHERE m.metric_key = ?
            """
            params: list = [metric_key]

            if section:
                sql += " AND m.section = ?"
                params.append(section)
            if device_name:
                sql += " AND s.device_name = ?"
                params.append(device_name)
            if fw_version:
                sql += " AND s.fw_version = ?"
                params.append(fw_version)

            sql += " ORDER BY s.parsed_at ASC"
            rows = conn.execute(sql, params).fetchall()
            return [dict(row) for row in rows]

    def _get_trend_data_batch(
        self,
        metric_keys: list[str],
        *,
        section: Optional[str] = None,
        device_name: Optional[str] = None,
        fw_version: Optional[str] = None,
    ) -> list[dict]:
        """批量获取多个指标的趋势数据（单次连接、单条 SQL）。

        与 get_trend_data 功能相同，但使用 IN 查询合并多个指标，
        避免为每个指标单独创建连接。

        Args:
            metric_keys: 指标名列表。
            section: Section 名（可选）。
            device_name: 设备名（可选）。
            fw_version: 固件版本（可选）。

        Returns:
            趋势数据列表，每项包含 parsed_at, device_name, num_value 等。
        """
        if not metric_keys:
            return []

        with self._db.connect() as conn:
            placeholders = ",".join("?" * len(metric_keys))
            sql = f"""
                SELECT s.device_name, s.fw_version, s.parsed_at, s.overall_result,
                       m.section, m.metric_key, m.metric_key_raw,
                       m.raw_value, m.num_value, m.prefix
                FROM test_metrics m
                JOIN test_summary s ON m.summary_id = s.id
                WHERE m.metric_key IN ({placeholders})
            """
            params: list = list(metric_keys)

            if section:
                sql += " AND m.section = ?"
                params.append(section)
            if device_name:
                sql += " AND s.device_name = ?"
                params.append(device_name)
            if fw_version:
                sql += " AND s.fw_version = ?"
                params.append(fw_version)

            sql += " ORDER BY m.metric_key, s.parsed_at ASC"
            rows = conn.execute(sql, params).fetchall()
            return [dict(row) for row in rows]

    def get_wear_trend(self, device_name: Optional[str] = None) -> list[dict]:
        """获取磨损相关指标趋势（WAI、PE Cycle、Bad Block）。

        使用单次查询批量获取多个磨损指标，避免多次连接开销。

        Args:
            device_name: 设备名（可选）。

        Returns:
            磨损指标趋势数据列表。
        """
        wear_keys = ["WAI", "wSLCMinPECycle", "wSLCMaxPECycle",
                     "wTLCMinPECycle", "wTLCMaxPECycle",
                     "dwIncreaseBadBlock", "wNewBadBlkNum"]

        return self._get_trend_data_batch(
            wear_keys,
            section="Wear_Detection",
            device_name=device_name,
        )

    def get_ecc_trend(self, device_name: Optional[str] = None) -> list[dict]:
        """获取 ECC 相关指标趋势。

        使用单次查询批量获取多个 ECC 指标，避免多次连接开销。

        Args:
            device_name: 设备名（可选）。

        Returns:
            ECC 指标趋势数据列表。
        """
        ecc_keys = ["dwUncorrectableCount", "wLogEdECCFailCnt",
                    "wCRCErrorCnt", "dwCRCErrCnt"]

        return self._get_trend_data_batch(
            ecc_keys,
            device_name=device_name,
        )

    # ---- 异常检测 ----

    def detect_anomalies(
        self,
        metric_key: str,
        *,
        threshold: Optional[float] = None,
        section: Optional[str] = None,
        std_factor: float = 2.0,
    ) -> list[dict]:
        """异常检测。

        指定阈值时返回超过阈值的记录；未指定阈值时基于
        均值 + std_factor * 标准差 自动判定。

        Args:
            metric_key: 指标名。
            threshold: 固定阈值（可选）。
            section: Section 名（可选）。
            std_factor: 标准差倍数（默认 2.0）。

        Returns:
            异常记录列表。
        """
        data = self.get_trend_data(metric_key, section=section)
        numeric_data = [d for d in data if d.get("num_value") is not None]

        if not numeric_data:
            return []

        if threshold is not None:
            return [d for d in numeric_data if d["num_value"] > threshold]

        # 基于统计的异常检测（使用样本方差，n-1）
        values = [d["num_value"] for d in numeric_data]
        n = len(values)

        # 样本数 < 2 时无法计算样本标准差，退化为全量返回空
        if n < 2:
            return []

        mean = sum(values) / n
        variance = sum((v - mean) ** 2 for v in values) / (n - 1)
        std = variance ** 0.5
        anomaly_threshold = mean + std_factor * std

        anomalies = [d for d in numeric_data if d["num_value"] > anomaly_threshold]
        for a in anomalies:
            a["anomaly_threshold"] = round(anomaly_threshold, 4)
            a["mean"] = round(mean, 4)
            a["std"] = round(std, 4)

        return anomalies
