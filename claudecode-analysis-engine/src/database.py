# -*- coding: utf-8 -*-
"""
数据库模块

提供数据库连接、初始化和基础操作功能。
"""

import logging
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, List, Optional, Tuple

from .config import Config, load_config

logger = logging.getLogger(__name__)

# 全局数据库实例
_db_instance: Optional["Database"] = None


class Database:
    """数据库管理类"""

    def __init__(self, db_path: Optional[str] = None, config: Optional[Config] = None):
        """
        初始化数据库连接。

        Args:
            db_path: 数据库文件路径, 优先级高于 config
            config: 配置对象
        """
        self.config = config or load_config()
        if db_path:
            self.db_path = db_path
        else:
            self.db_path = self.config.database.path

        # 转换为绝对路径
        if not os.path.isabs(self.db_path):
            script_dir = os.path.dirname(os.path.dirname(__file__))
            self.db_path = os.path.join(script_dir, self.db_path)

        self._conn: Optional[sqlite3.Connection] = None

    @property
    def connection(self) -> sqlite3.Connection:
        """获取数据库连接(懒加载)"""
        if self._conn is None:
            self._conn = self._create_connection()
        return self._conn

    def _create_connection(self) -> sqlite3.Connection:
        """创建数据库连接"""
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # 支持列名访问
        conn.execute("PRAGMA foreign_keys = ON")  # 启用外键约束
        logger.info(f"数据库连接已建立: {self.db_path}")
        return conn

    def close(self):
        """关闭数据库连接"""
        if self._conn:
            self._conn.close()
            self._conn = None
            logger.info("数据库连接已关闭")

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Connection, None, None]:
        """事务上下文管理器"""
        conn = self.connection
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"事务回滚: {e}")
            raise

    @contextmanager
    def cursor(self) -> Generator[sqlite3.Cursor, None, None]:
        """游标上下文管理器(自动提交)"""
        with self.transaction() as conn:
            cursor = conn.cursor()
            try:
                yield cursor
            finally:
                cursor.close()

    def init_schema(self):
        """初始化数据库 Schema"""
        schema_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "schema.sql"
        )

        if not os.path.exists(schema_path):
            raise FileNotFoundError(f"Schema 文件不存在: {schema_path}")

        with open(schema_path, "r", encoding="utf-8") as f:
            schema_sql = f.read()

        with self.transaction() as conn:
            conn.executescript(schema_sql)
            logger.info("数据库 Schema 初始化完成")

    def execute(self, sql: str, params: Tuple = ()) -> sqlite3.Cursor:
        """
        执行 SQL 语句。

        Args:
            sql: SQL 语句
            params: 参数元组

        Returns:
            游标对象
        """
        return self.connection.execute(sql, params)

    def fetchall(self, sql: str, params: Tuple = ()) -> List:
        """
        执行查询并返回所有结果。

        Args:
            sql: SQL 语句
            params: 参数元组

        Returns:
            结果列表
        """
        cursor = self.connection.execute(sql, params)
        return cursor.fetchall()

    def fetchone(self, sql: str, params: Tuple = ()) -> Optional:
        """
        执行查询并返回一条结果。

        Args:
            sql: SQL 语句
            params: 参数元组

        Returns:
            结果行或 None
        """
        cursor = self.connection.execute(sql, params)
        return cursor.fetchone()

    def commit(self):
        """提交事务"""
        self.connection.commit()

    def rollback(self):
        """回滚事务"""
        self.connection.rollback()


def get_database(db_path: Optional[str] = None) -> Database:
    """
    获取数据库实例(单例模式)。

    Args:
        db_path: 数据库文件路径

    Returns:
        Database 实例
    """
    global _db_instance
    if _db_instance is None:
        _db_instance = Database(db_path)
        # 确保 Schema 已初始化
        try:
            _db_instance.init_schema()
        except Exception as e:
            logger.warning(f"Schema 初始化检查: {e}")
    return _db_instance
