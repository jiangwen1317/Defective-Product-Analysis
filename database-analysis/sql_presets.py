"""
常用查询 SQL 预设集

覆盖以下场景：
1. fail_records        - 所有 Fail 的测试记录
2. wai_by_device       - 某设备的 WAI 趋势
3. fw_wear_compare     - 固件版本磨损指标对比
4. wai_threshold       - WAI 超过阈值的设备
5. section_metrics     - 某测试某 Section 的完整指标
6. bad_block_summary   - 坏块统计
7. device_life         - 设备寿命状态
8. temperature_stats   - 温度统计
9. write_volume        - 写入量统计
10. fail_distribution  - Fail Section 分布统计
"""

SQL_PRESETS: dict[str, dict] = {
    # 1. 查看所有 Fail 的测试记录
    "fail_records": {
        "description": "所有 Fail 的测试记录",
        "sql": """
            SELECT s.id, s.device_name, s.fw_version, s.overall_result,
                   s.fail_sections, s.wai, s.parsed_at
            FROM test_summary s
            WHERE s.overall_result = 'Fail'
            ORDER BY s.parsed_at DESC;
        """,
        "params": [],
    },

    # 2. 查看某设备的 WAI 趋势
    "wai_by_device": {
        "description": "某设备的 WAI 值趋势（参数: 设备名）",
        "sql": """
            SELECT s.device_name, s.parsed_at, m.raw_value, m.num_value
            FROM test_metrics m
            JOIN test_summary s ON m.summary_id = s.id
            WHERE m.metric_key = 'WAI' AND m.section = 'Wear_Detection'
              AND s.device_name = ?
            ORDER BY s.parsed_at ASC;
        """,
        "params": ["device_name"],
    },

    # 3. 固件版本磨损指标对比
    "fw_wear_compare": {
        "description": "两个固件版本的磨损指标统计对比（参数: 版本A, 版本B）",
        "sql": """
            SELECT s.fw_version, m.metric_key,
                   AVG(m.num_value) as avg_val,
                   MAX(m.num_value) as max_val,
                   MIN(m.num_value) as min_val,
                   COUNT(*) as sample_count
            FROM test_metrics m
            JOIN test_summary s ON m.summary_id = s.id
            WHERE m.section = 'Wear_Detection'
              AND m.metric_key IN ('WAI', 'WA(TLC)', 'WA(SLC)', 'WearGap')
              AND s.fw_version IN (?, ?)
            GROUP BY s.fw_version, m.metric_key;
        """,
        "params": ["fw_version_a", "fw_version_b"],
    },

    # 4. WAI 超过阈值的设备
    "wai_threshold": {
        "description": "WAI 超过阈值的设备（参数: 阈值）",
        "sql": """
            SELECT s.device_name, s.fw_version, s.parsed_at,
                   m.num_value as wai_value
            FROM test_metrics m
            JOIN test_summary s ON m.summary_id = s.id
            WHERE m.metric_key = 'WAI'
              AND m.section = 'Wear_Detection'
              AND m.num_value > ?
            ORDER BY m.num_value DESC;
        """,
        "params": ["threshold"],
    },

    # 5. 某测试某 Section 的完整指标
    "section_metrics": {
        "description": "某测试记录某 Section 的完整 KV 列表（参数: summary_id, section）",
        "sql": """
            SELECT m.metric_key_raw, m.raw_value, m.num_value,
                   m.value_type, m.prefix, m.array_index
            FROM test_metrics m
            WHERE m.summary_id = ? AND m.section = ?
            ORDER BY m.id;
        """,
        "params": ["summary_id", "section"],
    },

    # 6. 坏块统计
    "bad_block_summary": {
        "description": "所有设备的坏块统计（原始/新增/新坏块）",
        "sql": """
            SELECT s.id, s.device_name, s.parsed_at,
                   MAX(CASE WHEN m.metric_key = 'dwOriginalBadBlock'
                            AND m.section = 'Start of test'
                       THEN m.num_value END) as original,
                   MAX(CASE WHEN m.metric_key = 'dwIncreaseBadBlock'
                       THEN m.num_value END) as increase,
                   MAX(CASE WHEN m.metric_key = 'wNewBadBlkNum'
                       THEN m.num_value END) as new_bad
            FROM test_metrics m
            JOIN test_summary s ON m.summary_id = s.id
            WHERE m.metric_key IN ('dwOriginalBadBlock', 'dwIncreaseBadBlock', 'wNewBadBlkNum')
            GROUP BY s.id
            ORDER BY s.parsed_at DESC;
        """,
        "params": [],
    },

    # 7. 设备寿命状态
    "device_life": {
        "description": "设备寿命指标（Device Life A/B + PRE_EOL_INFO）",
        "sql": """
            SELECT s.device_name, s.fw_version, s.parsed_at,
                   MAX(CASE WHEN m.metric_key = 'bDevice_Life_A' THEN m.num_value END) as life_a,
                   MAX(CASE WHEN m.metric_key = 'bDevice_Life_B' THEN m.num_value END) as life_b,
                   MAX(CASE WHEN m.metric_key = 'bPRE_EOL_INFO' THEN m.num_value END) as pre_eol
            FROM test_metrics m
            JOIN test_summary s ON m.summary_id = s.id
            WHERE m.section = 'Wear_Detection'
              AND m.metric_key IN ('bDevice_Life_A', 'bDevice_Life_B', 'bPRE_EOL_INFO')
            GROUP BY s.id
            ORDER BY s.parsed_at DESC;
        """,
        "params": [],
    },

    # 8. 温度统计
    "temperature_stats": {
        "description": "设备温度范围统计",
        "sql": """
            SELECT s.device_name, s.parsed_at,
                   MAX(CASE WHEN m.metric_key = 'bTemperatureMax' THEN m.num_value END) as temp_max,
                   MAX(CASE WHEN m.metric_key = 'bTemperatureMin' THEN m.num_value END) as temp_min,
                   MAX(CASE WHEN m.metric_key = 'wTemperature' THEN m.num_value END) as temp_current
            FROM test_metrics m
            JOIN test_summary s ON m.summary_id = s.id
            WHERE m.metric_key IN ('bTemperatureMax', 'bTemperatureMin', 'wTemperature')
            GROUP BY s.id
            ORDER BY s.parsed_at DESC;
        """,
        "params": [],
    },

    # 9. 写入量统计
    "write_volume": {
        "description": "设备写入/读取扇区数和擦除次数",
        "sql": """
            SELECT s.device_name, s.parsed_at,
                   MAX(CASE WHEN m.metric_key = 'lwWriteAllSectNum' THEN m.num_value END) as write_sectors,
                   MAX(CASE WHEN m.metric_key = 'lwReadAllSectNum' THEN m.num_value END) as read_sectors,
                   MAX(CASE WHEN m.metric_key = 'wEraseCnt' THEN m.num_value END) as erase_count
            FROM test_metrics m
            JOIN test_summary s ON m.summary_id = s.id
            WHERE m.metric_key IN ('lwWriteAllSectNum', 'lwReadAllSectNum', 'wEraseCnt')
            GROUP BY s.id
            ORDER BY s.parsed_at DESC;
        """,
        "params": [],
    },

    # 10. Fail Section 分布统计
    "fail_distribution": {
        "description": "所有 Fail 记录的 Section 分布",
        "sql": """
            SELECT s.fail_sections, COUNT(*) as cnt
            FROM test_summary s
            WHERE s.overall_result = 'Fail'
            GROUP BY s.fail_sections
            ORDER BY cnt DESC;
        """,
        "params": [],
    },
}
