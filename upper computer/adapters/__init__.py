"""
设备适配器层。

提供与机械臂和 3720 测试仪的通信适配。
每个适配器负责一种设备的协议编解码和连接管理。
"""

from .arm_adapter import ArmAdapter
from .tc3720_adapter import TC3720Adapter, TC3720Status

__all__ = [
    "ArmAdapter",
    "TC3720Adapter",
    "TC3720Status",
]
