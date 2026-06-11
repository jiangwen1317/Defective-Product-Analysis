"""
数据库表结构定义与初始化

定义 test_summary / test_metrics / process_log 三张表的 DDL，
提供初始化函数在首次运行时自动建表建索引。
"""
import logging

logger = logging.getLogger(__name__)

# ============================================================
# 主表：测试摘要（每个日志文件一条记录）
# ============================================================
CREATE_TEST_SUMMARY = """
CREATE TABLE IF NOT EXISTS test_summary (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    file_name           TEXT    NOT NULL,
    file_path           TEXT    NOT NULL UNIQUE,
    file_size           INTEGER NOT NULL,
    file_mtime          REAL    NOT NULL,

    -- 顶层固定字段（从日志头部提取）
    device_name         TEXT,
    device_tool_name    TEXT,
    device_config_name  TEXT,

    -- Start of test 关键字段
    fw_version          TEXT,
    mp_tool_version     TEXT,
    flash_id            TEXT,
    original_bad_block  INTEGER,

    -- 汇总
    cycles              INTEGER DEFAULT 0 CHECK(cycles >= 0),
    overall_result      TEXT    CHECK(overall_result IN ('Pass', 'Fail', 'Unknown')),
    fail_sections       TEXT,

    -- 设备扩展信息
    controller          TEXT,
    capacity_mb         INTEGER,
    capacity_sectors    INTEGER,       -- 扇区数 (如 122224640)
    part_number         TEXT,
    task_link           TEXT,

    -- 测试参数
    test_cycle          INTEGER DEFAULT 0 CHECK(test_cycle >= 0),
    test_case           INTEGER DEFAULT 0 CHECK(test_case >= 0),

    -- 最终结果
    rtms_result         TEXT,
    rtms_code           TEXT,

    -- Wear 关键指标（冗余，高频查询用）
    wai                 REAL,
    slc_pe_min          INTEGER,
    slc_pe_max          INTEGER,
    tlc_pe_min          INTEGER,
    tlc_pe_max          INTEGER,
    increase_bad_block  INTEGER,

    -- 处理元数据
    parsed_at           TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    parse_status        TEXT    NOT NULL DEFAULT 'Success'
                        CHECK(parse_status IN ('Success', 'Failed', 'Partial'))
);
"""

CREATE_SUMMARY_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_summary_device_name   ON test_summary(device_name);",
    "CREATE INDEX IF NOT EXISTS idx_summary_fw_version    ON test_summary(fw_version);",
    "CREATE INDEX IF NOT EXISTS idx_summary_overall_result ON test_summary(overall_result);",
    "CREATE INDEX IF NOT EXISTS idx_summary_parsed_at     ON test_summary(parsed_at);",
    "CREATE INDEX IF NOT EXISTS idx_summary_controller    ON test_summary(controller);",
    "CREATE INDEX IF NOT EXISTS idx_summary_rtms_result   ON test_summary(rtms_result);",
    "CREATE INDEX IF NOT EXISTS idx_summary_flash_id      ON test_summary(flash_id);",
    "CREATE INDEX IF NOT EXISTS idx_summary_capacity_mb   ON test_summary(capacity_mb);",
    "CREATE INDEX IF NOT EXISTS idx_summary_capacity_sectors ON test_summary(capacity_sectors);",
]

# ============================================================
# KV 指标表：动态指标存储（每个 KV 一行）
# ============================================================
CREATE_TEST_METRICS = """
CREATE TABLE IF NOT EXISTS test_metrics (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    summary_id      INTEGER NOT NULL,
    section         TEXT    NOT NULL,
    metric_key      TEXT    NOT NULL,
    metric_key_raw  TEXT    NOT NULL,
    raw_value       TEXT    NOT NULL,
    num_value       REAL,
    value_type      TEXT    NOT NULL DEFAULT 'string'
                        CHECK(value_type IN ('hex', 'decimal', 'float', 'string', 'hexdump')),
    prefix          TEXT,
    array_index     TEXT,

    FOREIGN KEY (summary_id) REFERENCES test_summary(id) ON DELETE CASCADE
);
"""

CREATE_METRICS_INDEXES = [
    # 按指标名查询
    "CREATE INDEX IF NOT EXISTS idx_metrics_key "
    "ON test_metrics(metric_key);",
    # 按 Section + 指标名查询
    "CREATE INDEX IF NOT EXISTS idx_metrics_section_key "
    "ON test_metrics(section, metric_key);",
    # 按测试查所有指标
    "CREATE INDEX IF NOT EXISTS idx_metrics_summary "
    "ON test_metrics(summary_id);",
    # 按测试的某个 Section 查指标
    "CREATE INDEX IF NOT EXISTS idx_metrics_summary_section "
    "ON test_metrics(summary_id, section);",
    # 数值范围查询
    "CREATE INDEX IF NOT EXISTS idx_metrics_numeric "
    "ON test_metrics(metric_key, num_value) "
    "WHERE num_value IS NOT NULL;",
]

# ============================================================
# 处理记录表：文件处理状态追踪
# ============================================================
CREATE_PROCESS_LOG = """
CREATE TABLE IF NOT EXISTS process_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path       TEXT    NOT NULL,
    file_size       INTEGER NOT NULL,
    file_mtime      REAL    NOT NULL,
    action          TEXT    NOT NULL CHECK(action IN ('parsed', 'skipped', 'failed')),
    summary_id      INTEGER,
    error_message   TEXT,
    processed_at    TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),

    FOREIGN KEY (summary_id) REFERENCES test_summary(id) ON DELETE SET NULL
);
"""

CREATE_PROCESS_LOG_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_process_file_path ON process_log(file_path);",
    "CREATE INDEX IF NOT EXISTS idx_process_action    ON process_log(action);",
]


# ============================================================
# 迁移：为已有表添加缺失列
# ============================================================
_MIGRATE_SUMMARY_COLUMNS = [
    ("controller",         "TEXT"),
    ("capacity_mb",        "INTEGER"),
    ("capacity_sectors",   "INTEGER"),
    ("part_number",        "TEXT"),
    ("task_link",          "TEXT"),
    ("test_cycle",         "INTEGER DEFAULT 0"),
    ("test_case",          "INTEGER DEFAULT 0"),
    ("rtms_result",        "TEXT"),
    ("rtms_code",          "TEXT"),
]


def _migrate(conn: "sqlite3.Connection") -> None:
    """为已有表添加缺失列，并修复 UNIQUE 约束（幂等操作）。

    通过 PRAGMA table_info 检查现有列，仅 ALTER TABLE 添加缺失列。
    如果 file_name 上存在 UNIQUE 约束（旧版 schema），则通过表重建
    将 UNIQUE 约束迁移到 file_path 上。

    Args:
        conn: 已打开的 SQLite 连接。
    """
    cursor = conn.cursor()

    # 检查 test_summary 表是否存在
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='test_summary';"
    )
    if cursor.fetchone() is None:
        return  # 表不存在，init_database 的 CREATE TABLE 会创建

    # 获取现有列名
    cursor.execute("PRAGMA table_info(test_summary);")
    existing_columns = {row[1] for row in cursor.fetchall()}

    # 添加缺失列
    for col_name, col_type in _MIGRATE_SUMMARY_COLUMNS:
        if col_name not in existing_columns:
            cursor.execute(
                f"ALTER TABLE test_summary ADD COLUMN {col_name} {col_type};"
            )

    # 检查是否需要将 UNIQUE 约束从 file_name 迁移到 file_path
    cursor.execute(
        "SELECT sql FROM sqlite_master "
        "WHERE type='table' AND name='test_summary' AND sql LIKE '%file_name%UNIQUE%'"
    )
    needs_unique_fix = cursor.fetchone() is not None

    if needs_unique_fix:
        logger.info("检测到 file_name UNIQUE 约束，正在迁移到 file_path...")
        _rebuild_summary_table(conn)
        logger.info("UNIQUE 约束迁移完成")


def _rebuild_summary_table(conn: "sqlite3.Connection") -> None:
    """重建 test_summary 表，将 UNIQUE 约束从 file_name 移到 file_path。

    采用 rename → create new → copy data → drop old 的安全模式，
    保留所有现有数据。外键约束在操作期间临时禁用。
    """
    cursor = conn.cursor()

    # 获取现有表的实际列名
    cursor.execute("PRAGMA table_info(test_summary);")
    columns = [row[1] for row in cursor.fetchall()]
    col_list = ", ".join(columns)

    # 禁用外键约束（仅在重建期间）
    cursor.execute("PRAGMA foreign_keys=OFF;")

    try:
        cursor.execute("ALTER TABLE test_summary RENAME TO _test_summary_old;")
        cursor.execute(CREATE_TEST_SUMMARY)
        cursor.execute(
            f"INSERT INTO test_summary ({col_list}) "
            f"SELECT {col_list} FROM _test_summary_old;"
        )
        cursor.execute("DROP TABLE _test_summary_old;")

        # 重建索引（旧索引随旧表一起被删除）
        for sql in CREATE_SUMMARY_INDEXES:
            cursor.execute(sql)
    except Exception:
        # 回滚尝试：如果新表已创建但数据拷贝失败，尝试恢复旧表
        cursor.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='_test_summary_old'"
        )
        if cursor.fetchone() is not None:
            cursor.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name='test_summary'"
            )
            if cursor.fetchone() is not None:
                cursor.execute("DROP TABLE test_summary")
            cursor.execute(
                "ALTER TABLE _test_summary_old RENAME TO test_summary;"
            )
        raise
    finally:
        cursor.execute("PRAGMA foreign_keys=ON;")


def init_database(conn: "sqlite3.Connection") -> None:
    """在给定连接上执行全部建表与建索引语句。

    包含自动迁移：如果旧版数据库已存在 test_summary 表但缺少新增列，
    会自动通过 ALTER TABLE 补充。

    Args:
        conn: 已打开的 SQLite 连接。
    """
    cursor = conn.cursor()

    # 启用 WAL 模式和外键约束
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA foreign_keys=ON;")

    # 迁移：为旧表补充缺失列
    _migrate(conn)

    # 建表（IF NOT EXISTS，旧库已迁移、新库直接创建）
    cursor.execute(CREATE_TEST_SUMMARY)
    cursor.execute(CREATE_TEST_METRICS)
    cursor.execute(CREATE_PROCESS_LOG)

    # 建索引
    for sql in (
        CREATE_SUMMARY_INDEXES
        + CREATE_METRICS_INDEXES
        + CREATE_PROCESS_LOG_INDEXES
    ):
        cursor.execute(sql)

    conn.commit()
