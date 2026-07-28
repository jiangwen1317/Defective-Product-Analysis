"""
P0 并发缺陷修复回归测试。

覆盖以下修复：
1. TC3720TcpAdapter._timeout_monitor 死锁（锁内嵌套调用 _set_status）
2. PassthroughGateway._test_complete_event 竞态（先 start 后 clear / 全失败无唤醒）
3. START_TEST 处理移出接收线程（投递到工作队列，接收回调不阻塞）
4. BaseArmAdapter._receive_loop 缓冲区无消费累积（内存泄漏）
5. DeviceManager.stop 持锁调用 disconnect（回调重入锁风险）
6. DeviceManager 接线 TC3720 适配器的 on_error（超时结果可达网关）
7. UI 跨线程通信使用 pyqtSignal 而非 QTimer.singleShot
"""

import threading
import time
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

# 项目根目录（sys.path 注入已统一由 tests/conftest.py 处理）
_project_root = Path(__file__).resolve().parent.parent

from adapters import TC3720Status
from adapters.base_arm_adapter import BaseArmAdapter
from adapters.tc3720_tcp_adapter import TC3720TcpAdapter
from router.device_manager import DeviceManager
from router.gateway import GatewayConfig, PassthroughGateway


class TestTimeoutMonitorDeadlock:
    """修复1：_timeout_monitor 不再死锁。"""

    def test_timeout_monitor_completes_without_deadlock(self):
        """超时触发后监控线程应正常退出，状态回到 IDLE 并触发 on_error。"""
        errors: list[str] = []
        adapter = TC3720TcpAdapter(
            host="192.168.1.99",
            port=9999,
            on_error=errors.append,
        )
        adapter._running = True
        adapter._pending_test = True
        adapter._status = TC3720Status.TESTING

        t = threading.Thread(target=adapter._timeout_monitor, args=(0.05,))
        t.start()
        t.join(timeout=2.0)

        # 修复前：_set_status 在锁内被调用，此处线程永久卡死
        assert not t.is_alive(), "超时监控线程死锁未退出"
        assert adapter.status == TC3720Status.IDLE
        assert adapter._pending_test is False
        assert errors == ["测试超时"]


class TestGatewayEventRace:
    """修复2：完成事件的竞态与全失败唤醒。"""

    def _make_gateway(self, test_timeout: float = 0.5) -> PassthroughGateway:
        gateway = PassthroughGateway(config=GatewayConfig(test_timeout=test_timeout))
        gateway._running = True
        arm = Mock()
        arm.send_raw.return_value = True
        gateway._arm_adapter = arm
        return gateway

    def test_early_results_are_not_wiped_by_clear(self):
        """结果先于 wait 到达时不应等满超时（修复前 clear 会擦掉已置位的事件）。"""
        gateway = self._make_gateway(test_timeout=0.5)

        class InstantManager:
            """start_test 内同步回调完成结果，模拟极快返回。"""

            def start_test(self, dut_indices):
                results = {}
                for dut in dut_indices:
                    result = Mock()
                    result.dut_index = dut
                    result.error_code = "0000"
                    gateway._on_device_test_result(result)
                    results[dut] = True
                return results

        gateway._device_manager = InstantManager()

        start = time.time()
        gateway._handle_start_test({"group": "00", "bitmask": "10000000"})
        elapsed = time.time() - start

        # 修复前会等满 2×test_timeout = 1.0s
        assert elapsed < 0.4, f"结果已齐全仍等待了 {elapsed:.2f}s"
        sent = gateway._arm_adapter.send_raw.call_args[0][0]
        assert sent.startswith("@TEST_DONE 00 0000")

    def test_all_start_failures_return_immediately(self):
        """全部 DUT 启动失败时应立即返回（修复前无任何回调置位事件，等满超时）。"""
        gateway = self._make_gateway(test_timeout=0.5)

        manager = Mock()
        manager.start_test.return_value = {1: False, 3: False}
        gateway._device_manager = manager

        start = time.time()
        gateway._handle_start_test({"group": "00", "bitmask": "10100000"})
        elapsed = time.time() - start

        assert elapsed < 0.4, f"全部启动失败仍等待了 {elapsed:.2f}s"
        sent = gateway._arm_adapter.send_raw.call_args[0][0]
        # DUT#1 与 DUT#3 应为 EEEE
        parts = sent.rstrip("+").split(" ")
        assert parts[2] == "EEEE"  # DUT#1
        assert parts[4] == "EEEE"  # DUT#3


class TestReceiveThreadNotBlocked:
    """修复3：START_TEST 投递到工作队列，接收回调立即返回。"""

    def test_start_test_frame_is_dispatched_to_queue(self):
        gateway = PassthroughGateway(config=GatewayConfig(test_timeout=5.0))
        gateway._running = True

        start = time.time()
        gateway._on_arm_data_received("@START_TEST 00 10000000+")
        elapsed = time.time() - start

        # 修复前此调用会同步执行 _handle_start_test 并阻塞最长 2×timeout
        assert elapsed < 0.2, f"接收回调被阻塞 {elapsed:.2f}s"
        assert gateway._test_queue.qsize() == 1
        assert gateway._test_queue.get_nowait() == {"group": "00", "bitmask": "10000000"}

    def test_arm_buffer_capped_on_garbage_data(self):
        """含 '@' 但无 '+' 的异常数据不应使缓冲区无限增长。"""
        gateway = PassthroughGateway()

        gateway._on_arm_data_received("@" + "x" * (gateway.MAX_ARM_BUFFER + 100))

        assert len(gateway._arm_buffer) <= gateway.MAX_ARM_BUFFER


class _FakeArmAdapter(BaseArmAdapter):
    """用于测试基类接收循环的假适配器。"""

    def __init__(self, chunks: list[bytes]) -> None:
        super().__init__()
        self._chunks = list(chunks)
        self._connected = True
        self._running = True

    def _do_connect(self) -> bool:
        return True

    def _do_disconnect(self) -> None:
        pass

    def _read_available(self) -> bytes | None:
        if self._chunks:
            return self._chunks.pop(0)
        self._running = False  # 数据耗尽后结束循环
        return None

    def _write_data(self, data: str) -> bool:
        return True


class TestBaseAdapterBufferLeak:
    """修复4：基类接收循环不做任何缓冲累积。"""

    def test_receive_loop_does_not_grow_buffer(self):
        chunks = [b"@START_TEST 00 10000000+"] * 10
        adapter = _FakeArmAdapter(chunks)
        received: list[str] = []
        adapter._on_data_received = received.append

        adapter._receive_loop()

        # 数据全部通过回调交给上层，基类不再持有任何缓冲区属性
        assert len(received) == 10
        assert not hasattr(adapter, "_buffer")


class TestDeviceManagerLocking:
    """修复5/6：stop 锁外断开 + on_error 接线。"""

    def test_stop_does_not_hold_lock_during_disconnect(self):
        """disconnect 过程中回调查询管理器（需获取管理器锁）不应死锁。"""
        manager = DeviceManager(devices_config={})
        manager._running = True

        fake_adapter = Mock()
        fake_adapter.is_testing = False
        # 模拟 disconnect 触发状态回调，回调中反查管理器状态（需要管理器锁）
        fake_adapter.disconnect.side_effect = lambda: manager.is_all_idle()
        manager._adapters[1] = fake_adapter

        t = threading.Thread(target=manager.stop)
        t.start()
        t.join(timeout=2.0)

        # 修复前：stop 持锁调用 disconnect，回调再获取锁 → 死锁
        assert not t.is_alive(), "stop() 持锁调用 disconnect 导致死锁"
        assert fake_adapter.disconnect.called

    def test_init_device_wires_on_error(self):
        """适配器必须接线 on_error，超时错误才能以 EEEE 结果上报。"""
        results = []
        with patch("router.device_manager.TC3720TcpAdapter") as mock_cls:
            manager = DeviceManager(
                devices_config={"dut1": {"ip": "1.2.3.4", "port": 9090, "name": "B1"}},
                on_test_result=results.append,
            )
            manager.start()

        kwargs = mock_cls.call_args.kwargs
        assert kwargs.get("on_error") is not None, "on_error 未接线"

        # 触发 on_error 应产生 dut1 的 EEEE 结果
        kwargs["on_error"]("测试超时")
        assert len(results) == 1
        assert results[0].dut_index == 1
        assert results[0].error_code == "EEEE"
        assert results[0].success is False


class TestUIThreadCommunication:
    """修复7：UI 跨线程通信使用 pyqtSignal。"""

    def test_main_window_uses_signals_not_qtimer(self):
        source_file = _project_root / "ui" / "main_window.py"
        content = source_file.read_text(encoding="utf-8")

        assert "pyqtSignal" in content, "未定义跨线程信号"
        assert "QTimer.singleShot" not in content, "仍存在跨线程 QTimer.singleShot 调用"
