"""
适配器单元测试。

测试 BaseArmAdapter 及其子类的功能。
"""

import threading
import time
from unittest.mock import MagicMock, Mock, patch

import pytest
from adapters import ArmAdapter, ArmAdapterMode, BaseArmAdapter, SerialArmAdapter


class TestBaseArmAdapterInit:
    """BaseArmAdapter 初始化测试。"""

    def test_base_arm_adapter_is_abstract(self):
        """测试 BaseArmAdapter 是抽象类。"""
        with pytest.raises(TypeError):
            BaseArmAdapter()


class TestArmAdapterInit:
    """ArmAdapter 初始化测试。"""

    def test_init_default_values(self):
        """测试默认值初始化。"""
        adapter = ArmAdapter()

        assert adapter._host == "0.0.0.0"
        assert adapter._port == 8080
        assert adapter._mode == ArmAdapterMode.SERVER
        assert adapter._running is False
        assert adapter._connected is False

    def test_init_client_mode(self):
        """测试 Client 模式初始化。"""
        adapter = ArmAdapter(
            mode="tcp_client",
            target_host="192.168.1.100",
            target_port=8080,
        )

        assert adapter._mode == ArmAdapterMode.CLIENT
        assert adapter._target_host == "192.168.1.100"
        assert adapter._target_port == 8080

    def test_init_with_callbacks(self):
        """测试带回调初始化。"""
        connected_cb = Mock()
        disconnected_cb = Mock()
        data_cb = Mock()
        error_cb = Mock()

        adapter = ArmAdapter(
            on_connected=connected_cb,
            on_disconnected=disconnected_cb,
            on_data_received=data_cb,
            on_error=error_cb,
        )

        assert adapter._on_connected is connected_cb
        assert adapter._on_disconnected is disconnected_cb
        assert adapter._on_data_received is data_cb
        assert adapter._on_error is error_cb

    def test_reconnect_lock_exists(self):
        """测试重连锁存在。"""
        adapter = ArmAdapter()

        assert hasattr(adapter, '_reconnect_lock')
        assert isinstance(adapter._reconnect_lock, type(threading.Lock()))


class TestArmAdapterProperties:
    """ArmAdapter 属性测试。"""

    def test_mode_property(self):
        """测试 mode 属性。"""
        adapter = ArmAdapter(mode="tcp_server")
        assert adapter.mode == ArmAdapterMode.SERVER

        adapter = ArmAdapter(mode="tcp_client", target_host="192.168.1.1", target_port=8080)
        assert adapter.mode == ArmAdapterMode.CLIENT

    def test_host_property_server_mode(self):
        """测试 host 属性（Server 模式）。"""
        adapter = ArmAdapter(host="0.0.0.0", port=8080, mode="tcp_server")
        assert adapter.host == "0.0.0.0"

    def test_host_property_client_mode(self):
        """测试 host 属性（Client 模式）。"""
        adapter = ArmAdapter(
            mode="tcp_client",
            target_host="192.168.1.100",
            target_port=8080,
        )
        assert adapter.host == "192.168.1.100"

    def test_is_connected_initial_state(self):
        """测试初始连接状态。"""
        adapter = ArmAdapter()
        assert adapter.is_connected is False


class TestArmAdapterLifecycle:
    """ArmAdapter 生命周期测试。"""

    def test_start_twice_returns_true(self):
        """测试重复启动返回 True。"""
        adapter = ArmAdapter()

        # 模拟 Server 模式启动
        with patch.object(adapter, '_start_server_mode', return_value=True):
            result1 = adapter.start()
            assert result1 is True
            assert adapter._running is True

            result2 = adapter.start()
            assert result2 is True

    def test_stop_when_not_running(self):
        """测试未运行时停止（无异常）。"""
        adapter = ArmAdapter()

        # 不应抛出异常
        adapter.stop()
        assert adapter._running is False

    def test_stop_when_running(self):
        """测试运行时停止。"""
        adapter = ArmAdapter()
        adapter._running = True
        adapter._connected = True
        adapter._client_socket = Mock()

        with patch.object(adapter, '_do_disconnect'):
            adapter.stop()

        assert adapter._running is False


class TestArmAdapterSendRaw:
    """ArmAdapter send_raw 测试。"""

    def test_send_raw_not_connected(self):
        """测试未连接时发送。"""
        adapter = ArmAdapter()

        result = adapter.send_raw("test data")
        assert result is False

    def test_send_raw_connected(self):
        """测试连接时发送。"""
        adapter = ArmAdapter()
        adapter._running = True
        adapter._connected = True
        adapter._client_socket = Mock()

        with patch.object(adapter, '_write_data', return_value=True) as mock_write:
            result = adapter.send_raw("test data")

        assert result is True
        mock_write.assert_called_once_with("test data")


class TestSerialArmAdapterInit:
    """SerialArmAdapter 初始化测试。"""

    def test_init_default_values(self):
        """测试默认值初始化。"""
        adapter = SerialArmAdapter()

        assert adapter._port == "COM3"
        assert adapter._baudrate == 115200
        assert adapter._running is False

    def test_init_custom_values(self):
        """测试自定义值初始化。"""
        adapter = SerialArmAdapter(
            port="COM5",
            baudrate=57600,
        )

        assert adapter._port == "COM5"
        assert adapter._baudrate == 57600

    def test_port_name_property(self):
        """测试 port_name 属性。"""
        adapter = SerialArmAdapter(port="COM10")
        assert adapter.port_name == "COM10"

    def test_baudrate_property(self):
        """测试 baudrate 属性。"""
        adapter = SerialArmAdapter(baudrate=38400)
        assert adapter.baudrate == 38400


class TestSerialArmAdapterLifecycle:
    """SerialArmAdapter 生命周期测试。"""

    def test_start_fails_with_invalid_port(self):
        """测试无效端口启动失败。"""
        adapter = SerialArmAdapter(port="INVALID_PORT")

        result = adapter.start()
        assert result is False
        assert adapter._running is False

    def test_is_connected_initial_state(self):
        """测试初始连接状态。"""
        adapter = SerialArmAdapter()
        assert adapter.is_connected is False


class TestArmAdapterReconnect:
    """ArmAdapter 重连测试。"""

    def test_start_reconnect_sets_flag(self):
        """测试启动重连设置标志。"""
        adapter = ArmAdapter()
        adapter._running = True
        adapter._stop_reconnect.clear()
        adapter._reconnecting = False
        adapter._reconnect_thread = None

        with patch('threading.Thread') as mock_thread:
            mock_thread_instance = Mock()
            mock_thread.return_value = mock_thread_instance

            adapter._start_reconnect()

            assert adapter._reconnecting is True
            mock_thread.assert_called_once()

    def test_start_reconnect_when_already_reconnecting(self):
        """测试重复启动重连。"""
        adapter = ArmAdapter()
        adapter._running = True
        adapter._reconnecting = True

        with patch('threading.Thread') as mock_thread:
            adapter._start_reconnect()

            # 不应该再创建线程
            mock_thread.assert_not_called()


class TestArmAdapterClientAddress:
    """ArmAdapter client_address 测试。"""

    def test_client_address_no_socket(self):
        """测试无 socket 时返回 None。"""
        adapter = ArmAdapter()
        adapter._client_socket = None

        assert adapter.client_address is None

    def test_client_address_server_mode(self):
        """测试 Server 模式返回远程地址。"""
        adapter = ArmAdapter(mode="tcp_server")
        adapter._client_socket = Mock()
        adapter._client_socket.getpeername.return_value = ("192.168.1.100", 12345)

        assert adapter.client_address == "('192.168.1.100', 12345)"

    def test_client_address_client_mode(self):
        """测试 Client 模式返回目标地址。"""
        adapter = ArmAdapter(
            mode="tcp_client",
            target_host="192.168.1.100",
            target_port=8080,
        )
        adapter._client_socket = Mock()

        assert adapter.client_address == "192.168.1.100:8080"
