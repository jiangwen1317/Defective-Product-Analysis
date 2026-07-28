"""
线程安全测试 - 验证 P0 修复是否正确。
"""

import threading
from pathlib import Path


def _assert_single_reconnect_thread(adapter) -> None:
    """并发调用 _start_reconnect，验证只创建一个重连线程。

    用可控的假重连循环替换真实实现：既能统计线程创建次数，
    又能保证线程在全部并发调用期间存活（不产生真实网络连接）。
    """
    started_threads: list[str] = []
    release = threading.Event()

    def fake_reconnect_loop() -> None:
        started_threads.append(threading.current_thread().name)
        release.wait(2.0)
        with adapter._reconnect_lock:
            adapter._reconnecting = False

    adapter._reconnect_loop = fake_reconnect_loop

    callers = [threading.Thread(target=adapter._start_reconnect) for _ in range(5)]
    for t in callers:
        t.start()
    for t in callers:
        t.join(timeout=2.0)

    release.set()
    if adapter._reconnect_thread:
        adapter._reconnect_thread.join(timeout=2.0)

    # 修复前此处以 assert True 收尾，未验证任何行为
    assert len(started_threads) == 1, f"创建了 {len(started_threads)} 个重连线程"


class TestTC3720AdapterThreadSafety:
    """TC3720 适配器线程安全测试。"""

    def test_start_reconnect_no_duplicate_threads(self):
        """测试 _start_reconnect 不会创建多个重连线程。"""
        from adapters.tc3720_tcp_adapter import TC3720TcpAdapter

        adapter = TC3720TcpAdapter(host="192.168.1.99", port=9999)
        adapter._running = True
        adapter._stop_reconnect.clear()

        _assert_single_reconnect_thread(adapter)

    def test_reconnect_lock_is_thread_safe(self):
        """测试重连锁是线程安全的。"""
        from adapters.tc3720_tcp_adapter import TC3720TcpAdapter

        adapter = TC3720TcpAdapter(host="192.168.1.99", port=9999)

        # 验证锁存在
        assert hasattr(adapter, '_reconnect_lock')
        assert isinstance(adapter._reconnect_lock, type(adapter._lock))


class TestArmAdapterThreadSafety:
    """Arm 适配器线程安全测试。"""

    def test_start_reconnect_no_duplicate_threads(self):
        """测试 _start_reconnect 不会创建多个重连线程。"""
        from adapters.arm_adapter import ArmAdapter

        adapter = ArmAdapter(
            host="0.0.0.0",
            port=8080,
            mode="tcp_client",
            target_host="192.168.1.99",
            target_port=9999,
        )
        adapter._running = True
        adapter._stop_reconnect.clear()

        _assert_single_reconnect_thread(adapter)

    def test_reconnect_lock_is_thread_safe(self):
        """测试重连锁是线程安全的。"""
        from adapters.arm_adapter import ArmAdapter

        adapter = ArmAdapter(host="0.0.0.0", port=8080)

        # 验证锁存在
        assert hasattr(adapter, '_reconnect_lock')
        assert isinstance(adapter._reconnect_lock, type(adapter._lock))


class TestMainWindowUIInitialization:
    """主窗口 UI 初始化测试。"""

    def test_all_controls_initialized_in_init(self):
        """测试所有控件在 __init__ 中正确初始化。"""
        from ui.main_window import MainWindow

        # 检查类定义中是否包含所有控件初始化
        source_file = Path(__file__).resolve().parent.parent / "ui" / "main_window.py"
        with open(source_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # 检查关键的控件初始化代码
        assert "_arm_connection: ConnectionStatus | None = None" in content
        assert "_alarm_card: Card | None = None" in content
        assert "_task_group_label: QLabel | None = None" in content

    def test_no_hasattr_checks_in_safe_methods(self):
        """测试安全方法中不使用 hasattr 检查。"""
        from ui.main_window import MainWindow

        source_file = Path(__file__).resolve().parent.parent / "ui" / "main_window.py"
        with open(source_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # 查找所有使用 hasattr 检查直接控件属性的地方
        # 子部件（如 _alarm_label）通过父控件间接初始化，可以使用 hasattr
        lines_with_hasattr = []
        for i, line in enumerate(content.split('\n'), 1):
            if 'hasattr' in line and ('_arm_connection' in line
                                       or '_task_group_label' in line):
                lines_with_hasattr.append((i, line.strip()))

        # 不应该有使用 hasattr 检查这些主控件的情况
        assert len(lines_with_hasattr) == 0, f"Found hasattr checks: {lines_with_hasattr}"
