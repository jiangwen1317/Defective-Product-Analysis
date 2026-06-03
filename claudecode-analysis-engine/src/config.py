# -*- coding: utf-8 -*-
"""
配置管理模块

定义解析器的配置项，支持从 JSON 文件加载配置。
"""

import json
import os
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class DatabaseConfig:
    """数据库配置"""
    path: str = "emmc_analysis.db"  # SQLite 数据库文件路径


@dataclass
class MonitorConfig:
    """监控配置"""
    directory: str = "./logs"           # 监控目录
    trigger_file: str = ".trigger"      # 信号文件名
    scan_interval: int = 300            # 扫描间隔(秒), 默认 5 分钟
    extensions: List[str] = field(default_factory=lambda: [".txt", ".log"])  # 监控的文件扩展名


@dataclass
class ParserConfig:
    """解析器配置"""
    skip_sections: List[str] = field(default_factory=lambda: ["eMMC_EXT_CSD"])
    encoding: str = "utf-8"
    max_line_length: int = 10000


@dataclass
class ExportConfig:
    """导出配置"""
    output_dir: str = "./exports"       # 导出目录
    sheet_device_overview: str = "设备概览"
    sheet_detailed_metrics: str = "详细指标"
    sheet_anomaly_summary: str = "异常汇总"


@dataclass
class Config:
    """全局配置"""
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    monitor: MonitorConfig = field(default_factory=MonitorConfig)
    parser: ParserConfig = field(default_factory=ParserConfig)
    export: ExportConfig = field(default_factory=ExportConfig)


def _get_default_config_path() -> str:
    """获取默认配置文件路径"""
    return os.path.join(os.path.dirname(__file__), "config.json")


def load_config(config_path: Optional[str] = None) -> Config:
    """
    加载配置文件。

    Args:
        config_path: 配置文件路径, 默认使用 config.json

    Returns:
        Config 对象

    Raises:
        FileNotFoundError: 配置文件不存在
        json.JSONDecodeError: JSON 解析失败
    """
    if config_path is None:
        config_path = _get_default_config_path()

    # 如果配置文件不存在,返回默认配置
    if not os.path.exists(config_path):
        return Config()

    with open(config_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 构建配置对象
    database_config = DatabaseConfig(**data.get("database", {}))
    monitor_config = MonitorConfig(**data.get("monitor", {}))
    parser_config = ParserConfig(**data.get("parser", {}))
    export_config = ExportConfig(**data.get("export", {}))

    return Config(
        database=database_config,
        monitor=monitor_config,
        parser=parser_config,
        export=export_config,
    )


def save_default_config(config_path: Optional[str] = None):
    """
    保存默认配置文件。

    Args:
        config_path: 配置文件路径
    """
    if config_path is None:
        config_path = _get_default_config_path()

    config = Config()

    data = {
        "database": {
            "path": config.database.path,
        },
        "monitor": {
            "directory": config.monitor.directory,
            "trigger_file": config.monitor.trigger_file,
            "scan_interval": config.monitor.scan_interval,
            "extensions": config.monitor.extensions,
        },
        "parser": {
            "skip_sections": config.parser.skip_sections,
            "encoding": config.parser.encoding,
            "max_line_length": config.parser.max_line_length,
        },
        "export": {
            "output_dir": config.export.output_dir,
        },
    }

    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
