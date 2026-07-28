"""断线检测与配置模板修复回归测试。

覆盖以下修复：
1. ArmAdapter._read_available 空 recv 语义（修复前对端关闭被映射为"无数据"，
   断线永远检测不到；Server 模式还会因 select 对已关闭 socket 立即返回可读
   而陷入忙旋转，UI 永远显示已连接）
2. SerialArmAdapter._read_available 吞 SerialException（修复前 USB 拔出后
   接收循环永不退出，断线检测不到）
3. ArmAdapter Server 模式断开后不再启动无意义的重连线程
   （_do_connect 恒返回 False，重连线程只会静默空转）
4. 基类接收循环对 ConnectionError 走断开流程而非错误上报
5. 示例配置模板可直接使用（含 devices 节、无失效键）
"""

import json
import socket
import sys
import time
from pathlib import Path
from unittest.mock import Mock, PropertyMock, patch

import pytest
import serial

# 将项目根目录添加到模块搜索路径
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from adapters.arm_adapter import ArmAdapter
from adapters.base_arm_adapter import BaseArmAdapter
from adapters.serial_arm_adapter import SerialArmAdapter


def _wait_until(predicate, timeout: float = 3.0) -> bool:
    """轮询等待条件成立，避免固定 sleep 导致的用例不稳定。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


class TestArmAdapterReadAvailable:
    """修复1：空 recv 与链路异常必须抛 ConnectionError。"""

    def _make_adapter_with_socket(self, sock) -> ArmAdapter:
        adapter = ArmAdapter(mode="tcp_server")
        adapter._client_socket = sock
        return adapter

    def test_empty_recv_raises_connection_error(self):
        """对端正常关闭（recv 返回空字节）应抛出 ConnectionError。"""
        sock = Mock()
        sock.recv.return_value = b""
        adapter = self._make_adapter_with_socket(sock)

        with patch("adapters.arm_adapter.select") as mock_select:
            mock_select.select.return_value = ([sock], [], [])
            with pytest.raises(ConnectionError):
                adapter._read_available()

    def test_os_error_raises_connection_error(self):
        """ECONNRESET 等链路异常应抛出 ConnectionError（修复前被裸 except 吞掉）。"""
        sock = Mock()
        sock.recv.side_effect = OSError("connection reset by peer")
        adapter = self._make_adapter_with_socket(sock)

        with patch("adapters.arm_adapter.select") as mock_select:
            mock_select.select.return_value = ([sock], [], [])
            with pytest.raises(ConnectionError):
                adapter._read_available()

    def test_no_data_returns_none(self):
        """超时无数据仍返回 None（与断开语义严格区分）。"""
        sock = Mock()
        adapter = self._make_adapter_with_socket(sock)

        with patch("adapters.arm_adapter.select") as mock_select:
            mock_select.select.return_value = ([], [], [])
            assert adapter._read_available() is None


class TestServerModeDisconnectDetection:
    """修复1+3：Server 模式真实断线检测（真实 socket 集成测试）。"""

    def test_client_close_triggers_disconnect_without_reconnect_thread(self):
        """客户端关闭后：is_connected 变 False、on_disconnected 触发、不起重连线程。"""
        disconnected: list[bool] = []
        adapter = ArmAdapter(
            host="127.0.0.1",
            port=0,  # 由内核分配临时端口
            mode="tcp_server",
            on_disconnected=lambda a: disconnected.append(True),
        )
        assert adapter.start()
        try:
            port = adapter._server_socket.getsockname()[1]
            client = socket.create_connection(("127.0.0.1", port), timeout=3)
            assert _wait_until(lambda: adapter.is_connected), "客户端未接入"

            client.close()

            # 修复前：断开永远检测不到，is_connected 恒为 True
            assert _wait_until(lambda: not adapter.is_connected), "断线未被检测到"
            assert _wait_until(lambda: bool(disconnected)), "on_disconnected 未触发"

            # 修复3：Server 模式不应启动重连线程（_do_connect 恒返回 False）
            assert adapter._reconnecting is False
            assert adapter._reconnect_thread is None
        finally:
            adapter.stop()

    def test_new_client_can_reconnect_after_disconnect(self):
        """断开后 accept 循环应能接受新客户端并恢复在线状态。"""
        adapter = ArmAdapter(host="127.0.0.1", port=0, mode="tcp_server")
        assert adapter.start()
        try:
            port = adapter._server_socket.getsockname()[1]

            first = socket.create_connection(("127.0.0.1", port), timeout=3)
            assert _wait_until(lambda: adapter.is_connected)
            first.close()
            assert _wait_until(lambda: not adapter.is_connected)

            second = socket.create_connection(("127.0.0.1", port), timeout=3)
            try:
                assert _wait_until(lambda: adapter.is_connected), "新客户端无法接入"
            finally:
                second.close()
        finally:
            adapter.stop()


class _DisconnectingAdapter(BaseArmAdapter):
    """_read_available 直接抛 ConnectionError 的假适配器。"""

    def _do_connect(self) -> bool:
        return False

    def _do_disconnect(self) -> None:
        pass

    def _read_available(self) -> bytes | None:
        raise ConnectionError("链路失效")

    def _write_data(self, data: str) -> bool:
        return True


class TestBaseReceiveLoopDisconnect:
    """修复4：基类接收循环对 ConnectionError 走断开流程。"""

    def test_connection_error_breaks_loop_without_on_error(self):
        """ConnectionError 应退出循环并触发 on_disconnected，不触发 on_error。"""
        errors: list[str] = []
        disconnected: list[bool] = []

        adapter = _DisconnectingAdapter()
        adapter._running = True
        adapter._connected = True
        adapter._reconnecting = True  # 阻止断开后真正创建重连线程
        adapter._on_error = errors.append
        adapter._on_disconnected = lambda a: disconnected.append(True)

        adapter._receive_loop()  # 修复前：ConnectionError 不存在，循环永不退出

        assert disconnected == [True], "断开回调未触发"
        assert errors == [], "正常断开不应作为错误上报"


class TestSerialReadAvailable:
    """修复2：串口失效必须抛 ConnectionError。"""

    def test_serial_exception_raises_connection_error(self):
        """SerialException（如 USB 拔出）应抛出 ConnectionError 而非返回 None。"""
        adapter = SerialArmAdapter()
        fake_serial = Mock()
        fake_serial.is_open = True
        type(fake_serial).in_waiting = PropertyMock(
            side_effect=serial.SerialException("device disconnected")
        )
        adapter._serial = fake_serial

        with pytest.raises(ConnectionError):
            adapter._read_available()

    def test_no_data_returns_none(self):
        """无数据时仍返回 None。"""
        adapter = SerialArmAdapter()
        fake_serial = Mock()
        fake_serial.is_open = True
        fake_serial.in_waiting = 0
        adapter._serial = fake_serial

        assert adapter._read_available() is None


class TestConfigTemplates:
    """修复5：示例配置模板可直接复制使用。"""

    STALE_KEYS = {"tc3720_mode", "tc3720_host", "tc3720_port", "enable_debug"}

    def _load(self, filename: str) -> dict:
        path = _project_root / filename
        return json.loads(path.read_text(encoding="utf-8"))

    def test_serial_example_is_usable(self):
        """串口模板：能通过配置校验、含 devices 节、无失效键。"""
        from config import get_gateway_config

        cfg = self._load("config_serial_example.json")
        gateway_config = get_gateway_config(cfg)

        assert gateway_config.arm_mode == "serial"
        assert gateway_config.devices_config, "示例配置缺少 devices 节"
        assert not self.STALE_KEYS & set(cfg["gateway"].keys()), "示例配置含失效键"

    def test_full_template_is_usable(self):
        """全量模板：能通过配置校验、含 devices 节、无失效键。"""
        from config import get_gateway_config

        cfg = self._load("config_full.json")
        gateway_config = get_gateway_config(cfg)

        assert gateway_config.devices_config, "全量模板缺少 devices 节"
        assert not self.STALE_KEYS & set(cfg["gateway"].keys()), "全量模板含失效键"

    def test_redundant_serial_config_removed(self):
        """与 example 逐字节重复的 config_serial.json 已删除。"""
        assert not (_project_root / "config_serial.json").exists()
