"""
P0/P1 缺陷修复回归测试。

覆盖以下修复：
1. _send_error_to_arm 使用协议合法的 group="00"（修复前 "FF" 必然抛 ValueError，
   错误帧永远发不出，机械臂只能干等）
2. 网关测试会话回调链路（on_test_started / on_dut_result / on_test_finished），
   修复测试进度面板与任务详情"死 UI"
3. UI 触发测试的板号映射（修复前按复选框序号发送，配置非连续 DUT 时发错板号）
4. requirements.txt 依赖声明（补 pyserial、移除非法的 python>=3.10 行）
"""

import time
from pathlib import Path
from unittest.mock import Mock

import pytest

# 项目根目录（sys.path 注入已统一由 tests/conftest.py 处理）
_project_root = Path(__file__).resolve().parent.parent

from protocol.arm_protocol import ArmProtocol
from router.gateway import GatewayConfig, PassthroughGateway


def _make_gateway(test_timeout: float = 0.5, **callbacks) -> PassthroughGateway:
    """构造带 Mock 机械臂适配器的网关。"""
    gateway = PassthroughGateway(
        config=GatewayConfig(test_timeout=test_timeout), **callbacks
    )
    gateway._running = True
    arm = Mock()
    arm.send_raw.return_value = True
    gateway._arm_adapter = arm
    return gateway


class _InstantManager:
    """start_test 内同步回调完成结果，模拟极快返回（复用 P0 测试模式）。"""

    def __init__(self, gateway: PassthroughGateway, error_code: str = "0000") -> None:
        self._gateway = gateway
        self._error_code = error_code

    def start_test(self, dut_indices):
        results = {}
        for dut in dut_indices:
            result = Mock()
            result.dut_index = dut
            result.error_code = self._error_code
            self._gateway._on_device_test_result(result)
            results[dut] = True
        return results


class TestSendErrorToArm:
    """修复1：异常中止帧必须是协议合法帧。"""

    def test_error_frame_uses_valid_group(self):
        """错误帧应使用 group="00"（协议恒定值），且能被协议解析器接受。"""
        gateway = _make_gateway()

        gateway._send_error_to_arm("device manager not ready")

        # 修复前：build_test_done("FF", ...) 抛 ValueError，send_raw 不会被调用
        assert gateway._arm_adapter.send_raw.called, "错误帧未发送"
        sent = gateway._arm_adapter.send_raw.call_args[0][0]

        parsed = ArmProtocol.parse_command(sent)
        assert parsed is not None, f"错误帧不是合法协议帧: {sent!r}"
        cmd_type, params = parsed
        assert cmd_type == "TEST_DONE"
        assert params["group"] == "00"
        assert params["error_codes"] == ["EEEE"] * 8

    def test_handle_start_test_without_manager_sends_error_frame(self):
        """设备管理器未就绪时应向机械臂发出异常中止帧（修复前静默失败）。"""
        gateway = _make_gateway()
        gateway._device_manager = None

        gateway._handle_start_test({"group": "00", "bitmask": "10000000"})

        assert gateway._arm_adapter.send_raw.called
        sent = gateway._arm_adapter.send_raw.call_args[0][0]
        assert ArmProtocol.parse_command(sent) is not None


class TestSessionCallbacks:
    """修复2：测试会话回调链路接通 UI 数据。"""

    def test_session_callbacks_fired_in_order(self):
        """完整会话应依次触发 started → dut_result → finished。"""
        events: list[tuple] = []
        gateway = _make_gateway(
            on_test_started=lambda g, b, d: events.append(("started", g, b, d)),
            on_dut_result=lambda i, c: events.append(("dut", i, c)),
            on_test_finished=lambda g, r, t: events.append(("finished", g, r, t)),
        )
        gateway._device_manager = _InstantManager(gateway)

        gateway._handle_start_test({"group": "00", "bitmask": "10100000"})

        assert events[0] == ("started", "00", "10100000", [1, 3])
        assert ("dut", 1, "0000") in events
        assert ("dut", 3, "0000") in events

        kind, group, results, duration = events[-1]
        assert kind == "finished"
        assert group == "00"
        assert results == {1: "0000", 3: "0000"}
        assert duration >= 0

    def test_failed_start_reports_eeee_result(self):
        """启动失败的 DUT 应主动上报 EEEE（不会再有完成回调）。"""
        dut_results: list[tuple[int, str]] = []
        finished: list[dict] = []
        gateway = _make_gateway(
            on_dut_result=lambda i, c: dut_results.append((i, c)),
            on_test_finished=lambda g, r, t: finished.append(r),
        )
        manager = Mock()
        manager.start_test.return_value = {1: False, 3: False}
        gateway._device_manager = manager

        start = time.time()
        gateway._handle_start_test({"group": "00", "bitmask": "10100000"})
        assert time.time() - start < 0.4, "全部启动失败仍等满超时"

        assert (1, "EEEE") in dut_results
        assert (3, "EEEE") in dut_results
        assert finished == [{1: "EEEE", 3: "EEEE"}]

    def test_untracked_device_result_does_not_fire_callback(self):
        """非本次会话的 DUT 结果不应转发到 UI。"""
        dut_results: list[tuple[int, str]] = []
        gateway = _make_gateway(
            on_dut_result=lambda i, c: dut_results.append((i, c)),
        )
        # 会话仅跟踪 DUT#2
        gateway._test_results = {2: None}

        stray = Mock()
        stray.dut_index = 7
        stray.error_code = "0000"
        gateway._on_device_test_result(stray)

        assert dut_results == []


class TestBoardSelectionMapping:
    """修复3：复选框勾选状态按位置映射回真实 DUT 编号。"""

    def test_non_contiguous_duts_map_to_real_indices(self):
        from ui.main_window import MainWindow

        # 修复前：配置 [3, 5] 全勾选会发送 [1, 2]
        assert MainWindow._map_selected_boards([3, 5], [True, True]) == [3, 5]

    def test_partial_selection(self):
        from ui.main_window import MainWindow

        assert MainWindow._map_selected_boards([1, 2, 4], [True, False, True]) == [1, 4]

    def test_empty_selection(self):
        from ui.main_window import MainWindow

        assert MainWindow._map_selected_boards([1, 2], [False, False]) == []


class TestRequirements:
    """修复4：依赖声明可被 pip 正确安装。"""

    def test_pyserial_declared_and_no_invalid_line(self):
        requirements = (_project_root / "requirements.txt").read_text(encoding="utf-8")
        packages = [
            line.strip()
            for line in requirements.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]

        assert any(pkg.startswith("pyserial") for pkg in packages), "缺少 pyserial 依赖"
        # "python>=3.10" 不是合法 pip 依赖，会导致 pip install -r 失败
        assert not any(pkg.startswith("python") and not pkg.startswith("pyserial")
                       for pkg in packages if not pkg.startswith("PyQt")), \
            "存在非法的 python 版本声明行"
