"""
DeviceManager 设备管理器单元测试。
"""

import threading
import time
from unittest.mock import MagicMock, Mock, patch

import pytest
from adapters import TC3720Status
from router.device_manager import DeviceManager, TestResult


class TestDeviceManagerInit:
    """设备管理器初始化测试。"""

    def test_init_default_values(self):
        """测试默认值初始化。"""
        manager = DeviceManager(devices_config={})

        assert manager.DUT_COUNT == 8
        assert manager._running is False
        assert len(manager._adapters) == 0

    def test_init_with_devices_config(self):
        """测试带设备配置的初始化。"""
        config = {
            "dut1": {"ip": "192.168.1.101", "port": 9090, "name": "Board-1"},
            "dut2": {"ip": "192.168.1.102", "port": 9090, "name": "Board-2"},
        }

        manager = DeviceManager(devices_config=config)

        assert manager._devices_config == config
        assert manager._test_timeout == 30.0

    def test_init_with_custom_timeout(self):
        """测试自定义超时。"""
        manager = DeviceManager(devices_config={}, test_timeout=60.0)

        assert manager._test_timeout == 60.0


class TestDeviceManagerStartStop:
    """设备管理器启停测试。"""

    def test_start_sets_running_flag(self):
        """测试启动设置运行标志。"""
        manager = DeviceManager(devices_config={})

        with patch.object(manager, '_init_device'):
            result = manager.start()

        assert result is True
        assert manager._running is True

    def test_start_twice_returns_true(self):
        """测试重复启动返回 True。"""
        manager = DeviceManager(devices_config={})

        with patch.object(manager, '_init_device'):
            result1 = manager.start()
            result2 = manager.start()

        assert result1 is True
        assert result2 is True

    def test_stop_clears_running_flag(self):
        """测试停止清除运行标志。"""
        manager = DeviceManager(devices_config={})

        with patch.object(manager, '_init_device'):
            manager.start()

        manager.stop()

        assert manager._running is False

    def test_stop_when_not_running(self):
        """测试未运行时停止（无异常）。"""
        manager = DeviceManager(devices_config={})

        # 不应抛出异常
        manager.stop()
        assert manager._running is False


class TestDeviceManagerDeviceInit:
    """设备初始化测试。"""

    def test_init_device_missing_config(self):
        """测试缺少配置的设备。"""
        manager = DeviceManager(devices_config={})

        with patch.object(manager, '_init_device'):
            manager.start()

        # 应该没有初始化任何设备
        assert len(manager._adapters) == 0

    def test_init_device_missing_ip(self):
        """测试缺少 IP 的设备。"""
        config = {
            "dut1": {"ip": "", "port": 9090, "name": "Board-1"},
        }
        manager = DeviceManager(devices_config=config)

        with patch('router.device_manager.TC3720TcpAdapter'):
            manager.start()

        # 应该跳过没有 IP 的设备
        assert len(manager._adapters) == 0


class TestDeviceManagerStartTest:
    """测试启动测试功能测试。"""

    def setup_method(self):
        """每个测试前的设置。"""
        self.config = {
            "dut1": {"ip": "192.168.1.101", "port": 9090, "name": "Board-1"},
            "dut2": {"ip": "192.168.1.102", "port": 9090, "name": "Board-2"},
        }
        self.manager = DeviceManager(devices_config=self.config)

    def test_start_test_empty_list(self):
        """测试空列表。"""
        with patch.object(self.manager, '_init_device'):
            self.manager.start()

        result = self.manager.start_test([])
        assert result == {}

    def test_start_test_nonexistent_device(self):
        """测试不存在的设备。"""
        with patch.object(self.manager, '_init_device'):
            self.manager.start()

        result = self.manager.start_test([99])
        # 不存在的设备应该返回失败结果
        assert result[99] is False

    def test_start_test_no_adapter(self):
        """测试没有适配器的设备。"""
        with patch.object(self.manager, '_init_device'):
            self.manager.start()

        # 不 mock 适配器，让它们为 None
        self.manager._adapters.clear()

        result = self.manager.start_test([1])
        assert result[1] is False


class TestDeviceManagerStatus:
    """设备状态管理测试。"""

    def setup_method(self):
        """每个测试前的设置。"""
        self.manager = DeviceManager(devices_config={})

    def test_get_adapter_not_exists(self):
        """测试获取不存在的适配器。"""
        result = self.manager.get_adapter(1)
        assert result is None

    def test_get_all_adapters_empty(self):
        """测试获取所有适配器（空）。"""
        result = self.manager.get_all_adapters()
        assert result == {}

    def test_get_status_no_adapter(self):
        """测试获取没有适配器的设备状态。"""
        result = self.manager.get_status(1)
        assert result == TC3720Status.OFFLINE


class TestTestResult:
    """TestResult 数据类测试。"""

    def test_test_result_creation(self):
        """测试 TestResult 创建。"""
        result = TestResult(
            dut_index=1,
            device_name="Board-1",
            ip="192.168.1.101",
            port=9090,
            error_code="1901",
            success=True,
        )

        assert result.dut_index == 1
        assert result.device_name == "Board-1"
        assert result.ip == "192.168.1.101"
        assert result.port == 9090
        assert result.error_code == "1901"
        assert result.success is True
