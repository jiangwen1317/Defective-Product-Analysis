"""
PassthroughGateway 网关单元测试。
"""

import pytest
import sys
import threading
import time
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch, PropertyMock

# 将项目根目录添加到模块搜索路径
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from router.gateway import (
    PassthroughGateway,
    GatewayConfig,
    GatewayState,
    ErrorCode,
    TransferRecord,
)
from adapters import TC3720Status


class TestGatewayConfig:
    """GatewayConfig 数据类测试。"""

    def test_default_config(self):
        """测试默认配置。"""
        config = GatewayConfig()

        assert config.arm_mode == "tcp_server"
        assert config.arm_host == "0.0.0.0"
        assert config.arm_port == 8080
        assert config.test_timeout == 30.0
        assert config.enable_debug is False

    def test_custom_config(self):
        """测试自定义配置。"""
        config = GatewayConfig(
            arm_mode="serial",
            arm_serial_port="COM3",
            arm_serial_baudrate=57600,
            test_timeout=60.0,
            enable_debug=True,
        )

        assert config.arm_mode == "serial"
        assert config.arm_serial_port == "COM3"
        assert config.arm_serial_baudrate == 57600
        assert config.test_timeout == 60.0
        assert config.enable_debug is True


class TestTransferRecord:
    """TransferRecord 数据类测试。"""

    def test_transfer_record_default(self):
        """测试默认记录。"""
        record = TransferRecord(
            timestamp="2024-01-01 12:00:00",
            direction="arm_to_3720",
            raw_data="@TEST+",
            size=6,
        )

        assert record.error_code == ErrorCode.NONE
        assert record.error_message == ""

    def test_transfer_record_with_error(self):
        """测试带错误的记录。"""
        record = TransferRecord(
            timestamp="2024-01-01 12:00:00",
            direction="arm_to_3720",
            raw_data="invalid",
            size=7,
            error_code=ErrorCode.UNKNOWN,
            error_message="解析失败",
        )

        assert record.error_code == ErrorCode.UNKNOWN
        assert record.error_message == "解析失败"


class TestPassthroughGatewayInit:
    """网关初始化测试。"""

    def test_init_without_config(self):
        """测试无配置初始化。"""
        gateway = PassthroughGateway()

        assert gateway.state == GatewayState.IDLE
        assert gateway.is_running is False
        assert gateway._arm_adapter is None
        assert gateway._device_manager is None

    def test_init_with_callbacks(self):
        """测试带回调初始化。"""
        state_callback = Mock()
        arm_callback = Mock()

        gateway = PassthroughGateway(
            on_state_changed=state_callback,
            on_arm_connected=arm_callback,
        )

        assert gateway._on_state_changed is state_callback
        assert gateway._on_arm_connected is arm_callback

    def test_init_with_devices_config(self):
        """测试带设备配置的初始化。"""
        config = GatewayConfig(
            devices_config={
                "dut1": {"ip": "192.168.1.101", "port": 9090, "name": "Board-1"},
            }
        )

        gateway = PassthroughGateway(config=config)

        assert gateway._config.devices_config is not None


class TestPassthroughGatewayProperties:
    """网关属性测试。"""

    def test_state_property(self):
        """测试状态属性。"""
        gateway = PassthroughGateway()

        # 默认是 IDLE
        assert gateway.state == GatewayState.IDLE

    def test_is_running_property(self):
        """测试运行状态属性。"""
        gateway = PassthroughGateway()

        assert gateway.is_running is False

    def test_is_arm_connected_no_adapter(self):
        """测试机械臂连接状态（无适配器）。"""
        gateway = PassthroughGateway()

        assert gateway.is_arm_connected is False

    def test_tc3720_status_no_manager(self):
        """测试 3720 状态（无管理器）。"""
        gateway = PassthroughGateway()

        assert gateway.tc3720_status == TC3720Status.OFFLINE

    def test_arm_client_address_no_adapter(self):
        """测试机械臂地址（无适配器）。"""
        gateway = PassthroughGateway()

        assert gateway.arm_client_address is None


class TestPassthroughGatewayStateManagement:
    """网关状态管理测试。"""

    def test_clear_alarm(self):
        """测试清除告警。"""
        gateway = PassthroughGateway()

        gateway.clear_alarm()

        assert gateway.state == GatewayState.IDLE


class TestPassthroughGatewayTriggerTest:
    """主动触发测试功能测试。"""

    def test_trigger_test_no_adapter(self):
        """测试无适配器触发。"""
        gateway = PassthroughGateway()

        result = gateway.trigger_test()

        assert result is False

    def test_trigger_test_adapter_not_connected(self):
        """测试适配器未连接时触发。"""
        gateway = PassthroughGateway()

        # 创建一个假的适配器
        mock_adapter = Mock()
        mock_adapter.is_connected = False
        gateway._arm_adapter = mock_adapter

        result = gateway.trigger_test()

        assert result is False

    def test_trigger_test_without_send_raw(self):
        """测试适配器没有 send_raw 方法。"""
        gateway = PassthroughGateway()

        # 创建一个没有 send_raw 方法的模拟适配器
        mock_adapter = Mock(spec=[])
        mock_adapter.is_connected = True
        gateway._arm_adapter = mock_adapter

        result = gateway.trigger_test()

        assert result is False


class TestPassthroughGatewayStartStop:
    """网关启停测试。"""

    def test_start_when_already_running(self):
        """测试重复启动。"""
        gateway = PassthroughGateway()
        gateway._running = True

        result = gateway.start()

        assert result is True

    def test_stop_when_not_running(self):
        """测试未运行时停止。"""
        gateway = PassthroughGateway()

        # 不应抛出异常
        gateway.stop()

        assert gateway.is_running is False


class TestPassthroughGatewayBitmaskHandling:
    """Bitmask 处理测试。"""

    def test_get_device_status_summary_no_manager(self):
        """测试获取设备状态摘要（无管理器）。"""
        gateway = PassthroughGateway()

        result = gateway.get_device_status_summary()

        assert result == {}

    def test_on_start_test_empty_params(self):
        """测试处理空参数。"""
        gateway = PassthroughGateway()

        # 不应抛出异常
        gateway.on_start_test("", "")


class TestGatewayErrorCodes:
    """网关错误码测试。"""

    def test_error_codes_defined(self):
        """测试错误码定义。"""
        assert ErrorCode.NONE.value == "0000"
        assert ErrorCode.ARM_DISCONNECTED.value == "E003"
        assert ErrorCode.TC3720_ERROR.value == "E004"
        assert ErrorCode.UNKNOWN.value == "EEEE"


class TestGatewayState:
    """网关状态枚举测试。"""

    def test_states_defined(self):
        """测试状态定义。"""
        assert GatewayState.IDLE.value == "idle"
        assert GatewayState.FORWARDING.value == "forwarding"
        assert GatewayState.ERROR.value == "error"

    def test_state_ordering(self):
        """测试状态顺序。"""
        # GatewayState 枚举值
        assert len(GatewayState) == 3
        assert GatewayState.IDLE is not None
        assert GatewayState.FORWARDING is not None
        assert GatewayState.ERROR is not None
