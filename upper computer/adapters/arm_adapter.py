"""
机械臂设备适配器 - TCP 模式。

支持两种模式：
- TCP Server 模式（被动接收）：监听端口，等待机械臂主动连接
- TCP Client 模式（主动连接）：主动连接下位机 IP

协议格式：@<CMD> <参数>+ (如 @START_TEST 00 11111111+)

使用 threading + socket 实现，与 PyQt5 原生集成。
"""

import logging
import select
import socket
import threading
from enum import Enum
from typing import Callable

from adapters.base_arm_adapter import BaseArmAdapter

logger = logging.getLogger(__name__)


class ArmAdapterMode(Enum):
    """适配器工作模式。"""

    SERVER = "tcp_server"  # TCP Server：被动监听，等待连接
    CLIENT = "tcp_client"  # TCP Client：主动连接下位机


class ArmAdapter(BaseArmAdapter):
    """机械臂设备 TCP 适配器。

    支持 TCP Server 和 TCP Client 两种模式：
    - Server 模式：被动监听，等待机械臂主动连接
    - Client 模式：主动连接机械臂的 TCP 地址

    使用独立线程处理 TCP 连接，事件驱动回调通知上层应用。
    """

    # 默认监听配置
    DEFAULT_HOST: str = "0.0.0.0"
    DEFAULT_PORT: int = 8080
    BUFFER_SIZE: int = 1024
    SOCKET_TIMEOUT: float = 1.0  # socket 超时时间（秒）
    CONNECT_TIMEOUT: float = 5.0  # 连接超时时间（秒）

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        mode: str = "tcp_server",
        target_host: str = "",
        target_port: int = 0,
        reconnect_interval: float = 5.0,
        on_connected: Callable[["ArmAdapter"], None] | None = None,
        on_disconnected: Callable[["ArmAdapter"], None] | None = None,
        on_data_received: Callable[[str], None] | None = None,
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        """初始化机械臂适配器。

        Args:
            host: 监听地址（Server 模式使用）。
            port: 监听端口（Server 模式）或连接端口（Client 模式）。
            mode: 工作模式，"tcp_server"（默认）或 "tcp_client"。
            target_host: 目标主机地址（Client 模式使用）。
            target_port: 目标端口（Client 模式使用）。
            reconnect_interval: 重连间隔秒数（Client 模式，默认为 5.0）。
            on_connected: 机械臂连接成功回调。
            on_disconnected: 机械臂断开连接回调。
            on_data_received: 收到任意数据回调（由上层协议解析）。
            on_error: 错误发生回调。
        """
        super().__init__(
            reconnect_interval=reconnect_interval,
            on_connected=on_connected,
            on_disconnected=on_disconnected,
            on_data_received=on_data_received,
            on_error=on_error,
        )

        self._host = host
        self._port = port
        self._mode = ArmAdapterMode(mode) if isinstance(mode, str) else mode
        self._target_host = target_host
        self._target_port = target_port

        # 网络资源（基类不使用）
        self._server_socket: socket.socket | None = None
        self._client_socket: socket.socket | None = None
        self._receive_thread: threading.Thread | None = None

    @property
    def mode(self) -> ArmAdapterMode:
        """工作模式。"""
        return self._mode

    @property
    def host(self) -> str:
        """监听地址（Server 模式）或目标地址（Client 模式）。"""
        if self._mode == ArmAdapterMode.CLIENT:
            return self._target_host
        return self._host

    @property
    def port(self) -> int:
        """监听端口或连接端口。"""
        if self._mode == ArmAdapterMode.CLIENT:
            return self._target_port
        return self._port

    @property
    def target_address(self) -> str | None:
        """获取目标连接地址（Client 模式）。"""
        if self._mode == ArmAdapterMode.CLIENT:
            return f"{self._target_host}:{self._target_port}"
        return None

    @property
    def client_address(self) -> str | None:
        """获取已连接客户端的地址。"""
        with self._lock:
            if self._client_socket:
                try:
                    if self._mode == ArmAdapterMode.CLIENT:
                        return f"{self._target_host}:{self._target_port}"
                    return str(self._client_socket.getpeername())
                except Exception:
                    pass
        return None

    def start(self) -> bool:
        """启动适配器。

        Server 模式：启动 TCP Server 监听连接
        Client 模式：启动 TCP Client 连接目标地址

        Returns:
            启动是否成功。
        """
        if self._running:
            logger.warning("适配器已在运行")
            return True

        self._running = True
        self._stop_reconnect.clear()

        if self._mode == ArmAdapterMode.SERVER:
            return self._start_server_mode()
        else:
            return self._start_client_mode()

    def _start_server_mode(self) -> bool:
        """启动 TCP Server 模式。"""
        try:
            # 创建服务器 socket
            self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._server_socket.bind((self._host, self._port))
            self._server_socket.listen(1)
            self._server_socket.settimeout(self.SOCKET_TIMEOUT)

            self._receive_thread = threading.Thread(
                target=self._run_server_loop,
                name=f"ArmAdapter-Server-{self._port}",
                daemon=True,
            )
            self._receive_thread.start()

            logger.info("机械臂适配器已启动 [Server模式]，监听 %s:%d", self._host, self._port)
            return True

        except OSError as e:
            logger.error("启动机械臂适配器失败: %s", e)
            self._running = False
            if self._on_error:
                self._on_error(f"启动监听失败: {e}")
            return False

    def _start_client_mode(self) -> bool:
        """启动 TCP Client 模式。"""
        # 先尝试连接
        if not self._do_connect():
            # 启动重连线程
            self._start_reconnect()
        else:
            # 连接成功，启动接收线程
            self._start_receive_thread()

        logger.info("机械臂适配器已启动 [Client模式]，目标: %s:%d", self._target_host, self._target_port)
        return True

    def _do_connect(self) -> bool:
        """执行实际连接操作。"""
        if self._mode == ArmAdapterMode.SERVER:
            # Server 模式不主动连接
            return False

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.CONNECT_TIMEOUT)
            sock.connect((self._target_host, self._target_port))
            sock.settimeout(self.SOCKET_TIMEOUT)

            with self._lock:
                self._client_socket = sock
                self._connected = True
                self._buffer = ""

            logger.info("已连接到目标: %s:%d", self._target_host, self._target_port)
            self._on_connected_internal()
            return True

        except (OSError, socket.timeout) as e:
            logger.warning("连接目标失败: %s:%d - %s", self._target_host, self._target_port, e)
            return False

    def _do_disconnect(self) -> None:
        """执行实际断开连接操作。"""
        with self._lock:
            # 关闭客户端连接
            if self._client_socket:
                try:
                    self._client_socket.shutdown(socket.SHUT_RDWR)
                except Exception:
                    pass
                try:
                    self._client_socket.close()
                except Exception:
                    pass
                self._client_socket = None
                self._connected = False

            # 关闭服务器
            if self._server_socket:
                try:
                    self._server_socket.close()
                except Exception:
                    pass
                self._server_socket = None

    def _is_physical_connected(self) -> bool:
        """检查物理连接是否有效。"""
        return self._connected and self._client_socket is not None

    def _read_available(self) -> bytes | None:
        """读取可用数据。"""
        if not self._client_socket:
            return None

        try:
            readable, _, _ = select.select([self._client_socket], [], [], self.SOCKET_TIMEOUT)
            if not readable:
                return None

            data = self._client_socket.recv(self.BUFFER_SIZE)
            if not data:
                return None
            return data

        except socket.timeout:
            return None
        except Exception:
            return None

    def _write_data(self, data: str) -> bool:
        """发送数据。"""
        try:
            self._client_socket.sendall(data.encode("utf-8"))
            logger.debug("已发送数据: %r", data)
            return True
        except Exception as e:
            logger.error("发送数据失败: %s", e)
            return False

    def _run_server_loop(self) -> None:
        """TCP Server 主循环（在独立线程中运行）。"""
        logger.info("TCP Server 线程启动")

        while self._running:
            try:
                # 等待客户端连接
                client_socket, addr = self._server_socket.accept()
                logger.info("机械臂连接: %s", addr)

                # 处理客户端
                self._handle_client(client_socket)

            except socket.timeout:
                # 正常超时，继续循环检查 _running 标志
                continue
            except Exception as e:
                if self._running:
                    logger.error("Server accept 异常: %s", e)
                    if self._on_error:
                        self._on_error(f"Server error: {e}")

        logger.info("TCP Server 线程退出")

    def _handle_client(self, client_socket: socket.socket) -> None:
        """处理机械臂客户端连接（Server 模式）。

        Args:
            client_socket: 客户端 socket。
        """
        # 关闭旧连接
        with self._lock:
            if self._client_socket:
                try:
                    self._client_socket.shutdown(socket.SHUT_RDWR)
                except Exception:
                    pass
                try:
                    self._client_socket.close()
                except Exception:
                    pass

            self._client_socket = client_socket
            self._connected = True
            self._buffer = ""

        # 设置 socket 超时
        client_socket.settimeout(self.SOCKET_TIMEOUT)

        # 触发连接回调
        self._on_connected_internal()

        try:
            while self._running and self._connected:
                data = self._read_available()
                if data is None:
                    continue

                # 解码并追加到缓冲区
                message = data.decode("utf-8")
                with self._lock:
                    self._buffer += message

                logger.debug("收到原始数据: %r", message)

                # 触发数据接收回调
                if self._on_data_received:
                    self._on_data_received(message)

                # 处理完整帧
                self._process_buffer()

        except Exception as e:
            logger.error("连接处理异常: %s", e)
            if self._on_error:
                self._on_error(str(e))

        finally:
            self._on_disconnected_internal()
