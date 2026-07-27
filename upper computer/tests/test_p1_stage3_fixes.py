"""阶段三 P1 缺陷修复回归测试。

覆盖以下修复：
1. TCP Server 模式解码容错（修复前 data.decode("utf-8") 严格解码，
   设备上电噪声等非 UTF-8 字节触发 UnicodeDecodeError，整条机械臂连接被断开）
2. 配置异常启动保护（修复前 config.json 缺失关键字段时 MainWindow 构造
   抛未捕获 ValueError，程序黑框闪退，用户看不到任何提示）
3. 通讯日志文档行数上限（修复前 QTextEdit 文档无上限，
   长期运行时富文本文档无限膨胀导致内存增长与界面卡顿）
"""

import socket
import sys
import time
from pathlib import Path

import pytest

# 将项目根目录添加到模块搜索路径
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


@pytest.fixture(scope="module")
def qapp():
    """模块级 QApplication（进程内只允许一个实例）。"""
    from PyQt5.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    yield app


def _wait_until(predicate, timeout: float = 3.0) -> bool:
    """轮询等待条件成立，避免固定 sleep 导致的用例不稳定。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


class TestServerModeDecodeTolerance:
    """修复1：Server 模式非 UTF-8 字节不应断开连接。"""

    def test_invalid_utf8_does_not_disconnect(self):
        """噪声字节 + 合法帧：连接保持在线，帧数据正常送达上层。"""
        from adapters.arm_adapter import ArmAdapter

        received: list[str] = []
        disconnected: list[bool] = []
        adapter = ArmAdapter(
            host="127.0.0.1",
            port=0,  # 由内核分配临时端口
            mode="tcp_server",
            on_disconnected=lambda a: disconnected.append(True),
            on_data_received=received.append,
        )
        assert adapter.start()
        port = adapter._server_socket.getsockname()[1]

        client = socket.create_connection(("127.0.0.1", port), timeout=3)
        try:
            assert _wait_until(lambda: adapter.is_connected), "客户端未接入"

            # 模拟设备上电噪声（0xFF/0xFE 非法 UTF-8）后紧跟合法协议帧
            client.sendall(b"\xff\xfe@START_TEST 00 11111111+")

            assert _wait_until(
                lambda: any("@START_TEST 00 11111111+" in d for d in received)
            ), f"合法帧未送达上层: {received!r}"

            # 修复前：UnicodeDecodeError 触发异常分支，连接被断开
            assert not disconnected, "非 UTF-8 字节导致连接被断开"
            assert adapter.is_connected
        finally:
            client.close()
            adapter.stop()


class TestStartupConfigErrorGuard:
    """修复2：配置异常必须弹窗提示并以非零码退出。"""

    def test_main_shows_dialog_and_exits_on_config_error(self, qapp, monkeypatch):
        """MainWindow 构造抛异常时：调用 _show_startup_error 并 sys.exit(1)。"""
        import ui.main_window as mw

        def _raise(*args, **kwargs):
            raise ValueError("配置缺失: gateway.arm_mode 未设置")

        shown: list[str] = []
        monkeypatch.setattr(mw, "MainWindow", _raise)
        monkeypatch.setattr(mw, "_show_startup_error", shown.append)

        with pytest.raises(SystemExit) as exc_info:
            mw.main()

        assert exc_info.value.code == 1
        assert shown, "未向用户展示启动失败提示"
        assert "gateway.arm_mode" in shown[0]

    def test_empty_config_raises_value_error(self):
        """前置条件确认：空配置确实抛 ValueError（load_config 损坏时返回 {}）。"""
        from config import get_gateway_config

        with pytest.raises(ValueError):
            get_gateway_config({})


class TestLogViewBlockLimit:
    """修复3：通讯日志文档行数与 _log_buffer 同上限。"""

    def test_log_text_has_maximum_block_count(self, qapp):
        window = None
        try:
            from ui.main_window import MainWindow

            window = MainWindow()
            limit = window._log_text.document().maximumBlockCount()

            # 修复前：maximumBlockCount() == 0（无限制）
            assert limit > 0, "日志文档未设置行数上限"
            assert limit == window._log_buffer.maxlen
        finally:
            if window is not None:
                window.close()
