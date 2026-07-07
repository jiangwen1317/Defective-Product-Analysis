"""
配置模块 - 连接参数与默认值管理。

提供配置文件的加载、保存功能，支持热加载。
"""

import json
import logging
import os
from typing import Any

from router.gateway import GatewayConfig

logger = logging.getLogger(__name__)

# 模块所在目录
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# 默认配置文件路径
DEFAULT_CONFIG_PATH = os.path.join(_SCRIPT_DIR, "config.json")

# 默认配置
DEFAULT_CONFIG: dict[str, Any] = {
    "gateway": {
        # 机械臂通信模式: tcp_server | tcp_client | serial
        "arm_mode": "tcp_server",
        # TCP Server 模式
        "arm_host": "0.0.0.0",
        "arm_port": 8080,
        # TCP Client 模式
        "arm_target_host": "",  # Client 模式目标地址
        "arm_target_port": 0,  # Client 模式目标端口
        "arm_reconnect_interval": 5.0,  # Client 模式重连间隔（秒）
        # 串口模式 (serial)
        "arm_serial_port": "COM3",  # 串口名称
        "arm_serial_baudrate": 115200,  # 波特率
        # 串口高级参数（通常使用默认值即可）
        "arm_serial_bytesize": 8,  # 数据位: 5, 6, 7, 8
        "arm_serial_stopbits": 1,  # 停止位: 1, 1.5, 2
        "arm_serial_parity": "N",  # 校验位: N(None), E(Even), O(Odd)
        # 3720 配置
        "tc3720_mode": "simulator",
        "tc3720_host": "192.168.1.101",
        "tc3720_port": 9090,
        "test_timeout": 30.0,
        "enable_debug": False,
    },
    "ui": {
        "window_width": 1000,
        "window_height": 700,
        "log_max_lines": 5000,
        "theme": "dark",
    },
}


def load_config(config_path: str = DEFAULT_CONFIG_PATH) -> dict:
    """加载配置文件。

    Args:
        config_path: 配置文件路径，默认使用模块目录下的 config.json。

    Returns:
        配置字典。配置文件不存在时返回默认配置。
    """
    if not os.path.exists(config_path):
        logger.warning("配置文件不存在: %s，使用默认配置", config_path)
        return DEFAULT_CONFIG.copy()

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

        # 合并默认配置（确保所有必需字段存在）
        merged = DEFAULT_CONFIG.copy()
        _deep_merge(merged, config)

        return merged

    except json.JSONDecodeError as e:
        logger.error("配置文件格式错误: %s", e)
        return DEFAULT_CONFIG.copy()
    except Exception as e:
        logger.error("加载配置文件失败: %s", e)
        return DEFAULT_CONFIG.copy()


def save_config(config: dict, config_path: str = DEFAULT_CONFIG_PATH) -> bool:
    """保存配置到文件。

    Args:
        config: 配置字典。
        config_path: 配置文件路径。

    Returns:
        保存是否成功。
    """
    try:
        # 确保目录存在
        directory = os.path.dirname(config_path)
        if directory and not os.path.exists(directory):
            os.makedirs(directory, exist_ok=True)

        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4, ensure_ascii=False)

        logger.info("配置已保存: %s", config_path)
        return True

    except Exception as e:
        logger.error("保存配置文件失败: %s", e)
        return False


def _deep_merge(target: dict[str, Any], source: dict[str, Any]) -> None:
    """深度合并字典。

    将 source 中的值合并到 target 中，
    对于嵌套字典递归合并，对于其他类型直接覆盖。

    Args:
        target: 目标字典（会被修改）。
        source: 源字典。
    """
    for key, value in source.items():
        if key in target and isinstance(target[key], dict) and isinstance(value, dict):
            _deep_merge(target[key], value)
        else:
            target[key] = value


def get_gateway_config(config: dict[str, Any] | None = None) -> GatewayConfig:
    """获取网关配置。

    Args:
        config: 配置字典。为 None 时自动加载配置文件。

    Returns:
        网关配置对象。

    Raises:
        ValueError: 配置类型错误时抛出。
    """
    if config is None:
        config = load_config()

    gw = config.get("gateway", DEFAULT_CONFIG["gateway"])

    # 类型验证
    arm_port = gw.get("arm_port", 8080)
    tc3720_port = gw.get("tc3720_port", 9090)
    test_timeout = gw.get("test_timeout", 30.0)

    if not isinstance(arm_port, int) or not (1 <= arm_port <= 65535):
        raise ValueError(f"arm_port 必须是 1-65535 之间的整数，当前值: {arm_port!r}")
    if not isinstance(tc3720_port, int) or not (1 <= tc3720_port <= 65535):
        raise ValueError(f"tc3720_port 必须是 1-65535 之间的整数，当前值: {tc3720_port!r}")
    if not isinstance(test_timeout, (int, float)) or test_timeout <= 0:
        raise ValueError(f"test_timeout 必须是正数，当前值: {test_timeout!r}")

    return GatewayConfig(
        arm_mode=gw.get("arm_mode", "tcp_server"),
        arm_host=gw.get("arm_host", "0.0.0.0"),
        arm_port=arm_port,
        arm_target_host=gw.get("arm_target_host", ""),
        arm_target_port=gw.get("arm_target_port", 0),
        arm_reconnect_interval=float(gw.get("arm_reconnect_interval", 5.0)),
        # 串口配置
        arm_serial_port=gw.get("arm_serial_port", "COM3"),
        arm_serial_baudrate=int(gw.get("arm_serial_baudrate", 115200)),
        arm_serial_bytesize=int(gw.get("arm_serial_bytesize", 8)),
        arm_serial_stopbits=int(gw.get("arm_serial_stopbits", 1)),
        arm_serial_parity=str(gw.get("arm_serial_parity", "N")),
        # 3720 配置
        tc3720_mode=gw.get("tc3720_mode", "simulator"),
        tc3720_host=gw.get("tc3720_host", "192.168.1.101"),
        tc3720_port=tc3720_port,
        test_timeout=float(test_timeout),
        enable_debug=bool(gw.get("enable_debug", False)),
    )


def get_ui_config(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """获取 UI 配置。

    Args:
        config: 配置字典。为 None 时自动加载配置文件。

    Returns:
        UI 配置字典。
    """
    if config is None:
        config = load_config()

    return config.get("ui", DEFAULT_CONFIG["ui"])
