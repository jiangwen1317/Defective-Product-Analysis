"""
3720 芯片测试仪适配器 - TCP 客户端模式。

通过 TCP 与 3720 测试仪通信，发送测试指令并接收结果。

使用 threading + socket 实现，与 PyQt5 原生集成。
"""

import logging
import re
import socket
import threading
import time
from typing import Callable

# 从 tc3720_adapter 导入共享的 TC3720Status
from .tc3720_adapter import TC3720Status

logger = logging.getLogger(__name__)


class TC3720TcpAdapter:
    """3720 芯片测试仪 TCP 适配器。

    作为 TCP 客户端连接 3720 测试仪：
    - 连接管理（自动重连）
    - 发送测试启动信号（trigger_test() 方法）
    - 接收测试结果
    - 状态上报

    使用独立线程处理网络通信，事件驱动回调通知上层应用。
    """

    # 网络配置
    DEFAULT_HOST: str = "192.168.1.101"
    DEFAULT_PORT: int = 9090
    BUFFER_SIZE: int = 1024
    SOCKET_TIMEOUT: float = 1.0  # socket 超时时间（秒）
    CONNECT_TIMEOUT: float = 5.0  # 连接超时时间（秒）
    RECONNECT_INTERVAL: float = 3.0  # 重连间隔（秒）

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        reconnect_interval: float = RECONNECT_INTERVAL,
        on_status_changed: Callable[[TC3720Status], None] | None = None,
        on_test_complete: Callable[[list[str]], None] | None = None,  # error_codes
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        """初始化 3720 TCP 适配器。

        Args:
            host: 3720 测试仪 IP 地址。
            port: 3720 测试仪端口号。
            reconnect_interval: 重连间隔秒数。
            on_status_changed: 状态变化回调。
            on_test_complete: 测试完成回调（返回错误码列表）。
            on_error: 错误发生回调。
        """
        self._host = host
        self._port = port
        self._reconnect_interval = reconnect_interval
        self._on_status_changed = on_status_changed
        self._on_test_complete = on_test_complete
        self._on_error = on_error

        # 网络资源
        self._socket: socket.socket | None = None

        # 线程资源
        self._thread: threading.Thread | None = None
        self._running = False
        self._connected = False

        # 内部状态
        self._status = TC3720Status.OFFLINE
        self._pending_test = False  # 是否有待处理的测试

        # 读取缓冲区
        self._buffer: str = ""

        # 锁
        self._lock = threading.Lock()

        # 重连线程
        self._reconnect_thread: threading.Thread | None = None
        self._stop_reconnect = threading.Event()
        self._reconnecting = False  # 标记是否正在重连
        self._reconnect_lock = threading.Lock()  # 重连操作专用锁

    @property
    def host(self) -> str:
        """3720 IP 地址。"""
        return self._host

    @property
    def port(self) -> int:
        """3720 端口号。"""
        return self._port

    @property
    def status(self) -> TC3720Status:
        """当前设备状态。"""
        with self._lock:
            return self._status

    @property
    def is_online(self) -> bool:
        """设备是否在线。"""
        with self._lock:
            return self._status != TC3720Status.OFFLINE

    @property
    def is_testing(self) -> bool:
        """是否正在测试。"""
        with self._lock:
            return self._status == TC3720Status.TESTING

    @property
    def is_connected(self) -> bool:
        """TCP 是否已连接。"""
        with self._lock:
            return self._connected and self._socket is not None

    def _set_status(self, new_status: TC3720Status) -> None:
        """更新设备状态并触发回调（线程安全）。"""
        with self._lock:
            if self._status == new_status:
                return
            old_status = self._status
            self._status = new_status

        logger.info("3720 状态变化: %s -> %s", old_status.value, new_status.value)
        if self._on_status_changed:
            self._on_status_changed(new_status)

    def connect(self) -> bool:
        """建立与 3720 设备的 TCP 连接。

        Returns:
            连接是否成功。
        """
        with self._lock:
            if self._running:
                return True

        self._running = True
        self._stop_reconnect.clear()

        # 先尝试连接
        if not self._do_connect():
            # 连接失败，启动重连线程（状态保持 OFFLINE）
            logger.warning("3720 初始连接失败，已启动重连线程")
            self._reconnect_thread = threading.Thread(
                target=self._reconnect_loop,
                name="TC3720-Reconnect",
                daemon=True,
            )
            self._reconnect_thread.start()
            # 不要设置状态为 IDLE，保持 OFFLINE 直到重连成功
            logger.info("3720 TCP 适配器已启动（等待重连），目标: %s:%d", self._host, self._port)
            return True  # 返回 True 表示适配器启动成功（会在后台重连）
        else:
            # 连接成功，启动接收线程
            self._thread = threading.Thread(
                target=self._run_receive_loop,
                name=f"TC3720-Receive-{self._host}:{self._port}",
                daemon=True,
            )
            self._thread.start()
            # 只有真正连接成功才设置状态为 IDLE
            self._set_status(TC3720Status.IDLE)
            logger.info("3720 TCP 适配器已启动，目标: %s:%d", self._host, self._port)
            return True

    def _do_connect(self) -> bool:
        """执行 TCP 连接。

        Returns:
            连接是否成功。
        """
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.CONNECT_TIMEOUT)
            sock.connect((self._host, self._port))
            sock.settimeout(self.SOCKET_TIMEOUT)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)

            with self._lock:
                self._socket = sock
                self._connected = True
                self._buffer = ""

            logger.info("已连接到 3720: %s:%d", self._host, self._port)
            return True

        except (OSError, socket.timeout) as e:
            logger.warning("连接 3720 失败: %s:%d - %s", self._host, self._port, e)
            return False

    def _reconnect_loop(self) -> None:
        """重连循环。"""
        try:
            while self._running and not self._stop_reconnect.is_set():
                if self._do_connect():
                    # 连接成功，启动接收线程
                    self._thread = threading.Thread(
                        target=self._run_receive_loop,
                        name=f"TC3720-Receive-{self._host}:{self._port}",
                        daemon=True,
                    )
                    self._thread.start()
                    # 重连成功后设置状态为 IDLE
                    self._set_status(TC3720Status.IDLE)
                    logger.info("3720 重连成功，目标: %s:%d", self._host, self._port)
                    return

                # 等待重连间隔
                for _ in range(int(self._reconnect_interval * 10)):
                    if self._stop_reconnect.is_set() or not self._running:
                        return
                    time.sleep(0.1)
        finally:
            # 重置重连标志
            with self._reconnect_lock:
                self._reconnecting = False
            logger.info("3720 重连线程退出")

    def disconnect(self) -> None:
        """断开与 3720 设备的连接。"""
        if not self._running:
            return

        logger.info("断开 3720 连接...")
        self._running = False
        self._stop_reconnect.set()

        # 等待重连线程结束
        if self._reconnect_thread and self._reconnect_thread.is_alive():
            self._reconnect_thread.join(timeout=1.0)
            self._reconnect_thread = None

        # 等待主线程结束
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
            self._thread = None

        # 清理资源
        self._cleanup()

        self._set_status(TC3720Status.OFFLINE)
        logger.info("3720 连接已断开")

    def _cleanup(self) -> None:
        """清理 socket 资源。"""
        with self._lock:
            self._connected = False

            if self._socket:
                try:
                    self._socket.shutdown(socket.SHUT_RDWR)
                except Exception:
                    pass
                try:
                    self._socket.close()
                except Exception:
                    pass
                self._socket = None

    def trigger_test(self, timeout: float = 30.0) -> bool:
        """向 3720 发送启动信号（协议规定的 "START" 命令）。

        设置 _pending_test = True，确保收到 ErrorCode 响应时能正确处理。

        Args:
            timeout: 测试超时时间（秒）。

        Returns:
            启动是否成功。
        """
        with self._lock:
            if not self._running:
                logger.error("3720 未连接，无法发送启动信号")
                return False

            if self._status == TC3720Status.TESTING:
                logger.warning("3720 正在测试中，忽略重复请求")
                return False

        # 发送 START 信号（协议规定的 5 个大写字母）
        command = "START"

        logger.info("向 3720 发送启动信号: %r", command)

        # 保存待处理测试信息
        with self._lock:
            self._pending_test = True

        # 发送指令
        if not self._send_command(command):
            with self._lock:
                self._pending_test = False
            logger.error("发送启动信号失败")
            return False

        # 更新状态
        self._set_status(TC3720Status.TESTING)

        # 启动超时监控
        threading.Thread(
            target=self._timeout_monitor,
            args=(timeout,),
            name="TC3720-Timeout",
            daemon=True,
        ).start()

        return True

    def _send_command(self, command: str) -> bool:
        """发送指令。

        Args:
            command: 指令字符串。

        Returns:
            发送是否成功。
        """
        with self._lock:
            if not self._connected or not self._socket:
                logger.warning("3720 未连接，无法发送指令")
                return False

            try:
                self._socket.sendall(command.encode("utf-8"))
                logger.debug("已发送指令: %r", command)
                return True

            except Exception as e:
                logger.error("发送指令失败: %s", e)
                return False

    def _timeout_monitor(self, timeout: float) -> None:
        """测试超时监控。

        Args:
            timeout: 超时时间（秒）。
        """
        start_time = time.time()

        while self._running:
            elapsed = time.time() - start_time

            if elapsed >= timeout:
                # 锁内只做判断与标志修改；_set_status 与回调必须在锁外执行，
                # 否则嵌套获取同一把非重入锁会永久死锁
                timed_out = False
                with self._lock:
                    if self._pending_test and self._status == TC3720Status.TESTING:
                        self._pending_test = False
                        timed_out = True

                if timed_out:
                    logger.error("3720 测试超时 (%.1f秒)", timeout)
                    self._set_status(TC3720Status.IDLE)
                    if self._on_error:
                        self._on_error("测试超时")
                return

            with self._lock:
                if not self._pending_test:
                    return

            time.sleep(0.1)

    def _run_receive_loop(self) -> None:
        """接收数据主循环（在独立线程中运行）。"""
        logger.info("3720 接收线程启动")

        while self._running and self._connected:
            try:
                # 接收数据
                data = self._socket.recv(self.BUFFER_SIZE)

                if not data:
                    logger.info("3720 连接已关闭")
                    break

                # 解码数据
                message = data.decode("utf-8", errors="replace")
                logger.info("收到 3720 数据 [%d 字节]: %r", len(message), message)

                # 协议模式：处理接收到的数据
                with self._lock:
                    self._buffer += message
                self._process_buffer()

            except socket.timeout:
                continue
            except Exception as e:
                logger.error("接收 3720 数据异常: %s", e)
                break

        logger.info("3720 接收线程退出")

        # 连接断开处理
        self._on_disconnected_internal()

        # 自动重连
        if self._running:
            self._start_reconnect()

    def _process_buffer(self) -> None:
        """处理接收缓冲区中的数据。

        根据 3720 协议解析响应：
        - 测试完成响应: RESULT <ec1> <ec2> ... <ec8>
        - 错误响应: ERROR <code>

        行提取在锁内直接消费 self._buffer，解析回调在锁外执行，
        避免"拷贝-解析-覆盖回写"模式在解析窗口期丢失新到达的数据。
        """
        lines: list[str] = []

        with self._lock:
            # 查找行结束符（根据实际协议，可能是 \r\n、\n 或 \r）
            while True:
                idx_n = self._buffer.find("\n")
                idx_r = self._buffer.find("\r")
                if idx_n == -1 and idx_r == -1:
                    break

                if idx_r != -1 and (idx_n == -1 or idx_r < idx_n):
                    end = idx_r
                    # \r\n 作为整体跳过
                    skip = 2 if self._buffer[idx_r:idx_r + 2] == "\r\n" else 1
                else:
                    end = idx_n
                    skip = 1

                line = self._buffer[:end]
                self._buffer = self._buffer[end + skip:]

                # 移除首尾空白及 \x00 等 NULL 字符
                line = line.strip().strip("\x00").strip()
                if line:
                    lines.append(line)

        for line in lines:
            logger.debug("3720 响应行: %r", line)
            # 解析响应（根据实际协议修改）
            self._parse_response(line)

    def _parse_response(self, line: str) -> None:
        """解析 3720 响应。

        支持的响应格式：
        - ErrorCode: XXXX (单错误码，4位十六进制)
        - RESULT <ec1> <ec2> ... <ec8> (多错误码)
        - OK / ACK (确认响应)
        - ERROR <message> (错误响应)

        Args:
            line: 响应行。
        """
        line = line.strip()
        # 额外移除 \x00 等 NULL 字符
        line = line.strip("\x00").strip()

        if not line:
            return

        # 检查 ErrorCode: XXXX 格式
        if line.upper().startswith("ERRORCODE:"):
            self._parse_error_code_response(line)
            return

        parts = line.split()
        cmd = parts[0].upper()

        if cmd == "RESULT" or cmd == "TEST_DONE":
            # 测试结果响应
            # 格式: RESULT <ec1> <ec2> ... <ec8>
            if len(parts) >= 9:
                error_codes = parts[1:9]
                self._handle_test_result(error_codes)
            else:
                logger.warning("3720 RESULT 响应参数不足")

        elif cmd == "OK" or cmd == "ACK":
            # 确认响应
            logger.info("3720 确认响应: %s", line)

        elif cmd == "ERROR":
            # 错误响应
            error_msg = " ".join(parts[1:]) if len(parts) > 1 else "未知错误"
            logger.error("3720 错误响应: %s", error_msg)
            self._handle_error(error_msg)

        elif cmd == "STATUS":
            # 状态查询响应
            logger.info("3720 状态: %s", " ".join(parts[1:]))

        else:
            # 未知响应
            logger.warning("3720 未知响应: %s", line)

    def _parse_error_code_response(self, line: str) -> None:
        """解析 ErrorCode: XXXX 格式的响应。

        Args:
            line: 响应行，格式为 "ErrorCode: XXXX"。
        """
        # 匹配 "ErrorCode: XXXX" 格式
        match = re.match(r"^ErrorCode:\s*([0-9A-Fa-f]{4})$", line, re.IGNORECASE)
        if not match:
            logger.warning("无法解析 ErrorCode 响应格式: %s", line)
            return

        error_code = match.group(1).upper()
        logger.info("3720 收到错误码: %s", error_code)

        # 检查是否有待处理的测试
        with self._lock:
            if not self._pending_test:
                logger.warning("收到错误码但没有待处理的测试: %s", error_code)
                return

        # 构造成单错误码列表
        error_codes = [error_code]

        # 更新状态并触发回调
        with self._lock:
            self._pending_test = False

        self._set_status(TC3720Status.IDLE)

        if self._on_test_complete:
            self._on_test_complete(error_codes)

    def _handle_test_result(self, error_codes: list[str]) -> None:
        """处理测试结果。

        Args:
            error_codes: 8个错误码列表。
        """
        with self._lock:
            if not self._pending_test:
                logger.warning("收到测试结果但没有待处理的测试")
                return

            self._pending_test = False

        self._set_status(TC3720Status.IDLE)

        logger.info("3720 测试完成 - ErrorCodes: %s", error_codes)

        if self._on_test_complete:
            self._on_test_complete(error_codes)

    def _handle_error(self, error_msg: str) -> None:
        """处理 3720 错误。

        Args:
            error_msg: 错误消息。
        """
        with self._lock:
            self._pending_test = False

        self._set_status(TC3720Status.ERROR)

        if self._on_error:
            self._on_error(error_msg)

    def _on_disconnected_internal(self) -> None:
        """内部断开连接处理。"""
        with self._lock:
            self._connected = False
            self._pending_test = False

            if self._socket:
                try:
                    self._socket.close()
                except Exception:
                    pass
                self._socket = None

        self._set_status(TC3720Status.OFFLINE)
        logger.info("3720 连接已断开")

    def _start_reconnect(self) -> None:
        """启动重连（线程安全，确保只有一个重连线程）。"""
        with self._reconnect_lock:
            # 检查是否已经有重连线程在运行
            if self._reconnecting:
                logger.debug("重连线程已在运行，跳过")
                return

            # 检查现有线程是否还活着
            if self._reconnect_thread and self._reconnect_thread.is_alive():
                logger.debug("重连线程仍在运行，跳过")
                return

            self._reconnecting = True
            self._stop_reconnect.clear()

            self._reconnect_thread = threading.Thread(
                target=self._reconnect_loop,
                name="TC3720-Reconnect",
                daemon=True,
            )
            self._reconnect_thread.start()
