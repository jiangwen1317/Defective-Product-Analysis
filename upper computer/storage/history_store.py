"""
测试历史持久化。

将每次测试会话的结果写入 SQLite 数据库（data/test_history.db），
供程序重启后恢复统计数字与产线追溯使用。

表结构与早期版本已写入的 test_records 完全兼容：
    id, timestamp, group_id, bitmask, dut_count, error_codes(JSON), duration_ms, success
"""

import json
import logging
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# 未受测 DUT 在 error_codes 列中的占位符
NOT_TESTED_CODE = "----"


class HistoryStore:
    """测试历史存储（SQLite）。

    每次操作独立开关连接：写入频率低（每次测试会话一条记录），
    无需常驻连接，也避免跨线程共享连接的问题。
    """

    def __init__(self, db_path: str | Path) -> None:
        """初始化存储并确保表结构存在。

        Args:
            db_path: 数据库文件路径，父目录不存在时自动创建。

        Raises:
            sqlite3.Error: 数据库文件无法创建或初始化失败时。
        """
        self._db_path = str(db_path)
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        with closing(sqlite3.connect(self._db_path)) as conn, conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS test_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    group_id TEXT NOT NULL,
                    bitmask TEXT NOT NULL,
                    dut_count INTEGER NOT NULL,
                    error_codes TEXT NOT NULL,
                    duration_ms INTEGER NOT NULL,
                    success INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_timestamp ON test_records(timestamp)"
            )

    def save_record(self, group: str, results: dict[int, str], duration: float) -> None:
        """保存一次测试会话记录。

        Args:
            group: 组号。
            results: 本次受测 DUT 的结果字典 {dut_index: error_code}。
            duration: 会话耗时（秒）。

        Raises:
            sqlite3.Error: 写入失败时。
        """
        bitmask = "".join("1" if i in results else "0" for i in range(1, 9))
        error_codes = [results.get(i, NOT_TESTED_CODE) for i in range(1, 9)]
        success = 1 if results and all(c == "0000" for c in results.values()) else 0

        with closing(sqlite3.connect(self._db_path)) as conn, conn:
            conn.execute(
                "INSERT INTO test_records "
                "(timestamp, group_id, bitmask, dut_count, error_codes, duration_ms, success) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                    group,
                    bitmask,
                    len(results),
                    json.dumps(error_codes),
                    int(duration * 1000),
                    success,
                ),
            )

    def load_stats(self) -> dict[str, int]:
        """加载累计统计（供启动时恢复界面统计数字）。

        Returns:
            {"total": 总会话数, "success": 成功数, "failed": 失败数}。
        """
        with closing(sqlite3.connect(self._db_path)) as conn:
            row = conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(success), 0) FROM test_records"
            ).fetchone()

        total, success = int(row[0]), int(row[1])
        return {"total": total, "success": success, "failed": total - success}
