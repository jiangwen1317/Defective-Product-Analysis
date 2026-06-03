"""
SQLite 连接管理与数据访问层

提供 DatabaseConnection 上下文管理器，以及 MetricsRepository 封装所有 CRUD 操作。
"""
import sqlite3
import logging
from contextlib import contextmanager
from typing import Optional

logger = logging.getLogger(__name__)


class DatabaseConnection:
    """SQLite 连接管理器（上下文管理器模式）。

    使用 WAL 模式支持并发读，启用外键约束。
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    @contextmanager
    def connect(self):
        """上下文管理器，自动管理连接生命周期。

        Yields:
            sqlite3.Connection: 配置好的数据库连接。
        """
        conn = sqlite3.connect(self._db_path)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


class MetricsRepository:
    """指标数据的 CRUD 操作封装。"""

    def __init__(self, db: DatabaseConnection) -> None:
        self._db = db

    # ---- 写入 ----

    def insert_summary(
        self,
        conn: sqlite3.Connection,
        *,
        file_name: str,
        file_path: str,
        file_size: int,
        file_mtime: float,
        device_name: Optional[str] = None,
        device_tool_name: Optional[str] = None,
        device_config_name: Optional[str] = None,
        fw_version: Optional[str] = None,
        mp_tool_version: Optional[str] = None,
        flash_id: Optional[str] = None,
        original_bad_block: Optional[int] = None,
        cycles: int = 0,
        overall_result: Optional[str] = None,
        fail_sections: Optional[str] = None,
        controller: Optional[str] = None,
        capacity_mb: Optional[int] = None,
        capacity_sectors: Optional[int] = None,
        part_number: Optional[str] = None,
        task_link: Optional[str] = None,
        test_cycle: int = 0,
        test_case: int = 0,
        rtms_result: Optional[str] = None,
        rtms_code: Optional[str] = None,
        wai: Optional[float] = None,
        slc_pe_min: Optional[int] = None,
        slc_pe_max: Optional[int] = None,
        tlc_pe_min: Optional[int] = None,
        tlc_pe_max: Optional[int] = None,
        increase_bad_block: Optional[int] = None,
        parse_status: str = "Success",
    ) -> int:
        """插入主表记录，返回新 ID。

        Args:
            conn: 当前事务连接。
            其余参数对应 test_summary 表字段。

        Returns:
            新插入的记录 ID。
        """
        cursor = conn.execute(
            """
            INSERT INTO test_summary (
                file_name, file_path, file_size, file_mtime,
                device_name, device_tool_name, device_config_name,
                fw_version, mp_tool_version, flash_id, original_bad_block,
                cycles, overall_result, fail_sections,
                controller, capacity_mb, capacity_sectors, part_number, task_link,
                test_cycle, test_case, rtms_result, rtms_code,
                wai, slc_pe_min, slc_pe_max, tlc_pe_min, tlc_pe_max,
                increase_bad_block, parse_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                file_name, file_path, file_size, file_mtime,
                device_name, device_tool_name, device_config_name,
                fw_version, mp_tool_version, flash_id, original_bad_block,
                cycles, overall_result, fail_sections,
                controller, capacity_mb, capacity_sectors, part_number, task_link,
                test_cycle, test_case, rtms_result, rtms_code,
                wai, slc_pe_min, slc_pe_max, tlc_pe_min, tlc_pe_max,
                increase_bad_block, parse_status,
            ),
        )
        return cursor.lastrowid

    def insert_metrics_batch(
        self,
        conn: sqlite3.Connection,
        summary_id: int,
        metrics: list[tuple],
    ) -> None:
        """批量插入指标记录。

        Args:
            conn: 当前事务连接。
            summary_id: 关联的主表 ID。
            metrics: 指标元组列表，每个元素为
                (section, metric_key, metric_key_raw, raw_value,
                 num_value, value_type, prefix, array_index)。
        """
        if not metrics:
            return
        conn.executemany(
            """
            INSERT INTO test_metrics (
                summary_id, section, metric_key, metric_key_raw,
                raw_value, num_value, value_type, prefix, array_index
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [(summary_id, *m) for m in metrics],
        )

    def insert_process_log(
        self,
        conn: sqlite3.Connection,
        *,
        file_path: str,
        file_size: int,
        file_mtime: float,
        action: str,
        summary_id: Optional[int] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """记录文件处理状态。

        Args:
            conn: 当前事务连接。
            file_path: 文件路径。
            file_size: 文件大小。
            file_mtime: 文件修改时间。
            action: 处理动作（parsed/skipped/failed）。
            summary_id: 成功时关联的主表 ID。
            error_message: 失败时的错误信息。
        """
        conn.execute(
            """
            INSERT INTO process_log (
                file_path, file_size, file_mtime, action,
                summary_id, error_message
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (file_path, file_size, file_mtime, action, summary_id, error_message),
        )

    # ---- 查询 ----

    def get_summaries(
        self,
        conn: sqlite3.Connection,
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
        offset: int = 0,
    ) -> list[dict]:
        """主表组合筛选查询。

        Args:
            conn: 数据库连接。
            device_name: 按设备名过滤。
            fw_version: 按固件版本过滤。
            flash_id: 按 Flash ID 精确查询。
            overall_result: 按综合结果过滤（Pass/Fail）。
            capacity_mb: 按容量 MB 过滤。
            capacity_sectors: 按扇区数过滤。
            controller: 按主控型号过滤。
            date_from: 起始日期（YYYY-MM-DD）。
            date_to: 截止日期（YYYY-MM-DD）。
            limit: 返回条数上限。
            offset: 偏移量。

        Returns:
            符合条件的记录字典列表。
        """
        sql = "SELECT * FROM test_summary WHERE 1=1"
        params: list = []

        if device_name:
            sql += " AND device_name = ?"
            params.append(device_name)
        if fw_version:
            sql += " AND fw_version = ?"
            params.append(fw_version)
        if flash_id:
            sql += " AND flash_id = ?"
            params.append(flash_id)
        if overall_result:
            sql += " AND overall_result = ?"
            params.append(overall_result)
        if capacity_mb is not None:
            sql += " AND capacity_mb = ?"
            params.append(capacity_mb)
        if capacity_sectors is not None:
            sql += " AND capacity_sectors = ?"
            params.append(capacity_sectors)
        if controller:
            sql += " AND controller = ?"
            params.append(controller)
        if date_from:
            sql += " AND parsed_at >= ?"
            params.append(date_from)
        if date_to:
            sql += " AND parsed_at <= ?"
            params.append(date_to + " 23:59:59")

        sql += " ORDER BY parsed_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def get_metrics(
        self,
        conn: sqlite3.Connection,
        *,
        summary_id: Optional[int] = None,
        section: Optional[str] = None,
        metric_key: Optional[str] = None,
        value_type: Optional[str] = None,
    ) -> list[dict]:
        """指标查询，支持按 summary_id/section/metric_key 组合过滤。

        Args:
            conn: 数据库连接。
            summary_id: 主表 ID。
            section: Section 名称。
            metric_key: 指标键名。
            value_type: 值类型（hex/decimal/float/string）。

        Returns:
            符合条件的指标字典列表。
        """
        sql = "SELECT * FROM test_metrics WHERE 1=1"
        params: list = []

        if summary_id is not None:
            sql += " AND summary_id = ?"
            params.append(summary_id)
        if section:
            sql += " AND section = ?"
            params.append(section)
        if metric_key:
            sql += " AND metric_key = ?"
            params.append(metric_key)
        if value_type:
            sql += " AND value_type = ?"
            params.append(value_type)

        sql += " ORDER BY id"
        rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def get_metric_values_across_devices(
        self,
        conn: sqlite3.Connection,
        *,
        metric_key: str,
        section: Optional[str] = None,
        device_name: Optional[str] = None,
    ) -> list[dict]:
        """跨设备查询同一指标的值（用于趋势图）。

        Args:
            conn: 数据库连接。
            metric_key: 指标键名。
            section: Section 名称（可选过滤）。
            device_name: 设备名（可选过滤）。

        Returns:
            包含 device_name、parsed_at、raw_value、num_value 的字典列表。
        """
        sql = """
            SELECT s.device_name, s.fw_version, s.parsed_at,
                   m.metric_key, m.raw_value, m.num_value, m.section
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

        sql += " ORDER BY s.parsed_at ASC"
        rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def compare_metrics(
        self,
        conn: sqlite3.Connection,
        summary_ids: list[int],
        section: Optional[str] = None,
    ) -> list[dict]:
        """多设备/多周期指标对比。

        Args:
            conn: 数据库连接。
            summary_ids: 待对比的主表 ID 列表。
            section: 可选按 Section 过滤。

        Returns:
            对比结果字典列表。
        """
        if not summary_ids:
            return []

        placeholders = ",".join("?" * len(summary_ids))
        sql = f"""
            SELECT m.summary_id, s.device_name, s.parsed_at,
                   m.section, m.metric_key, m.metric_key_raw,
                   m.raw_value, m.num_value, m.value_type
            FROM test_metrics m
            JOIN test_summary s ON m.summary_id = s.id
            WHERE m.summary_id IN ({placeholders})
        """
        params: list = list(summary_ids)

        if section:
            sql += " AND m.section = ?"
            params.append(section)

        sql += " ORDER BY m.summary_id, m.section, m.id"
        rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def get_fail_summary(self, conn: sqlite3.Connection) -> list[dict]:
        """汇总所有 Fail 的测试记录。

        Returns:
            Fail 记录列表。
        """
        rows = conn.execute(
            """
            SELECT * FROM test_summary
            WHERE overall_result = 'Fail'
            ORDER BY parsed_at DESC
            """,
        ).fetchall()
        return [dict(row) for row in rows]

    def is_file_processed(
        self,
        conn: sqlite3.Connection,
        file_path: str,
        file_size: int,
        file_mtime: float,
    ) -> bool:
        """判断文件是否已处理且未变化。

        Args:
            conn: 数据库连接。
            file_path: 文件路径。
            file_size: 文件大小。
            file_mtime: 文件修改时间。

        Returns:
            True 表示已处理且无变化，可跳过。
        """
        row = conn.execute(
            """
            SELECT id FROM process_log
            WHERE file_path = ? AND file_size = ? AND file_mtime = ?
              AND action IN ('parsed', 'skipped')
            LIMIT 1
            """,
            (file_path, file_size, file_mtime),
        ).fetchone()
        return row is not None

    def get_all_process_logs(
        self, conn: sqlite3.Connection
    ) -> list[dict]:
        """获取所有处理记录。

        Returns:
            处理记录字典列表。
        """
        rows = conn.execute(
            "SELECT * FROM process_log ORDER BY processed_at DESC"
        ).fetchall()
        return [dict(row) for row in rows]
