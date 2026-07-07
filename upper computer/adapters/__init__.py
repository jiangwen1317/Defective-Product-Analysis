"""
设备适配器层。

提供与机械臂和 3720 测试仪的通信适配。
每个适配器负责一种设备的协议编解码和连接管理。

支持多种通信模式：
- ArmAdapter: 机械臂 TCP Server/Client 模式
- SerialArmAdapter: 机械臂串口模式
- TC3720TcpAdapter: 3720 测试仪 TCP 模式
- TC3720Adapter: 3720 测试仪模拟器模式
"""

from .arm_adapter import ArmAdapter
from .serial_arm_adapter import SerialArmAdapter
from .tc3720_adapter import TC3720Adapter, TC3720Status
from .tc3720_tcp_adapter import TC3720TcpAdapter

__all__ = [
    "ArmAdapter",
    "SerialArmAdapter",
    "TC3720Adapter",
    "TC3720TcpAdapter",
    "TC3720Status",
]
