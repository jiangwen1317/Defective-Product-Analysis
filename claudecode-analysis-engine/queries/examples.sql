-- ============================================================
-- EMMC 测试日志数据库 - 常用查询示例
-- 适用于 SQLite 数据库
-- ============================================================

-- ============================================================
-- 1. 数据概览
-- ============================================================

-- 1.1 统计记录总数
SELECT
    COUNT(*) AS total_records,
    SUM(CASE WHEN parse_status = 'Success' THEN 1 ELSE 0 END) AS success_count,
    SUM(CASE WHEN parse_status = 'Failed' THEN 1 ELSE 0 END) AS failed_count,
    SUM(CASE WHEN test_result = 'Fail' THEN 1 ELSE 0 END) AS fail_count
FROM test_summary;

-- 1.2 按设备统计
SELECT
    device_name,
    fw_version,
    COUNT(*) AS record_count,
    GROUP_CONCAT(DISTINCT test_result) AS results
FROM test_summary
GROUP BY device_name, fw_version
ORDER BY record_count DESC;

-- ============================================================
-- 2. 关键指标对比
-- ============================================================

-- 2.1 对比 WAI 指标 (按设备)
SELECT
    s.device_name,
    s.fw_version,
    m.raw_value AS WAI
FROM test_summary s
INNER JOIN test_metrics m ON s.id = m.summary_id
WHERE m.metric_key = 'WAI'
  AND s.parse_status = 'Success'
ORDER BY s.device_name, m.num_value DESC;

-- 2.2 对比多个设备的 WA(TLC) 和 WA(SLC)
SELECT
    s.device_name,
    s.test_cycles,
    MAX(CASE WHEN m.metric_key = 'WA(TLC)' THEN m.num_value END) AS WA_TLC,
    MAX(CASE WHEN m.metric_key = 'WA(SLC)' THEN m.num_value END) AS WA_SLC,
    MAX(CASE WHEN m.metric_key = 'WAI' THEN m.num_value END) AS WAI
FROM test_summary s
LEFT JOIN test_metrics m ON s.id = m.summary_id
WHERE s.parse_status = 'Success'
GROUP BY s.id
ORDER BY s.device_name;

-- 2.3 对比固件版本间的 P/E Cycle 差异
SELECT
    s.fw_version,
    COUNT(*) AS device_count,
    AVG(m.num_value) AS avg_pe_cycle,
    MIN(m.num_value) AS min_pe_cycle,
    MAX(m.num_value) AS max_pe_cycle
FROM test_summary s
INNER JOIN test_metrics m ON s.id = m.summary_id
WHERE m.metric_key = 'wTLCMaxPECycle'
  AND s.parse_status = 'Success'
GROUP BY s.fw_version
ORDER BY avg_pe_cycle DESC;

-- ============================================================
-- 3. 结构体对比 (按 Section 过滤)
-- ============================================================

-- 3.1 对比 Wear_Detection 模块的所有指标
SELECT
    s.device_name,
    m.metric_key,
    m.raw_value,
    m.num_value
FROM test_summary s
INNER JOIN test_metrics m ON s.id = m.summary_id
WHERE m.section = 'Wear_Detection'
  AND s.parse_status = 'Success'
ORDER BY s.device_name, m.metric_key;

-- 3.2 对比多个设备的 BM_table_match 结果
SELECT
    s.device_name,
    s.fw_version,
    m.result AS BM_table_match_result
FROM test_summary s
INNER JOIN test_metrics m ON s.id = m.summary_id
WHERE m.section = 'BM_table_match'
  AND s.parse_status = 'Success';

-- 3.3 提取所有 Section 的 Result
SELECT
    s.device_name,
    s.id,
    GROUP_CONCAT(m.section || ':' || m.result, ', ') AS section_results
FROM test_summary s
INNER JOIN test_metrics m ON s.id = m.summary_id
WHERE m.metric_key = 'Result'
  AND s.parse_status = 'Success'
GROUP BY s.id;

-- ============================================================
-- 4. 组合筛选查询
-- ============================================================

-- 4.1 按设备名称 + 版本号筛选
SELECT * FROM test_summary
WHERE device_name LIKE '%DM3720%'
  AND fw_version LIKE '%TL600E%';

-- 4.2 多条件 OR 组合查询
SELECT * FROM test_summary
WHERE (device_name LIKE '%DM3720%' OR device_name LIKE '%DM1234%')
  AND test_result = 'Pass'
  AND parse_status = 'Success';

-- 4.3 按容量和主控筛选 (通过 flash_id 判断)
SELECT * FROM test_summary
WHERE flash_id LIKE '%ECDE784C%'  -- 示例 flash_id
  AND parse_status = 'Success';

-- ============================================================
-- 5. 磨损曲线数据查询
-- ============================================================

-- 5.1 获取磨损曲线数据 (WAI, P/E Cycle, Bad Block)
SELECT
    s.device_name,
    s.id AS summary_id,
    s.test_cycles,
    s.created_at,
    MAX(CASE WHEN m.metric_key = 'WAI' THEN m.num_value END) AS WAI,
    MAX(CASE WHEN m.metric_key = 'dwDegreOfwear' THEN m.num_value END) AS degree_of_wear,
    MAX(CASE WHEN m.metric_key = 'dwIncreaseBadBlock' THEN m.num_value END) AS bad_block_count
FROM test_summary s
LEFT JOIN test_metrics m ON s.id = m.summary_id
WHERE s.parse_status = 'Success'
GROUP BY s.id
ORDER BY s.device_name, s.created_at;

-- 5.2 某设备的 WAI 趋势
SELECT
    s.test_cycles,
    m.num_value AS WAI,
    s.created_at
FROM test_summary s
INNER JOIN test_metrics m ON s.id = m.summary_id
WHERE s.device_name = 'DM3720.012.13'
  AND m.metric_key = 'WAI'
  AND s.parse_status = 'Success'
ORDER BY s.test_cycles;

-- ============================================================
-- 6. ECC 曲线数据查询
-- ============================================================

-- 6.1 获取 ECC 相关指标
SELECT
    s.device_name,
    m.metric_key,
    m.num_value,
    m.cycles
FROM test_summary s
INNER JOIN test_metrics m ON s.id = m.summary_id
WHERE m.metric_key LIKE '%ECC%'
  AND s.parse_status = 'Success'
ORDER BY s.device_name, m.cycles, m.metric_key;

-- 6.2 按 Block/LBA 粒度的 ECC 分布
SELECT
    m.raw_value AS block_addr,
    m.num_value AS ecc_count
FROM test_metrics m
INNER JOIN test_summary s ON m.summary_id = s.id
WHERE m.metric_key LIKE '%ECC_cnt%'
  AND s.parse_status = 'Success'
ORDER BY m.num_value DESC
LIMIT 100;

-- ============================================================
-- 7. 异常查询
-- ============================================================

-- 7.1 解析失败的记录
SELECT * FROM test_summary
WHERE parse_status = 'Failed'
ORDER BY created_at DESC;

-- 7.2 测试失败的设备
SELECT * FROM test_summary
WHERE test_result = 'Fail'
ORDER BY created_at DESC;

-- 7.3 查看失败原因
SELECT
    s.device_name,
    s.file_name,
    s.parse_error
FROM test_summary s
WHERE s.parse_status = 'Failed';

-- 7.4 WAI 低于阈值的设备
SELECT
    s.device_name,
    s.fw_version,
    m.num_value AS WAI
FROM test_summary s
INNER JOIN test_metrics m ON s.id = m.summary_id
WHERE m.metric_key = 'WAI'
  AND m.num_value < 10  -- 假设阈值
  AND s.parse_status = 'Success'
ORDER BY m.num_value;

-- ============================================================
-- 8. 指标统计
-- ============================================================

-- 8.1 WAI 统计
SELECT
    'WAI' AS metric,
    COUNT(*) AS count,
    MIN(num_value) AS min_val,
    MAX(num_value) AS max_val,
    AVG(num_value) AS avg_val
FROM test_metrics
WHERE metric_key = 'WAI' AND num_value IS NOT NULL;

-- 8.2 所有关键指标统计
SELECT
    metric_key,
    COUNT(*) AS count,
    MIN(num_value) AS min_val,
    MAX(num_value) AS max_val,
    AVG(num_value) AS avg_val
FROM test_metrics
WHERE metric_key IN ('WAI', 'WA(TLC)', 'WA(SLC)', 'dwTLCMaxPECycle', 'dwIncreaseBadBlock')
  AND num_value IS NOT NULL
GROUP BY metric_key;

-- ============================================================
-- 9. 视图查询 (使用预定义的视图)
-- ============================================================

-- 9.1 设备概览视图
SELECT * FROM v_device_overview;

-- 9.2 异常设备视图
SELECT * FROM v_failed_devices;

-- ============================================================
-- 10. 数据导出查询
-- ============================================================

-- 10.1 导出设备概览 (CSV 格式)
.output device_overview.csv
SELECT
    device_name,
    fw_version,
    test_cycles,
    test_result,
    WAI,
    PE_cycle,
    WA_TLC,
    WA_SLC
FROM v_device_overview;

-- 10.2 导出所有 WAI 数据
.output wai_data.csv
SELECT
    s.device_name,
    s.fw_version,
    m.num_value AS WAI,
    s.created_at
FROM test_summary s
INNER JOIN test_metrics m ON s.id = m.summary_id
WHERE m.metric_key = 'WAI'
  AND s.parse_status = 'Success';
