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
# 注意：实际 IP 配置请修改 config.json，本文件仅作为默认值参考
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
        # 测试超时
        "test_timeout": 30.0,
        "enable_debug": True,  # 开发环境建议开启
    },
    # 多设备配置：DUT #1-8 对应的 3720 测试仪 IP
    # 实际 IP 请在 config.json 中配置
    # Bitmask 中哪一位为 1，就使用对应 DUT 的 IP
    # 例如：Bitmask=11000000 表示测试 DUT #1 和 #2
    "devices": {
        "dut1": {"ip": "", "port": 9090, "name": "Board-1"},  # TODO: 配置实际 IP
        "dut2": {"ip": "", "port": 9090, "name": "Board-2"},
        "dut3": {"ip": "", "port": 9090, "name": "Board-3"},
        "dut4": {"ip": "", "port": 9090, "name": "Board-4"},
        "dut5": {"ip": "", "port": 9090, "name": "Board-5"},
        "dut6": {"ip": "", "port": 9090, "name": "Board-6"},
        "dut7": {"ip": "", "port": 9090, "name": "Board-7"},
        "dut8": {"ip": "", "port": 9090, "name": "Board-8"},
    },
    "ui": {
        "window_width": 1200,
        "window_height": 800,
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
    test_timeout = gw.get("test_timeout", 30.0)

    if not isinstance(arm_port, int) or not (1 <= arm_port <= 65535):
        raise ValueError(f"arm_port 必须是 1-65535 之间的整数，当前值: {arm_port!r}")
    if not isinstance(test_timeout, (int, float)) or test_timeout <= 0:
        raise ValueError(f"test_timeout 必须是正数，当前值: {test_timeout!r}")

    # 获取多设备配置
    devices_config = config.get("devices", DEFAULT_CONFIG.get("devices", {}))

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
        # 测试配置
        test_timeout=float(test_timeout),
        enable_debug=bool(gw.get("enable_debug", False)),
        # 多设备配置
        devices_config=devices_config,
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
