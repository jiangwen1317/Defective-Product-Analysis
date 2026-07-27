"""
机械臂适配器基类。

提供 TCP 和串口适配器的公共功能：
- 连接状态管理
- 缓冲区处理
- 协议帧解析
- 线程安全重连控制
"""

import logging
import threading
from abc import ABC, abstractmethod
from typing import Callable

from protocol.arm_protocol import ArmProtocol

logger = logging.getLogger(__name__)


class BaseArmAdapter(ABC):
    """机械臂适配器基类。

    定义适配器必须实现的方法，提供公共功能：
    - 统一的连接状态管理
    - 缓冲区处理
    - 协议帧解析
    - 线程安全重连控制
    """

    def __init__(
        self,
        reconnect_interval: float = 5.0,
        on_connected: Callable[["BaseArmAdapter"], None] | None = None,
        on_disconnected: Callable[["BaseArmAdapter"], None] | None = None,
        on_data_received: Callable[[str], None] | None = None,
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        """初始化基类。

        Args:
            reconnect_interval: 重连间隔秒数。
            on_connected: 连接成功回调。
            on_disconnected: 断开连接回调。
            on_data_received: 收到数据回调。
            on_error: 错误回调。
        """
        self._reconnect_interval = reconnect_interval
        self._on_connected = on_connected
        self._on_disconnected = on_disconnected
        self._on_data_received = on_data_received
        self._on_error = on_error

        # 连接状态
        self._running = False
        self._connected = False

        # 重连线程控制
        self._reconnect_thread: threading.Thread | None = None
        self._stop_reconnect = threading.Event()
        self._reconnecting = False
        self._reconnect_lock = threading.Lock()

        # 读取缓冲区
        self._buffer = ""

        # 锁
        self._lock = threading.Lock()

    @property
    def is_connected(self) -> bool:
        """机械臂是否已连接。"""
        with self._lock:
            return self._connected

    @abstractmethod
    def _is_physical_connected(self) -> bool:
        """检查物理连接是否有效（子类实现）。

        Returns:
            连接是否有效。
        """
        ...

    @abstractmethod
    def _do_connect(self) -> bool:
        """执行实际连接操作（子类实现）。

        Returns:
            连接是否成功。
        """
        ...

    @abstractmethod
    def _do_disconnect(self) -> None:
        """执行实际断开连接操作（子类实现）。"""
        ...

    @abstractmethod
    def _read_available(self) -> bytes | None:
        """读取可用数据（子类实现）。

        Returns:
            读取的字节数据，无数据时返回 None。
        """
        ...

    @abstractmethod
    def _write_data(self, data: str) -> bool:
        """发送数据（子类实现）。

        Args:
            data: 要发送的字符串。

        Returns:
            发送是否成功。
        """
        ...

    def start(self) -> bool:
        """启动适配器。

        Returns:
            启动是否成功。
        """
        if self._running:
            logger.warning("适配器已在运行")
            return True

        self._running = True
        self._stop_reconnect.clear()

        # 执行连接
        if not self._do_connect():
            # 启动重连线程
            self._start_reconnect()
        else:
            # 连接成功，启动接收线程
            self._start_receive_thread()

        return True

    def stop(self) -> None:
        """停止适配器，断开所有连接。"""
        if not self._running:
            return

        logger.info("停止机械臂适配器...")
        self._running = False
        self._stop_reconnect.set()

        # 等待重连线程结束
        if self._reconnect_thread and self._reconnect_thread.is_alive():
            self._reconnect_thread.join(timeout=1.0)
            self._reconnect_thread = None

        # 等待主线程结束
        self._wait_for_receive_thread()

        # 清理资源
        self._do_disconnect()

        logger.info("机械臂适配器已停止")

    def _start_reconnect(self) -> None:
        """启动重连（线程安全）。"""
        with self._reconnect_lock:
            if self._reconnecting:
                logger.debug("重连线程已在运行，跳过")
                return

            if self._reconnect_thread and self._reconnect_thread.is_alive():
                logger.debug("重连线程仍在运行，跳过")
                return

            self._reconnecting = True
            self._stop_reconnect.clear()

            self._reconnect_thread = threading.Thread(
                target=self._reconnect_loop,
                name=f"{self.__class__.__name__}-Reconnect",
                daemon=True,
            )
            self._reconnect_thread.start()

    def _reconnect_loop(self) -> None:
        """重连循环。"""
        try:
            while self._running and not self._stop_reconnect.is_set():
                if self._do_connect():
                    logger.info("重连成功")
                    self._start_receive_thread()
                    return

                # 等待重连间隔
                for _ in range(int(self._reconnect_interval * 10)):
                    if self._stop_reconnect.is_set() or not self._running:
                        return
                    threading.Event().wait(0.1)
        finally:
            with self._reconnect_lock:
                self._reconnecting = False
            logger.info("重连线程退出")

    def _start_receive_thread(self) -> None:
        """启动接收线程（子类可覆盖）。"""
        self._receive_thread = threading.Thread(
            target=self._receive_loop,
            name=f"{self.__class__.__name__}-Receive",
            daemon=True,
        )
        self._receive_thread.start()

    def _receive_loop(self) -> None:
        """接收数据主循环。

        解码后直接交由上层网关解析（网关自带分帧缓冲），
        基类不再累积 self._buffer，避免只写入不消费导致的内存泄漏。
        """
        logger.info("接收线程启动")

        while self._running and self._connected:
            try:
                data = self._read_available()
                if data is None:
                    threading.Event().wait(0.1)
                    continue

                message = data.decode("utf-8", errors="replace")
                logger.debug("收到原始数据: %r", message)

                # 触发数据接收回调（由上层网关处理协议解析）
                if self._on_data_received:
                    self._on_data_received(message)

            except Exception as e:
                logger.error("接收数据异常: %s", e)
                if self._on_error:
                    self._on_error(str(e))
                break

        logger.info("接收线程退出")
        self._on_disconnected_internal()

    def _process_buffer(self) -> None:
        """处理缓冲区中的数据，提取完整帧。

        优化：对于分片到达的数据，只记录 debug 级别日志，
        避免大量 "无法解析" 警告干扰用户。
        """
        frames_to_process: list[tuple[str, dict]] = []

        with self._lock:
            buffer_copy = self._buffer

            while "+" in buffer_copy:
                frame, buffer_copy = buffer_copy.split("+", 1)
                frame += "+"

                result = ArmProtocol.parse_command(frame)
                if result:
                    frames_to_process.append(result)
                else:
                    # 检查是否是可能不完整的帧（以 @ 开头但解析失败）
                    if frame.strip().startswith("@"):
                        # 可能是分片数据，debug 级别记录
                        logger.debug("收到分片数据，等待完整帧: %r", frame[:50])
                    else:
                        # 非协议数据（如配置信息），忽略
                        logger.debug("忽略非协议数据: %r", frame[:50])

            self._buffer = buffer_copy

        # 在锁外执行回调
        for cmd_type, params in frames_to_process:
            if cmd_type == "START_TEST":
                group = params.get("group", "")
                bitmask = params.get("bitmask", "")
                logger.info("收到 START_TEST - Group: %s, Bitmask: %s", group, bitmask)
            else:
                logger.info("收到指令: %s", cmd_type)

    def _on_connected_internal(self) -> None:
        """内部连接成功处理。"""
        with self._lock:
            self._connected = True

        logger.info("机械臂已连接")
        if self._on_connected:
            self._on_connected(self)

    def _on_disconnected_internal(self) -> None:
        """内部断开连接处理。"""
        with self._lock:
            self._connected = False

        logger.info("机械臂已断开连接")
        if self._on_disconnected:
            self._on_disconnected(self)

        # Client 模式自动重连
        if self._running:
            self._start_reconnect()

    def _wait_for_receive_thread(self) -> None:
        """等待接收线程结束。"""
        if hasattr(self, '_receive_thread') and self._receive_thread:
            if self._receive_thread.is_alive():
                self._receive_thread.join(timeout=2.0)

    def send_raw(self, data: str) -> bool:
        """发送原始数据。

        Args:
            data: 要发送的原始字符串。

        Returns:
            发送是否成功。
        """
        with self._lock:
            if not self._connected:
                logger.warning("未连接，无法发送数据")
                return False

            return self._write_data(data)

    def send_test_done(self, group: str, error_codes: list[str]) -> bool:
        """向机械臂发送 TEST_DONE 指令。

        Args:
            group: 组号（2位十六进制）。
            error_codes: 8个错误码列表。

        Returns:
            发送是否成功。
        """
        command = ArmProtocol.build_test_done(group, error_codes)
        return self.send_raw(command)
