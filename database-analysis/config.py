"""
公共配置模块

提供配置文件加载、数据库路径解析等公共功能，
供 CLI (main.py)、GUI (gui_app.py)、文件监听 (file_watcher.py) 统一使用。
"""
import json
import logging
import os

logger = logging.getLogger(__name__)

# 项目根目录（database-analysis/）
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))

# 默认配置文件路径
DEFAULT_CONFIG_PATH = os.path.join(PROJECT_DIR, "config.json")

# 默认配置（配置文件不存在时使用）
_DEFAULT_CONFIG: dict = {
    "database": {"path": "emmc_analysis.db"},
    "log_sources": {
        "scan_dirs": [],
        "file_extensions": [".txt", ".log"],
    },
    "export": {"report_dir": "reports"},
    "anomaly_thresholds": {},
}


def load_config(config_path: str = DEFAULT_CONFIG_PATH) -> dict:
    """读取配置文件，返回配置字典。

    Args:
        config_path: 配置文件路径，默认使用项目目录下的 config.json。

    Returns:
        配置字典。配置文件不存在时返回默认配置。
    """
    if not os.path.exists(config_path):
        logger.warning("配置文件不存在: %s，使用默认配置", config_path)
        return _DEFAULT_CONFIG.copy()

    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_db_path(config: dict | None = None) -> str:
    """从配置中获取数据库绝对路径。

    Args:
        config: 配置字典。为 None 时自动加载配置文件。

    Returns:
        数据库文件绝对路径。
    """
    if config is None:
        config = load_config()

    db_path = config.get("database", {}).get("path", "emmc_analysis.db")
    if not os.path.isabs(db_path):
        db_path = os.path.join(PROJECT_DIR, db_path)
    return db_path


def get_file_extensions(config: dict | None = None) -> list[str]:
    """从配置中获取日志文件扩展名列表。

    Args:
        config: 配置字典。为 None 时自动加载配置文件。

    Returns:
        文件扩展名列表（如 ['.txt', '.log']）。
    """
    if config is None:
        config = load_config()
    return config.get("log_sources", {}).get("file_extensions", [".txt", ".log"])
