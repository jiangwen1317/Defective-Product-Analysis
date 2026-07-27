"""
配置模块 - 用户配置加载与验证。

配置来源：config.json（用户配置，唯一的配置入口）

注意：所有默认值在代码中硬编码，不在 DEFAULT_CONFIG 中重复定义。
这样设计的优势：
1. 单一数据源 - 避免多处配置导致的不一致
2. 清晰的责任边界 - config.json 是用户入口，代码是系统默认值
3. 易于维护 - 配置项与使用代码在一起
"""

import json
import logging
import os
from typing import Any

from router.gateway import GatewayConfig

logger = logging.getLogger(__name__)

# 配置文件路径
_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")


def load_config(config_path: str = _CONFIG_PATH) -> dict:
    """加载用户配置。

    Args:
        config_path: 配置文件路径。

    Returns:
        配置字典。配置文件不存在时返回空字典。
    """
    if not os.path.exists(config_path):
        logger.error("配置文件不存在: %s", config_path)
        return {}

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        logger.info("配置加载成功: %s", config_path)
        return config

    except json.JSONDecodeError as e:
        logger.error("配置文件格式错误: %s", e)
        return {}
    except Exception as e:
        logger.error("加载配置文件失败: %s", e)
        return {}


def get_gateway_config(config: dict[str, Any] | None = None) -> GatewayConfig:
    """获取网关配置。

    从 config.json 加载，缺失的字段使用代码中的硬编码默认值。

    Args:
        config: 配置字典。为 None 时自动加载 config.json。

    Returns:
        网关配置对象。
    """
    if config is None:
        config = load_config()

    gw = config.get("gateway", {})

    # 验证端口号
    arm_port = gw.get("arm_port", 8080)
    if not isinstance(arm_port, int) or not (1 <= arm_port <= 65535):
        logger.warning("arm_port 无效，使用默认值 8080: %r", arm_port)
        arm_port = 8080

    # 验证超时
    test_timeout = gw.get("test_timeout", 30.0)
    if not isinstance(test_timeout, (int, float)) or test_timeout <= 0:
        logger.warning("test_timeout 无效，使用默认值 30.0: %r", test_timeout)
        test_timeout = 30.0

    # 获取设备配置
    devices_config = config.get("devices", {})

    # 获取通信模式（必需配置）
    arm_mode = gw.get("arm_mode")
    if not arm_mode:
        raise ValueError("配置缺失: gateway.arm_mode 未设置")

    # 串口模式配置（必需配置）
    arm_serial_port = gw.get("arm_serial_port")
    arm_serial_baudrate = gw.get("arm_serial_baudrate")
    if arm_mode == "serial":
        if not arm_serial_port:
            raise ValueError("配置缺失: gateway.arm_serial_port 未设置（串口模式需要）")
        if arm_serial_baudrate is None:
            raise ValueError("配置缺失: gateway.arm_serial_baudrate 未设置（串口模式需要）")
        arm_serial_baudrate = int(arm_serial_baudrate)

    return GatewayConfig(
        arm_mode=arm_mode,
        arm_host=gw.get("arm_host", "0.0.0.0"),
        arm_port=arm_port,
        arm_target_host=gw.get("arm_target_host", ""),
        arm_target_port=gw.get("arm_target_port", 0),
        arm_reconnect_interval=float(gw.get("arm_reconnect_interval", 5.0)),
        # 串口配置（必须有值，否则抛出异常）
        arm_serial_port=arm_serial_port,
        arm_serial_baudrate=arm_serial_baudrate,
        arm_serial_bytesize=int(gw.get("arm_serial_bytesize", 8)),
        arm_serial_stopbits=int(gw.get("arm_serial_stopbits", 1)),
        arm_serial_parity=str(gw.get("arm_serial_parity", "N")),
        # 测试配置
        test_timeout=float(test_timeout),
        # 多设备配置
        devices_config=devices_config,
    )


def get_ui_config(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """获取 UI 配置。

    Args:
        config: 配置字典。为 None 时自动加载 config.json。

    Returns:
        UI 配置字典，包含 window_width, window_height, log_max_lines, theme。
    """
    if config is None:
        config = load_config()

    ui = config.get("ui", {})

    return {
        "window_width": ui.get("window_width", 1200),
        "window_height": ui.get("window_height", 800),
        "log_max_lines": ui.get("log_max_lines", 5000),
        "theme": ui.get("theme", "dark"),
    }


def get_configured_dut_indices(config: dict[str, Any] | None = None) -> list[int]:
    """获取已配置的 DUT 编号列表。

    IP 非空的 DUT 视为已配置。

    Args:
        config: 配置字典。为 None 时自动加载 config.json。

    Returns:
        已配置的 DUT 编号列表，如 [1, 2]。
    """
    if config is None:
        config = load_config()

    configured = []
    devices = config.get("devices", {})

    for i in range(1, 9):
        dut_config = devices.get(f"dut{i}", {})
        ip = dut_config.get("ip", "")
        if ip and ip.strip():
            configured.append(i)

    return configured
