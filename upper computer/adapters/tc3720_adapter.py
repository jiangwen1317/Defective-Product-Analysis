"""
3720 芯片测试仪状态定义。

TC3720Status 为共享状态枚举，供 TC3720TcpAdapter（tc3720_tcp_adapter.py）
与设备管理器、网关、UI 各层使用。
"""

from enum import Enum


class TC3720Status(Enum):
    """3720 设备状态枚举。"""

    OFFLINE = "offline"
    IDLE = "idle"
    TESTING = "testing"
    ERROR = "error"
