"""
机械臂适配器基类。

提供 TCP 和串口适配器的公共功能：
- 连接状态管理
- 接收循环（数据直接交由上层网关分帧与解析）
- 线程安全重连控制
"""

import logging
import threading
from abc import ABC, abstractmethod
from typing import Callable

from adapters.reconnect_mixin import ReconnectMixin

logger = logging.getLogger(__name__)


class BaseArmAdapter(ReconnectMixin, ABC):
    """机械臂适配器基类。

    定义适配器必须实现的方法，提供公共功能：
    - 统一的连接状态管理
    - 接收循环（数据直接交由上层网关分帧与解析）
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

        # 重连线程控制（字段由 ReconnectMixin 统一初始化）
        self._init_reconnect_state()

        # 读取线程控制
        self._lock = threading.Lock()

    @property
    def is_connected(self) -> bool:
        """机械臂是否已连接。"""
        with self._lock:
            return self._connected

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
            读取的字节数据，超时无数据时返回 None。

        Raises:
            ConnectionError: 连接已断开（对端关闭或链路失效）时。
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
        self._join_reconnect_thread(timeout=1.0)

        # 等待接收线程结束
        self._wait_for_receive_thread()

        # 清理资源
        self._do_disconnect()

        logger.info("机械臂适配器已停止")

    def _on_reconnect_success(self) -> None:
        """重连成功：启动接收线程（ReconnectMixin 钩子）。"""
        logger.info("重连成功")
        self._start_receive_thread()

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
        基类不做任何缓冲累积。
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

            except ConnectionError as e:
                # 对端关闭或链路失效：正常断开事件，走断开流程而非错误上报
                logger.info("连接已断开: %s", e)
                break
            except Exception as e:
                logger.error("接收数据异常: %s", e)
                if self._on_error:
                    self._on_error(str(e))
                break

        logger.info("接收线程退出")
        self._on_disconnected_internal()

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
