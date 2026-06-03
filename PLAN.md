# EMMC 测试日志数据库分析系统 - 实现计划

## 1. 项目概述

基于日志下载器已下载的日志文件，构建自动化的 EMMC 测试日志解析与数据库分析系统。

## 2. 数据库设计 (SQLite)

### 2.1 主表 (test_summary)
```sql
CREATE TABLE test_summary (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    file_name       TEXT NOT NULL,           -- 原始文件名
    file_path       TEXT NOT NULL,           -- 完整文件路径
    file_size       INTEGER,                 -- 文件大小(bytes)
    file_hash       TEXT,                    -- 文件MD5哈希(用于增量识别)
    file_mtime      REAL,                    -- 文件修改时间(Unix timestamp)

    device_name     TEXT,                    -- 设备名称 DM3720.012.13
    fw_version      TEXT,                    -- 固件版本
    tool_version    TEXT,                    -- 工具版本
    flash_id        TEXT,                    -- Flash ID

    test_cycles     INTEGER,                 -- 测试循环次数
    test_result     TEXT,                    -- 整体测试结果 Pass/Fail

    parse_status    TEXT DEFAULT 'Pending',  -- 解析状态: Pending/Success/Failed
    parse_error     TEXT,                    -- 解析错误信息
    parse_time      REAL,                    -- 解析耗时(秒)

    created_at      REAL NOT NULL,           -- 记录创建时间
    updated_at      REAL                     -- 记录更新时间
);

-- 关键索引
CREATE INDEX idx_summary_device ON test_summary(device_name);
CREATE INDEX idx_summary_fw ON test_summary(fw_version);
CREATE INDEX idx_summary_parse_status ON test_summary(parse_status);
CREATE INDEX idx_summary_created ON test_summary(created_at);
```

### 2.2 KV 指标表 (test_metrics)
```sql
CREATE TABLE test_metrics (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    summary_id      INTEGER NOT NULL,        -- 关联 test_summary.id

    section         TEXT NOT NULL,           -- Section 名称
    cycles          INTEGER DEFAULT 0,       -- 测试循环次数

    metric_key      TEXT NOT NULL,           -- 指标键名
    raw_value       TEXT,                    -- 原始字符串值

    num_value       REAL,                    -- 数值(转换失败时为NULL)
    str_value       TEXT,                    -- 字符串值(用于纯文本)

    hex_value       TEXT,                    -- 十六进制原始值(如 0x0001)

    result          TEXT,                    -- 该Section的测试结果 Pass/Fail

    created_at      REAL NOT NULL,

    FOREIGN KEY (summary_id) REFERENCES test_summary(id) ON DELETE CASCADE
);

-- 核心索引: 支持纵向切片查询
CREATE INDEX idx_metrics_key ON test_metrics(metric_key);
CREATE INDEX idx_metrics_section ON test_metrics(section);
CREATE INDEX idx_metrics_section_key ON test_metrics(section, metric_key);
CREATE INDEX idx_metrics_summary ON test_metrics(summary_id);
CREATE INDEX idx_metrics_num ON test_metrics(num_value);  -- 支持数值范围查询
```

### 2.3 解析日志表 (parse_logs) - 可选
```sql
CREATE TABLE parse_logs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    summary_id      INTEGER,                 -- 关联 test_summary.id
    file_name       TEXT NOT NULL,
    log_level       TEXT NOT NULL,           -- INFO/WARNING/ERROR
    message         TEXT NOT NULL,
    created_at      REAL NOT NULL
);
```

## 3. Section 识别规则

| Section Header | 说明 | 特殊处理 |
|---------------|------|----------|
| `[Start of test]` | 开始测试 | 全局指标 |
| `Cycles:N` | 测试循环 | 更新 cycles 值 |
| `[End of test]` | 结束测试 | 全局指标 |
| `[eMMC_EXT_CSD]` | EXTCSD数据 | **跳过 hex dump 块** |
| `[Wear_Detection]` | 磨损检测 | WAI等关键指标 |
| `[EmptyBlk_Detection]` | 空块检测 | - |
| `[GarbageDetection]` | 垃圾检测 | - |
| `[PM_mapping_validity_detection]` | PM映射验证 | - |
| `[BM_table_match]` | BM表匹配 | 保留自由文本行 |
| `[PDMBlockGarbComparison]` | PDM块垃圾比较 | - |
| `[GM/BIT_comparison_garbage]` | GM/BIT比较 | - |
| `[PDMI_legitimacy_detection]` | PDMI合法性检测 | - |
| `[PDMI_index_legitimacy_detection]` | PDMI索引检测 | - |
| `[CheckStackUsage]` | 栈使用检测 | - |

## 4. 文件结构设计

```
database-analysis/
├── schema.sql                     # 数据库 Schema (建表+索引)
├── sample_data/
│   └── RTMS_RTMSLOG_0.txt        # 示例日志文件
├── src/
│   ├── __init__.py
│   ├── config.py                  # 配置管理
│   ├── database.py                # 数据库连接与初始化
│   ├── models.py                  # 数据模型 (dataclass)
│   ├── parser.py                  # 日志解析引擎
│   ├── query.py                   # 查询接口
│   └── export.py                  # RMA 报告导出
├── logs/                          # 解析日志
├── tests/
│   └── test_parser.py            # 解析器单元测试
├── queries/                       # 常用 SQL 示例
│   └── examples.sql
├── config.json                    # 配置文件
├── main.py                        # 主入口
└── README.md                      # 使用说明
```

## 5. 核心模块设计

### 5.1 parser.py - 日志解析引擎
```
关键功能:
1. 增量解析 - 基于 文件大小 + 修改时间 + MD5 判断变更
2. 分块识别 - 按 Section Header 切分
3. KV 提取 - 正则匹配 `Key : Value` 或 `Key=Value`
4. 数值转换 - 自动转浮点数/十六进制
5. Hex Dump 跳过 - 识别并跳过 EXTCSD 的 hex dump
6. 错误隔离 - 单文件失败不影响整体
```

### 5.2 query.py - 查询接口
```
关键功能:
1. 按设备/版本筛选
2. 结构体对比 (按 section)
3. 组合筛选 (多条件 AND/OR)
4. 磨损曲线查询 (WAI/P/E 周期)
5. ECC 曲线查询
```

### 5.3 export.py - RMA 报告导出
```
关键功能:
1. Sheet1: 设备概览 (test_summary + 核心指标)
2. Sheet2: 详细指标 (动态 pivot 的 KV 表)
3. Sheet3: 异常汇总 (parse_status='Failed' 的记录)
```

## 6. 实现步骤

### Step 1: 创建项目骨架
- [ ] 创建目录结构
- [ ] 编写 schema.sql
- [ ] 编写 config.py (监控目录、扫描间隔等配置)
- [ ] 编写 database.py (数据库连接、初始化)

### Step 2: 实现解析器
- [ ] 实现 models.py (数据模型: TestSummary, TestMetric)
- [ ] 实现 parser.py (核心解析逻辑)
  - Section 识别与切分
  - KV 提取正则
  - Hex Dump 跳过
  - 数值转换 (浮点/十六进制)
  - 增量判断 (size + mtime)
- [ ] 添加单元测试

### Step 3: 实现查询与导出
- [ ] 实现 query.py (查询接口)
  - 按设备/版本筛选
  - 按 section 过滤
  - 组合筛选
  - 磨损曲线 / ECC 曲线查询
- [ ] 实现 export.py (Excel导出)
  - Sheet1: 设备概览
  - Sheet2: 详细指标 (动态 pivot)
  - Sheet3: 异常汇总

### Step 4: 集成与文档
- [ ] 编写 main.py (主入口: 解析 + 定时监控 + 导出)
- [ ] 编写 queries/examples.sql (常用查询示例)
- [ ] 编写 README.md (使用说明)

---

## 8. 核心数据结构

### 8.1 TestSummary (主表模型)
```python
@dataclass
class TestSummary:
    id: int = None
    file_name: str = ""
    file_path: str = ""
    file_size: int = 0
    file_mtime: float = 0.0
    device_name: str = ""
    fw_version: str = ""
    tool_version: str = ""
    flash_id: str = ""
    test_cycles: int = 0
    test_result: str = ""  # Pass/Fail
    parse_status: str = "Pending"
    parse_error: str = ""
    parse_time: float = 0.0
    created_at: float = 0.0
    updated_at: float = 0.0
```

### 8.2 TestMetric (KV指标模型)
```python
@dataclass
class TestMetric:
    id: int = None
    summary_id: int = 0
    section: str = ""      # 如 "Wear_Detection"
    cycles: int = 0        # 当前循环次数
    metric_key: str = ""   # 如 "WAI"
    raw_value: str = ""    # "11.980"
    num_value: float = None # 11.98 (转换失败时为 None)
    str_value: str = ""    # 纯文本值
    hex_value: str = ""    # "0x0001"
    result: str = ""       # Pass/Fail
    created_at: float = 0.0
```

### 8.3 Parser 配置
```python
# Section Header 正则
SECTION_PATTERN = r'\[([\w/_\-]+)\]'

# KV 提取正则 (支持 `: ` 和 `=`)
KV_PATTERN = r'^\s*([\w\[\]]+)\s*[:=]\s*(.+)$'

# Cycles 行
CYCLES_PATTERN = r'^Cycles:(\d+)$'

# 结果行
RESULT_PATTERN = r'Result\s*:\s*(Pass|Fail)'

# Hex Dump 判断: 匹配行首为 `Offset:` 或 `...xxx:` 或纯十六进制
HEX_DUMP_PATTERN = r'^(Offset:|\.\.\.\d+:|[0-9a-fA-F]{2}(\s+[0-9a-fA-F]{2})*)\s*$'
```

## 9. KV 键名规范化

解析时需规范化键名以便查询:
| 原始键名 | 规范化键名 |
|---------|-----------|
| `bFWVersion[64]` | `bFWVersion` |
| `[SLC] WearGap` | `SLC_WearGap` |
| `eMMC_EXT_CSD` | 特殊 Section，不解析具体 KV |

## 10. 定时监控设计

```
监控流程:
1. 启动时全量扫描已有日志文件
2. 定期扫描监控目录 (默认 5 分钟间隔)
3. 发现新文件或文件变更时自动解析
4. 支持信号文件触发 (如 trigger.txt)
5. 解析完成后自动清除信号文件
6. 解析失败记录到 test_summary.parse_status='Failed'
```

### 10.1 信号文件机制
```
监控目录结构:
logs/
├── RTMS_RTMSLOG_0.txt
├── RTMS_RTMSLOG_1.txt
└── .trigger              # 信号文件 (存在时触发解析，完成后删除)

触发流程:
1. 检测到 .trigger 文件存在
2. 扫描目录下所有 .txt/.log 文件
3. 执行增量解析
4. 解析完成后删除 .trigger
```

### 10.2 main.py 命令行接口
```bash
# 单次解析
python main.py --parse

# 启动定时监控 (默认 5 分钟间隔)
python main.py --watch

# 指定间隔 (分钟)
python main.py --watch --interval 10

# 导出 RMA 报告
python main.py --export --output report.xlsx

# 组合: 监控 + 导出
python main.py --watch --export --interval 5
```

## 7. 技术选型

- **数据库**: SQLite (轻量, 零配置, 支持 Windows)
- **Excel导出**: openpyxl
- **日志**: 内置 logging 模块
- **测试**: pytest (可选)
- **定时监控**: 内置 threading.Timer / time.sleep 循环
- **增量判断**: 文件大小 (size) + 修改时间 (mtime)

## 8. 注意事项

1. **Hex Dump 跳过**: EXTCSD 区域的 hex dump 行需识别并跳过
2. **自由文本保留**: BM_table_match 中的文本行需整体作为一条 KV 记录
3. **增量处理**: 使用文件哈希避免重复解析
4. **中文注释**: 所有代码使用中文注释
