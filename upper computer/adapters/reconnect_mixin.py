"""
TCP 重连支持组件。

将 BaseArmAdapter 与 TC3720TcpAdapter 中逐字重复的重连机制收敛到一处：
- 重连线程的防重复启动（_reconnect_lock + _reconnecting 标志）
- 重连循环（分片等待，及时响应停止请求）
- TCP 建连与 socket 安全清理

宿主类约定（Mixin 依赖以下成员，缺失会在运行时报 AttributeError）：
- self._running: bool                 运行标志
- self._reconnect_interval: float     重连间隔（秒）
- CONNECT_TIMEOUT / SOCKET_TIMEOUT    类常量（_open_tcp_socket 使用）
并实现钩子方法：
- _do_connect() -> bool               执行实际连接
- _on_reconnect_success() -> None     重连成功后的动作（启动接收线程、更新状态等）
"""

import logging
import socket
import threading

logger = logging.getLogger(__name__)


def close_socket(sock: socket.socket | None) -> None:
    """安全关闭 socket（shutdown + close，忽略已断开等异常）。

    Args:
        sock: 要关闭的 socket，为 None 时直接返回。
    """
    if sock is None:
        return
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except Exception:
        pass
    try:
        sock.close()
    except Exception:
        pass


class ReconnectMixin:
    """线程安全的自动重连支持。

    通过 _start_reconnect() 启动后台重连线程；重复调用只会创建一个线程。
    stop 流程调用 _stop_reconnect.set() + _join_reconnect_thread() 终止重连。
    """

    def _init_reconnect_state(self) -> None:
        """初始化重连控制字段（宿主类 __init__ 中调用）。"""
        self._reconnect_thread: threading.Thread | None = None
        self._stop_reconnect = threading.Event()
        self._reconnecting = False
        self._reconnect_lock = threading.Lock()

    def _do_connect(self) -> bool:
        """执行实际连接操作（宿主类实现）。"""
        raise NotImplementedError

    def _on_reconnect_success(self) -> None:
        """重连成功后的动作（宿主类实现：启动接收线程、更新状态等）。"""
        raise NotImplementedError

    def _reconnect_thread_name(self) -> str:
        """重连线程名称（宿主类可覆盖）。"""
        return f"{self.__class__.__name__}-Reconnect"

    def _start_reconnect(self) -> None:
        """启动重连（线程安全，确保只有一个重连线程）。"""
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
                name=self._reconnect_thread_name(),
                daemon=True,
            )
            self._reconnect_thread.start()

    def _reconnect_loop(self) -> None:
        """重连循环。"""
        try:
            while self._running and not self._stop_reconnect.is_set():
                if self._do_connect():
                    self._on_reconnect_success()
                    return

                # 分片等待重连间隔，便于及时响应停止请求
                for _ in range(int(self._reconnect_interval * 10)):
                    if self._stop_reconnect.is_set() or not self._running:
                        return
                    self._stop_reconnect.wait(0.1)
        finally:
            with self._reconnect_lock:
                self._reconnecting = False
            logger.info("重连线程退出 [%s]", self._reconnect_thread_name())

    def _join_reconnect_thread(self, timeout: float = 1.0) -> None:
        """等待重连线程结束并清空引用。

        Args:
            timeout: 等待超时时间（秒）。
        """
        if self._reconnect_thread and self._reconnect_thread.is_alive():
            self._reconnect_thread.join(timeout=timeout)
        self._reconnect_thread = None

    def _open_tcp_socket(
        self,
        host: str,
        port: int,
        keepalive: bool = False,
    ) -> socket.socket | None:
        """建立 TCP 连接。

        Args:
            host: 目标地址。
            port: 目标端口。
            keepalive: 是否开启 TCP KEEPALIVE。

        Returns:
            已连接的 socket（已设置 SOCKET_TIMEOUT），失败时返回 None。
        """
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.CONNECT_TIMEOUT)
            sock.connect((host, port))
            sock.settimeout(self.SOCKET_TIMEOUT)
            if keepalive:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            return sock

        except (OSError, socket.timeout) as e:
            logger.warning("TCP 连接失败: %s:%d - %s", host, port, e)
            return None
