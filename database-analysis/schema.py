"""
数据库表结构定义与初始化

定义 test_summary / test_metrics / process_log 三张表的 DDL，
提供初始化函数在首次运行时自动建表建索引。
"""

# ============================================================
# 主表：测试摘要（每个日志文件一条记录）
# ============================================================
CREATE_TEST_SUMMARY = """
CREATE TABLE IF NOT EXISTS test_summary (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    file_name           TEXT    NOT NULL UNIQUE,
    file_path           TEXT    NOT NULL,
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
    cycles              INTEGER DEFAULT 0,
    overall_result      TEXT,
    fail_sections       TEXT,

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
);
"""

CREATE_SUMMARY_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_summary_device_name   ON test_summary(device_name);",
    "CREATE INDEX IF NOT EXISTS idx_summary_fw_version    ON test_summary(fw_version);",
    "CREATE INDEX IF NOT EXISTS idx_summary_overall_result ON test_summary(overall_result);",
    "CREATE INDEX IF NOT EXISTS idx_summary_parsed_at     ON test_summary(parsed_at);",
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
    value_type      TEXT    NOT NULL DEFAULT 'string',
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
    action          TEXT    NOT NULL,
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


def init_database(conn: "sqlite3.Connection") -> None:
    """在给定连接上执行全部建表与建索引语句。

    Args:
        conn: 已打开的 SQLite 连接。
    """
    cursor = conn.cursor()

    # 启用 WAL 模式和外键约束
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA foreign_keys=ON;")

    # 建表
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
