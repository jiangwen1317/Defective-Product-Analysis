-- ============================================================
-- EMMC 测试日志数据库 Schema
-- 采用 "主表 (test_summary) + KV指标表 (test_metrics)" 双表模型
-- ============================================================

-- 启用外键约束
PRAGMA foreign_keys = ON;

-- ============================================================
-- 主表: 测试摘要表
-- 存储每份日志文件的元数据和固定身份信息
-- ============================================================
CREATE TABLE IF NOT EXISTS test_summary (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    file_name       TEXT NOT NULL,           -- 原始文件名
    file_path       TEXT NOT NULL,           -- 完整文件路径
    file_size       INTEGER,                 -- 文件大小(bytes)
    file_mtime      REAL,                    -- 文件修改时间(Unix timestamp)

    device_name     TEXT,                    -- 设备名称 如 DM3720.012.13
    fw_version      TEXT,                    -- 固件版本
    tool_version    TEXT,                    -- 工具版本 如 V1.0.19
    flash_id        TEXT,                    -- Flash ID

    test_cycles     INTEGER DEFAULT 0,       -- 测试循环次数
    test_result     TEXT,                    -- 整体测试结果 Pass/Fail

    parse_status    TEXT DEFAULT 'Pending',  -- 解析状态: Pending/Success/Failed
    parse_error     TEXT,                    -- 解析错误信息(失败时)
    parse_time      REAL,                    -- 解析耗时(秒)

    created_at      REAL NOT NULL,           -- 记录创建时间(Unix timestamp)
    updated_at      REAL                     -- 记录更新时间(Unix timestamp)
);

-- ============================================================
-- 索引: 加速关键查询
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_summary_device ON test_summary(device_name);
CREATE INDEX IF NOT EXISTS idx_summary_fw ON test_summary(fw_version);
CREATE INDEX IF NOT EXISTS idx_summary_parse_status ON test_summary(parse_status);
CREATE INDEX IF NOT EXISTS idx_summary_result ON test_summary(test_result);
CREATE INDEX IF NOT EXISTS idx_summary_created ON test_summary(created_at);
CREATE INDEX IF NOT EXISTS idx_summary_file ON test_summary(file_name, file_mtime);

-- ============================================================
-- KV指标表: 测试指标表
-- 存储所有动态测试指标,禁止为任何具体指标创建独立列
-- ============================================================
CREATE TABLE IF NOT EXISTS test_metrics (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    summary_id      INTEGER NOT NULL,        -- 关联 test_summary.id

    section         TEXT NOT NULL,           -- Section 名称 如 Wear_Detection
    cycles          INTEGER DEFAULT 0,       -- 测试循环次数

    metric_key      TEXT NOT NULL,           -- 指标键名 如 WAI
    raw_value       TEXT,                    -- 原始字符串值

    num_value       REAL,                    -- 数值(转换失败时为NULL)
    str_value       TEXT,                    -- 字符串值(用于纯文本或长字符串)
    hex_value       TEXT,                    -- 十六进制原始值(如 0x0001)

    result          TEXT,                    -- 该Section的测试结果 Pass/Fail

    created_at      REAL NOT NULL,           -- 记录创建时间

    FOREIGN KEY (summary_id) REFERENCES test_summary(id) ON DELETE CASCADE
);

-- ============================================================
-- 索引: 核心索引 - 实现纵向切片查询秒级响应
-- ============================================================
-- 按 metric_key 查询: 支持快速筛选任意指标
CREATE INDEX IF NOT EXISTS idx_metrics_key ON test_metrics(metric_key);
-- 按 section 查询: 支持只看特定模块(SMART/EXTCSD等)
CREATE INDEX IF NOT EXISTS idx_metrics_section ON test_metrics(section);
-- 联合索引: 支持同名字段区分(如多个Section的Result)
CREATE INDEX IF NOT EXISTS idx_metrics_section_key ON test_metrics(section, metric_key);
-- 关联查询
CREATE INDEX IF NOT EXISTS idx_metrics_summary ON test_metrics(summary_id);
-- 数值范围查询: 支持 ECC 曲线、WAI 阈值等数值筛选
CREATE INDEX IF NOT EXISTS idx_metrics_num ON test_metrics(num_value);

-- ============================================================
-- 解析日志表: 记录解析过程日志
-- ============================================================
CREATE TABLE IF NOT EXISTS parse_logs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    summary_id      INTEGER,                 -- 关联 test_summary.id (可为NULL)
    file_name       TEXT NOT NULL,
    log_level       TEXT NOT NULL,           -- INFO/WARNING/ERROR
    message         TEXT NOT NULL,
    created_at      REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_parse_logs_level ON parse_logs(log_level);
CREATE INDEX IF NOT EXISTS idx_parse_logs_summary ON parse_logs(summary_id);

-- ============================================================
-- 视图: 设备概览 (便于快速查询)
-- ============================================================
CREATE VIEW IF NOT EXISTS v_device_overview AS
SELECT
    s.id,
    s.device_name,
    s.fw_version,
    s.test_cycles,
    s.test_result,
    s.parse_status,
    s.file_name,
    s.created_at,
    -- 提取关键磨损指标
    MAX(CASE WHEN m.metric_key = 'WAI' THEN m.num_value END) AS WAI,
    MAX(CASE WHEN m.metric_key = 'P/E_cycle' THEN m.num_value END) AS PE_cycle,
    MAX(CASE WHEN m.metric_key = 'WA(TLC)' THEN m.num_value END) AS WA_TLC,
    MAX(CASE WHEN m.metric_key = 'WA(SLC)' THEN m.num_value END) AS WA_SLC
FROM test_summary s
LEFT JOIN test_metrics m ON s.id = m.summary_id
GROUP BY s.id;

-- ============================================================
-- 视图: 异常设备汇总
-- ============================================================
CREATE VIEW IF NOT EXISTS v_failed_devices AS
SELECT
    s.id,
    s.device_name,
    s.fw_version,
    s.file_name,
    s.parse_status,
    s.parse_error,
    s.created_at
FROM test_summary s
WHERE s.parse_status = 'Failed'
   OR s.test_result = 'Fail';

-- ============================================================
-- 触发器: 自动更新 updated_at
-- ============================================================
CREATE TRIGGER IF NOT EXISTS tr_summary_updated
AFTER UPDATE ON test_summary
BEGIN
    UPDATE test_summary SET updated_at = strftime('%s', 'now') WHERE id = NEW.id;
END;
