"""
信号路由层。

实现机械臂与 3720 测试仪之间的全自动信号透传逻辑。
支持多设备管理，根据 Bitmask 路由到对应的 3720 测试仪。
"""

from .device_manager import DeviceConfig, DeviceManager, TestResult
from .gateway import (
    ErrorCode,
    GatewayConfig,
    GatewayState,
    SignalGateway,
    TransferRecord,
)

__all__ = [
    "SignalGateway",
    "GatewayState",
    "GatewayConfig",
    "TransferRecord",
    "ErrorCode",
    "DeviceManager",
    "DeviceConfig",
    "TestResult",
]
