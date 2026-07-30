"""
MainWindow 跨线程信号→槽链路的行为级测试。

既有断言（test_p0_concurrency_fixes.py 的 TestUIThreadCommunication、
test_thread_safety.py 的 TestMainWindowUIInitialization）为源码文本匹配，
仅验证写法；本文件通过真实行为验证两条最高风险链路：

1. DUT 状态链：设备线程回调 _on_dut_status_changed
   → _sig_dut_status（跨线程排队）→ _update_dut_display_safe（主线程）
   → DutGridPanel 状态文字刷新。
2. 测试会话链：Gateway-TestWorker 线程回调 _on_test_started /
   _on_dut_result / _on_test_finished → 对应信号 → 进度面板 /
   任务详情标签 / 会话统计刷新。

验证方式：从真实 threading.Thread 触发回调，join 后先断言 UI 未变
（跨线程 emit 只会把槽排队到主线程——若有人把回调改成直接调槽或
直接碰控件，此处立即失败），再由主线程 processEvents 排空事件队列，
断言 UI 已刷新（若有人删掉信号接线或回调不再 emit，此处失败）。
"""

import sys
import threading

import pytest
from adapters import TC3720Status


@pytest.fixture(scope="module")
def qapp():
    """模块级 QApplication（进程内只允许一个实例）。"""
    from PyQt5.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    yield app


@pytest.fixture()
def window(qapp):
    """真实 MainWindow 实例（网关不启动，无真实设备）。"""
    from ui.main_window import MainWindow

    win = MainWindow()
    # 测试不落盘真实历史库（统计仍走内存 _stats）
    win._history_store = None
    # 排空构造期间可能残留的事件，保证后续"UI 未变"断言干净
    qapp.processEvents()
    try:
        yield win
    finally:
        win.close()


def _run_in_worker_thread(target, *args) -> None:
    """在真实工作线程中执行回调并等待其结束（模拟设备/网关线程）。"""
    worker = threading.Thread(target=target, args=args, name="Fake-DeviceThread")
    worker.start()
    worker.join(timeout=2.0)
    assert not worker.is_alive(), "工作线程回调未在 2s 内返回（疑似阻塞）"


class TestDutStatusSignalChain:
    """DUT 状态链：工作线程回调经 _sig_dut_status 排队后刷新状态面板。"""

    def test_status_update_deferred_until_main_thread_event_loop(self, qapp, window):
        """工作线程触发状态回调：processEvents 前控件不变，之后刷新为"测试中"。"""
        labels = window._dut_grid_panel._dut_status_labels
        assert labels, "config.json 未配置任何 DUT，无法验证状态链"
        dut_index = next(iter(labels))
        text_before = labels[dut_index].text()
        assert text_before != "测试中", "初始状态即为测试中，用例前提不成立"

        _run_in_worker_thread(
            window._on_dut_status_changed, dut_index, TC3720Status.TESTING
        )

        # 槽不得在工作线程同步执行：主线程处理事件前控件必须保持原状
        assert labels[dut_index].text() == text_before, (
            "控件在主线程事件循环运行前已被修改——回调绕过了 pyqtSignal 排队"
        )

        qapp.processEvents()

        assert labels[dut_index].text() == "测试中", (
            "processEvents 后 DUT 状态未刷新——信号未接线或回调未 emit"
        )


class TestSessionSignalChain:
    """测试会话链：started/dut_result/finished 三连回调驱动 UI 与统计。"""

    @staticmethod
    def _bitmask_for(dut_indices: list[int]) -> str:
        return "".join("1" if i in dut_indices else "0" for i in range(1, 9))

    def test_started_from_worker_thread_updates_task_labels(self, qapp, window):
        """工作线程触发会话开始：processEvents 后任务详情与加载态刷新。"""
        duts = window._configured_duts[:2]
        assert duts, "config.json 未配置任何 DUT，无法验证会话链"
        bitmask = self._bitmask_for(duts)
        group_before = window._task_group_label.text()

        _run_in_worker_thread(window._on_test_started, "07", bitmask, list(duts))

        assert window._task_group_label.text() == group_before
        assert window._trigger_busy is False, (
            "加载态在主线程事件循环运行前已被修改——回调绕过了 pyqtSignal 排队"
        )

        qapp.processEvents()

        assert window._task_group_label.text() == "07"
        assert window._task_bitmask_label.text() == bitmask
        assert window._trigger_busy is True
        assert window._test_progress_panel._is_testing is True

    def test_finished_from_worker_thread_updates_stats_and_restores_trigger(
        self, qapp, window
    ):
        """完整会话：结果与结束回调经信号入主线程后刷新统计并恢复触发态。"""
        duts = window._configured_duts[:2]
        assert duts, "config.json 未配置任何 DUT，无法验证会话链"
        results = {dut: "0000" for dut in duts}

        # 先经同一链路建立"会话进行中"状态
        _run_in_worker_thread(
            window._on_test_started, "07", self._bitmask_for(duts), list(duts)
        )
        qapp.processEvents()
        stats_before = dict(window._stats)

        def _worker() -> None:
            for dut, code in results.items():
                window._on_dut_result(dut, code)
            window._on_test_finished("07", dict(results), 1.5)

        _run_in_worker_thread(_worker)

        # 主线程处理事件前：统计与会话状态必须保持"进行中"原状
        assert window._stats == stats_before
        assert window._test_progress_panel._is_testing is True

        qapp.processEvents()

        assert window._test_progress_panel._is_testing is False
        assert window._trigger_busy is False, "会话结束后触发按钮未恢复"
        for dut, code in results.items():
            assert window._test_progress_panel._dut_results.get(dut) == code

        assert window._stats["total"] == stats_before["total"] + 1
        assert window._stats["success"] == stats_before["success"] + 1
        assert window._stats["failed"] == stats_before["failed"]

        expected_codes = " ".join(f"#{d}:{results[d]}" for d in sorted(results))
        assert window._task_errorcodes_label.text() == expected_codes
        assert window._task_duration_label.text() == "1.5 s"
