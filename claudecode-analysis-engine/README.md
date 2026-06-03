# EMMC 测试日志数据库分析系统

基于主表 + KV 指标表的双表模型，实现 EMMC 测试日志的解析、存储、查询和报告导出。

## 功能特性

- **增量解析**: 基于文件大小 + 修改时间判断变更，避免重复解析
- **双表模型**: 主表存储元数据，KV 表存储动态指标，支持灵活查询
- **Section 识别**: 自动识别日志中的测试环节 (Wear_Detection, BM_table_match 等)
- **数值转换**: 自动转换浮点数和十六进制值
- **错误隔离**: 单文件解析失败不影响整体流程
- **定时监控**: 支持信号文件触发和定时扫描
- **RMA 报告**: 导出 Excel 格式的分析报告

## 目录结构

```
claudecode-analysis-engine/
├── src/                    # 源代码
│   ├── __init__.py
│   ├── config.py           # 配置管理
│   ├── database.py         # 数据库连接
│   ├── models.py           # 数据模型
│   ├── parser.py           # 日志解析引擎
│   ├── query.py            # 查询接口
│   └── export.py           # 报告导出
├── logs/                   # 日志目录 (监控目标)
├── exports/                # 导出目录
├── queries/                # SQL 查询示例
├── schema.sql              # 数据库 Schema
├── config.json             # 配置文件
├── main.py                 # 主入口
└── README.md               # 使用说明
```

## 快速开始

### 1. 安装依赖

```bash
pip install openpyxl
```

### 2. 配置

编辑 `config.json` 设置监控目录和数据库路径:

```json
{
    "database": {
        "path": "emmc_analysis.db"
    },
    "monitor": {
        "directory": "./logs",
        "scan_interval": 300
    }
}
```

### 3. 单次解析

```bash
# 解析默认目录
python main.py --parse

# 解析指定目录
python main.py --parse --directory ./logs

# 解析单个文件
python main.py --parse --file ./logs/RTMS_RTMSLOG_0.txt

# 解析后自动导出报告
python main.py --parse --export
```

### 4. 定时监控

```bash
# 启动监控 (默认 5 分钟间隔)
python main.py --watch

# 指定间隔 (分钟)
python main.py --watch --interval 10
```

监控支持信号文件触发，在监控目录下创建 `.trigger` 文件可立即触发解析:

```bash
echo "" > logs/.trigger
```

### 5. 导出报告

```bash
# 使用默认配置导出
python main.py --export

# 指定输出路径
python main.py --export --output ./my_report.xlsx
```

报告包含 3 个 Sheet:
- **设备概览**: 设备信息 + 核心指标 (WAI, WA(TLC), WA(SLC))
- **详细指标**: 动态透视的 KV 宽表
- **异常汇总**: 解析失败或测试失败的记录

### 6. 查询操作

```bash
# 列出所有设备
python main.py --list-devices

# 列出所有 Section
python main.py --list-sections

# 列出所有指标
python main.py --list-metrics

# 按 Section 筛选指标
python main.py --list-metrics --section Wear_Detection

# 查看指标统计
python main.py --stat WAI

# 显示指定 ID 的详细信息
python main.py --show 1
```

## 数据库设计

### 主表 (test_summary)

存储每份日志文件的元数据和固定身份信息:

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 主键 |
| file_name | TEXT | 原始文件名 |
| device_name | TEXT | 设备名称 |
| fw_version | TEXT | 固件版本 |
| test_cycles | INTEGER | 测试循环次数 |
| test_result | TEXT | Pass/Fail |
| parse_status | TEXT | Pending/Success/Failed |

### KV 指标表 (test_metrics)

存储所有动态测试指标:

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 主键 |
| summary_id | INTEGER | 关联 test_summary |
| section | TEXT | Section 名称 |
| metric_key | TEXT | 指标键名 |
| raw_value | TEXT | 原始值 |
| num_value | REAL | 数值 |
| hex_value | TEXT | 十六进制值 |

### 核心索引

```sql
-- 纵向切片查询的关键索引
CREATE INDEX idx_metrics_key ON test_metrics(metric_key);
CREATE INDEX idx_metrics_section ON test_metrics(section);
CREATE INDEX idx_metrics_section_key ON test_metrics(section, metric_key);
```

## 日志格式

解析器支持的日志格式:

```
Device_Name              :DM3720.012.13

Start of test:
    bFWVersion[64]       :TL600E -V2.7.1
    ...

End of test:
    ...

Wear_Detection:
    WAI                  :11.980
    WA(TLC)              :13.612
    Result               :Pass!

BM_table_match:
    Result               :Fail!
```

## 命令行参考

```
使用示例:
  # 单次解析日志目录
  python main.py --parse

  # 解析指定目录
  python main.py --parse --directory ./logs

  # 解析单个文件
  python main.py --parse --file ./logs/RTMS_RTMSLOG_0.txt

  # 解析后导出报告
  python main.py --parse --export

  # 启动定时监控
  python main.py --watch

  # 指定监控间隔(分钟)
  python main.py --watch --interval 10

  # 导出报告
  python main.py --export

  # 指定输出路径
  python main.py --export --output ./report.xlsx

  # 查询操作
  python main.py --list-devices
  python main.py --list-sections
  python main.py --list-metrics --section Wear_Detection
  python main.py --stat WAI
  python main.py --show 1
```

## 编程接口

```python
from src import parse_logs, export_report, get_query

# 解析日志
results = parse_logs(directory="./logs")

# 导出报告
export_report("./report.xlsx")

# 查询数据
query = get_query()
devices = query.get_unique_devices()
metrics = query.query_metric("WAI")
```

## 注意事项

1. **Hex Dump 跳过**: eMMC_EXT_CSD 区域的 hex dump 会作为一条记录存储
2. **增量判断**: 基于文件大小 + 修改时间，非 MD5 哈希
3. **错误隔离**: 单文件解析失败不影响其他文件
4. **外键约束**: 默认启用，删除摘要会级联删除关联指标

## 许可证

MIT License
