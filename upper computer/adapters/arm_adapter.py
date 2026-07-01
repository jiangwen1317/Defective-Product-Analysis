"""
机械臂设备适配器。

被动接收机械臂通过 TCP 发送的指令。
协议格式：@<CMD> <参数>+ (如 @START_TEST 00 11111111+)

使用 threading + socket 实现，与 PyQt5 原生集成。
"""

import logging
import select
import socket
import threading
import time
from typing import Callable

from protocol.arm_protocol import ArmProtocol

logger = logging.getLogger(__name__)


class ArmAdapter:
    """机械臂设备适配器（TCP Server 模式）。

    被动接收机械臂的连接和指令请求。
    使用独立线程处理 TCP 连接，事件驱动回调通知上层应用。
    """

    # 默认监听配置
    DEFAULT_HOST: str = "0.0.0.0"
    DEFAULT_PORT: int = 8080
    BUFFER_SIZE: int = 1024
    SOCKET_TIMEOUT: float = 1.0  # socket 超时时间（秒）

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        on_connected: Callable[["ArmAdapter"], None] | None = None,
        on_disconnected: Callable[["ArmAdapter"], None] | None = None,
        on_start_test: Callable[[str, str], None] | None = None,  # group, bitmask
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        """初始化机械臂适配器。

        Args:
            host: 监听地址，默认为 0.0.0.0（接受所有接口连接）。
            port: 监听端口。
            on_connected: 机械臂连接成功回调。
            on_disconnected: 机械臂断开连接回调。
            on_start_test: 收到 START_TEST 指令回调。
            on_error: 错误发生回调。
        """
        self._host = host
        self._port = port
        self._on_connected = on_connected
        self._on_disconnected = on_disconnected
        self._on_start_test = on_start_test
        self._on_error = on_error

        # 网络资源
        self._server_socket: socket.socket | None = None
        self._client_socket: socket.socket | None = None

        # 线程资源
        self._thread: threading.Thread | None = None
        self._running = False
        self._connected = False

        # 读取缓冲区
        self._buffer = ""

        # 锁
        self._lock = threading.Lock()

    @property
    def host(self) -> str:
        """监听地址。"""
        return self._host

    @property
    def port(self) -> int:
        """监听端口。"""
        return self._port

    @property
    def is_connected(self) -> bool:
        """机械臂是否已连接。"""
        with self._lock:
            return self._connected and self._client_socket is not None

    @property
    def client_address(self) -> str | None:
        """获取已连接客户端的地址。"""
        with self._lock:
            if self._client_socket:
                try:
                    return str(self._client_socket.getpeername())
                except Exception:
                    pass
        return None

    def start(self) -> bool:
        """启动 TCP Server，监听机械臂连接。

        Returns:
            启动是否成功。
        """
        if self._running:
            logger.warning("适配器已在运行")
            return True

        try:
            # 创建服务器 socket
            self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._server_socket.bind((self._host, self._port))
            self._server_socket.listen(1)
            self._server_socket.settimeout(self.SOCKET_TIMEOUT)

            self._running = True
            self._thread = threading.Thread(
                target=self._run_loop,
                name=f"ArmAdapter-{self._port}",
                daemon=True,
            )
            self._thread.start()

            logger.info("机械臂适配器已启动，监听 %s:%d", self._host, self._port)
            return True

        except OSError as e:
            logger.error("启动机械臂适配器失败: %s", e)
            if self._on_error:
                self._on_error(f"启动监听失败: {e}")
            return False

    def stop(self) -> None:
        """停止 TCP Server，断开所有连接。"""
        self._running = False

        # 等待线程结束
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
            self._thread = None

        # 清理资源
        self._cleanup()

        logger.info("机械臂适配器已停止")

    def send_test_done(self, group: str, error_codes: list[str]) -> bool:
        """向机械臂发送 TEST_DONE 指令。

        Args:
            group: 组号（2位十六进制）。
            error_codes: 8个错误码列表。

        Returns:
            发送是否成功。
        """
        with self._lock:
            if not self._connected or not self._client_socket:
                logger.warning("机械臂未连接，无法发送指令")
                return False

            try:
                command = ArmProtocol.build_test_done(group, error_codes)
                self._client_socket.sendall(command.encode("utf-8"))
                logger.info("已发送 TEST_DONE 到机械臂: %s", command)
                return True

            except Exception as e:
                logger.error("发送 TEST_DONE 失败: %s", e)
                self._on_error(f"发送失败: {e}")
                return False

    def send_abort(self, error_code: str = "EEEE") -> bool:
        """向机械臂发送异常中止信号。

        Args:
            error_code: 错误码，默认为 "EEEE"。

        Returns:
            发送是否成功。
        """
        with self._lock:
            if not self._connected or not self._client_socket:
                logger.warning("机械臂未连接，无法发送中止信号")
                return False

            try:
                # 发送异常中止（所有 DUT 标记为错误）
                error_codes = [error_code] * 8
                command = ArmProtocol.build_test_done("FF", error_codes)
                self._client_socket.sendall(command.encode("utf-8"))
                logger.warning("已发送异常中止信号到机械臂: %s", command)
                return True

            except Exception as e:
                logger.error("发送异常中止信号失败: %s", e)
                return False

    def _cleanup(self) -> None:
        """清理 socket 资源。"""
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

    def _run_loop(self) -> None:
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
        """处理机械臂客户端连接。

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
        if self._on_connected:
            self._on_connected(self)

        try:
            while self._running and self._connected:
                try:
                    # 使用 select 检测数据可用性
                    readable, _, _ = select.select(
                        [client_socket], [], [], self.SOCKET_TIMEOUT
                    )

                    if not readable:
                        continue

                    data = client_socket.recv(self.BUFFER_SIZE)

                except socket.timeout:
                    continue
                except Exception as e:
                    logger.error("读取数据异常: %s", e)
                    break

                if not data:
                    break

                # 解码并追加到缓冲区
                message = data.decode("utf-8")
                with self._lock:
                    self._buffer += message

                logger.debug("收到原始数据: %r", message)

                # 处理完整帧（以 '+' 结尾）
                self._process_buffer()

        except Exception as e:
            logger.error("连接处理异常: %s", e)
            if self._on_error:
                self._on_error(str(e))

        finally:
            # 连接断开清理
            self._on_disconnected_internal()

    def _process_buffer(self) -> None:
        """处理缓冲区中的数据，提取完整帧。

        注意：此方法需要在持有锁的情况下调用，或确保线程安全调用。
        缓冲区读取、处理、更新在一次锁操作内完成，避免竞态条件。
        """
        frames_to_process: list[tuple[str, dict]] = []

        # 在锁内完成所有缓冲区操作，避免竞态条件
        with self._lock:
            buffer_copy = self._buffer

            while "+" in buffer_copy:
                frame, buffer_copy = buffer_copy.split("+", 1)
                frame += "+"

                # 解析指令（纯计算操作，无需锁保护）
                result = ArmProtocol.parse_command(frame)
                if result:
                    frames_to_process.append(result)
                else:
                    logger.warning("无法解析指令帧: %s", frame.strip())

            # 原子更新缓冲区
            self._buffer = buffer_copy

        # 在锁外执行回调，避免长时间持有锁
        for cmd_type, params in frames_to_process:
            if cmd_type == "START_TEST":
                group = params.get("group", "")
                bitmask = params.get("bitmask", "")
                logger.info(
                    "收到 START_TEST - Group: %s, Bitmask: %s",
                    group,
                    bitmask,
                )
                if self._on_start_test:
                    self._on_start_test(group, bitmask)
            else:
                logger.warning("收到未知指令: %s", cmd_type)

    def _on_disconnected_internal(self) -> None:
        """内部断开连接处理。"""
        with self._lock:
            self._connected = False

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

        logger.info("机械臂已断开连接")
        if self._on_disconnected:
            self._on_disconnected(self)
