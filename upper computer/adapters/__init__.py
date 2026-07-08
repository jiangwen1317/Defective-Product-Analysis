"""
设备适配器层。

提供与机械臂和 3720 测试仪的通信适配。
每个适配器负责一种设备的协议编解码和连接管理。

支持多种通信模式：
- ArmAdapter: 机械臂 TCP Server/Client 模式
- SerialArmAdapter: 机械臂串口模式
- TC3720TcpAdapter: 3720 测试仪 TCP 模式（主要使用）
- TC3720Adapter: 3720 测试仪模拟器模式（仅用于测试）

架构说明：
- BaseArmAdapter: 机械臂适配器基类，提供公共功能
- ArmAdapter/SerialArmAdapter: 继承自 BaseArmAdapter
"""

from .base_arm_adapter import BaseArmAdapter
from .arm_adapter import ArmAdapter, ArmAdapterMode
from .serial_arm_adapter import SerialArmAdapter
from .tc3720_adapter import TC3720Adapter, TC3720Status
from .tc3720_tcp_adapter import TC3720TcpAdapter

__all__ = [
    # 基类
    "BaseArmAdapter",
    # 机械臂适配器
    "ArmAdapter",
    "ArmAdapterMode",
    "SerialArmAdapter",
    # 3720 适配器
    "TC3720Adapter",
    "TC3720TcpAdapter",
    "TC3720Status",
]
