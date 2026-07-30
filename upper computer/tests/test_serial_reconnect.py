"""串口适配器自动重连测试。

串口模式此前不自动重连（USB 拔插后需人工重启服务），
现已接入 ReconnectMixin：断开后自动重连，重连成功补发初始化序列。
"""

from unittest.mock import Mock, patch

import serial
from adapters.serial_arm_adapter import SerialArmAdapter


class TestSerialAutoReconnect:
    """串口断开后应自动启动重连。"""

    def test_disconnect_triggers_reconnect_when_running(self):
        """运行中断开：应调用 _start_reconnect（修复前被覆盖方法禁用）。"""
        adapter = SerialArmAdapter()
        adapter._running = True

        with patch.object(adapter, "_start_reconnect") as mock_reconnect:
            adapter._on_disconnected_internal()

        mock_reconnect.assert_called_once()

    def test_disconnect_no_reconnect_when_stopped(self):
        """已停止时断开：不应启动重连。"""
        adapter = SerialArmAdapter()
        adapter._running = False

        with patch.object(adapter, "_start_reconnect") as mock_reconnect:
            adapter._on_disconnected_internal()

        mock_reconnect.assert_not_called()

    def test_reconnect_success_resends_init_sequence(self):
        """重连成功：应先补发初始化序列，再启动接收线程。"""
        adapter = SerialArmAdapter()
        call_order: list[str] = []

        with patch.object(
            adapter, "_send_init_sequence",
            side_effect=lambda: call_order.append("init"),
        ), patch.object(
            adapter, "_start_receive_thread",
            side_effect=lambda: call_order.append("receive"),
        ):
            adapter._on_reconnect_success()

        assert call_order == ["init", "receive"]


class TestSerialConnectErrorReporting:
    """重连循环中的连接失败不应向 UI 刷屏告警。"""

    def test_connect_failure_reports_error_when_not_reconnecting(self):
        """首次连接失败：应触发 on_error。"""
        errors: list[str] = []
        adapter = SerialArmAdapter(on_error=errors.append)

        with patch("adapters.serial_arm_adapter.serial.Serial",
                   side_effect=serial.SerialException("port not found")):
            assert adapter._do_connect() is False

        assert len(errors) == 1

    def test_connect_failure_silent_during_reconnect(self):
        """重连周期中的失败：只记日志，不触发 on_error。"""
        errors: list[str] = []
        adapter = SerialArmAdapter(on_error=errors.append)
        adapter._reconnecting = True

        with patch("adapters.serial_arm_adapter.serial.Serial",
                   side_effect=serial.SerialException("port not found")):
            assert adapter._do_connect() is False

        assert errors == []


class TestSerialReconnectReleasesStaleHandle:
    """重连前必须释放旧串口句柄（Windows 下 COM 口否则被占用）。"""

    def test_do_connect_closes_stale_serial_first(self):
        """_do_connect 应先关闭残留的旧句柄再打开新串口。"""
        adapter = SerialArmAdapter()
        stale = Mock()
        adapter._serial = stale

        with patch("adapters.serial_arm_adapter.serial.Serial") as mock_serial:
            assert adapter._do_connect() is True

        stale.close.assert_called_once()
        assert adapter._serial is mock_serial.return_value
