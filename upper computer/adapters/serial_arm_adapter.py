"""
机械臂设备适配器 - 串口模式。

支持串口通信，用于接收机械臂的指令。

协议格式：@<CMD> <参数>+ (如 @START_TEST 00 11111111+)

使用 threading + pyserial 实现，与 PyQt5 原生集成。
"""

import logging
import sys
import threading
import time
from enum import Enum
from pathlib import Path
from typing import Callable

# 将项目根目录添加到 Python 搜索路径
_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import serial
import serial.tools.list_ports

from protocol.arm_protocol import ArmProtocol

logger = logging.getLogger(__name__)


class SerialArmMode(Enum):
    """串口工作模式。"""
    SERIAL = "serial"


class SerialArmAdapter:
    """机械臂设备串口适配器。

    通过串口与机械臂通信，接收测试指令并返回测试结果。

    使用独立线程持续读取串口数据，事件驱动回调通知上层应用。
    """

    # 常用波特率选项
    BAUDRATES = [9600, 19200, 38400, 57600, 115200]

    # 默认串口配置
    DEFAULT_BAUDRATE: int = 115200
    DEFAULT_BYTESIZE: int = serial.EIGHTBITS  # 8位数据位
    DEFAULT_STOPBITS: int = serial.STOPBITS_ONE  # 1位停止位
    DEFAULT_PARITY: str = serial.PARITY_NONE  # 无校验
    DEFAULT_TIMEOUT: float = 0.1  # 读取超时（秒）

    def __init__(
        self,
        port: str = "COM3",
        baudrate: int = DEFAULT_BAUDRATE,
        bytesize: int = DEFAULT_BYTESIZE,
        stopbits: int = DEFAULT_STOPBITS,
        parity: str = DEFAULT_PARITY,
        timeout: float = DEFAULT_TIMEOUT,
        on_connected: Callable[["SerialArmAdapter"], None] | None = None,
        on_disconnected: Callable[["SerialArmAdapter"], None] | None = None,
        on_start_test: Callable[[str, str], None] | None = None,  # group, bitmask
        on_data_received: Callable[[str], None] | None = None,  # 用于回显测试
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        """初始化串口适配器。

        Args:
            port: 串口名称，如 'COM3'（Windows）或 '/dev/ttyUSB0'（Linux）。
            baudrate: 波特率，默认 115200。
            bytesize: 数据位，默认 8 位。
            stopbits: 停止位，默认 1 位。
            parity: 校验位，默认无校验。
            timeout: 读取超时时间（秒）。
            on_connected: 串口打开成功回调。
            on_disconnected: 串口关闭回调。
            on_start_test: 收到 START_TEST 指令回调。
            on_data_received: 收到任意数据回调（用于回显测试调试）。
            on_error: 错误发生回调。
        """
        self._port = port
        self._baudrate = baudrate
        self._bytesize = bytesize
        self._stopbits = stopbits
        self._parity = parity
        self._timeout = timeout

        self._on_connected = on_connected
        self._on_disconnected = on_disconnected
        self._on_start_test = on_start_test
        self._on_data_received = on_data_received
        self._on_error = on_error

        # 串口资源
        self._serial: serial.Serial | None = None

        # 线程资源
        self._thread: threading.Thread | None = None
        self._running = False
        self._connected = False

        # 读取缓冲区（字节串）
        self._buffer: bytearray = bytearray()

        # 锁
        self._lock = threading.Lock()

    @property
    def port(self) -> str:
        """串口名称。"""
        return self._port

    @property
    def baudrate(self) -> int:
        """波特率。"""
        return self._baudrate

    @property
    def is_connected(self) -> bool:
        """串口是否已连接。"""
        with self._lock:
            return self._connected and self._serial is not None and self._serial.is_open

    def get_available_ports() -> list[str]:
        """获取系统中可用的串口列表。

        Returns:
            可用串口名称列表。
        """
        ports = serial.tools.list_ports.comports()
        return [port.device for port in ports]

    def start(self) -> bool:
        """启动适配器，打开串口并开始监听。

        Returns:
            启动是否成功。
        """
        if self._running:
            logger.warning("适配器已在运行")
            return True

        if not self._open_serial():
            return False

        # 发送初始化序列：进入特殊模式并启动脚本
        self._send_init_sequence()

        self._running = True

        # 启动接收线程
        self._thread = threading.Thread(
            target=self._run_read_loop,
            name=f"SerialArmAdapter-{self._port}",
            daemon=True,
        )
        self._thread.start()

        logger.info("机械臂串口适配器已启动 [端口: %s, 波特率: %d]", self._port, self._baudrate)
        return True

    def _send_init_sequence(self) -> None:
        """发送初始化序列到机械臂。

        流程：
        1. 发送 'e' 进入特殊模式
        2. 等待响应
        3. 发送 '4' 启动特殊脚本
        4. 等待进入传输状态
        """
        logger.info("发送初始化序列到机械臂...")

        # 等待一下让机械臂准备好
        time.sleep(0.5)

        # 发送 'e' 进入特殊模式
        try:
            self._serial.write(b'e')
            self._serial.flush()
            logger.info("已发送: 'e' (进入特殊模式)")
        except Exception as e:
            logger.error("发送 'e' 失败: %s", e)
            return

        # 等待响应
        time.sleep(1.0)

        # 读取响应
        try:
            if self._serial.in_waiting > 0:
                response = self._serial.read(self._serial.in_waiting)
                logger.info("机械臂响应: %r", response)
        except Exception as e:
            logger.warning("读取响应失败: %s", e)

        # 发送 '4' 启动特殊脚本
        try:
            self._serial.write(b'4')
            self._serial.flush()
            logger.info("已发送: '4' (启动特殊脚本)")
        except Exception as e:
            logger.error("发送 '4' 失败: %s", e)
            return

        # 等待进入传输状态
        time.sleep(1.0)

        # 读取响应
        try:
            if self._serial.in_waiting > 0:
                response = self._serial.read(self._serial.in_waiting)
                logger.info("机械臂响应: %r", response)
        except Exception as e:
            logger.warning("读取响应失败: %s", e)

        logger.info("初始化序列发送完成，等待机械臂进入传输状态...")

    def _open_serial(self) -> bool:
        """打开串口连接。

        Returns:
            打开是否成功。
        """
        try:
            self._serial = serial.Serial(
                port=self._port,
                baudrate=self._baudrate,
                bytesize=self._bytesize,
                stopbits=self._stopbits,
                parity=self._parity,
                timeout=self._timeout,
                write_timeout=1.0,
            )

            with self._lock:
                self._connected = True
                self._buffer.clear()

            logger.info("串口已打开: %s", self._port)

            # 在锁外触发回调，避免潜在的死锁
            on_connected = self._on_connected
            if on_connected:
                on_connected(self)

            return True

        except serial.SerialException as e:
            logger.error("打开串口失败: %s - %s", self._port, e)
            on_error = self._on_error
            if on_error:
                on_error(f"打开串口失败: {e}")
            return False

    def stop(self) -> None:
        """停止适配器，关闭串口。"""
        if not self._running:
            return

        logger.info("停止机械臂串口适配器...")
        self._running = False

        # 等待线程结束
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
            self._thread = None

        # 关闭串口
        self._close_serial()

        logger.info("机械臂串口适配器已停止")

    def _close_serial(self) -> None:
        """关闭串口连接。"""
        with self._lock:
            self._connected = False

            if self._serial:
                try:
                    self._serial.close()
                except Exception:
                    pass
                self._serial = None

        if self._on_disconnected:
            self._on_disconnected(self)

        logger.info("串口已关闭")

    def send_raw(self, data: str) -> bool:
        """发送原始数据（用于回显测试）。

        Args:
            data: 要发送的原始字符串。

        Returns:
            发送是否成功。
        """
        with self._lock:
            if not self._connected or not self._serial or not self._serial.is_open:
                logger.warning("串口未连接，无法发送数据")
                return False

            try:
                self._serial.write(data.encode("utf-8"))
                self._serial.flush()
                logger.info("已发送原始数据: %r", data)
                return True

            except Exception as e:
                logger.error("发送数据失败: %s", e)
                return False

    def send_test_done(self, group: str, error_codes: list[str]) -> bool:
        """向机械臂发送 TEST_DONE 指令。

        Args:
            group: 组号（2位十六进制）。
            error_codes: 8个错误码列表。

        Returns:
            发送是否成功。
        """
        with self._lock:
            if not self._connected or not self._serial or not self._serial.is_open:
                logger.warning("串口未连接，无法发送指令")
                return False

            try:
                command = ArmProtocol.build_test_done(group, error_codes)
                self._serial.write(command.encode("utf-8"))
                self._serial.flush()
                logger.info("已发送 TEST_DONE: %s", command)
                return True

            except Exception as e:
                logger.error("发送 TEST_DONE 失败: %s", e)
                if self._on_error:
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
            if not self._connected or not self._serial or not self._serial.is_open:
                logger.warning("串口未连接，无法发送中止信号")
                return False

            try:
                # 发送异常中止（所有 DUT 标记为错误）
                error_codes = [error_code] * 8
                command = ArmProtocol.build_test_done("FF", error_codes)
                self._serial.write(command.encode("utf-8"))
                self._serial.flush()
                logger.warning("已发送异常中止信号: %s", command)
                return True

            except Exception as e:
                logger.error("发送异常中止信号失败: %s", e)
                return False

    def _run_read_loop(self) -> None:
        """串口读取主循环（在独立线程中运行）。

        改进：累积数据直到遇到帧边界（\r\n），然后一次性触发回调。
        这样可以解决串口数据分片到达导致的消息不完整问题。
        """
        logger.info("串口读取线程启动")

        # 累积缓冲区（用于合并分片数据）
        line_buffer = ""

        while self._running:
            try:
                # 检查串口是否有效
                with self._lock:
                    serial_port = self._serial

                if not serial_port or not serial_port.is_open:
                    break

                # 读取可用数据
                try:
                    data = serial_port.read(serial_port.in_waiting or 1)
                except serial.SerialException as e:
                    logger.error("读取串口数据异常: %s", e)
                    break

                if not data:
                    # 检查累积缓冲区中是否有未处理的完整行
                    if line_buffer and "\n" in line_buffer:
                        line, line_buffer = self._extract_complete_line(line_buffer)
                        if line:
                            self._on_line_received(line)
                    continue

                # 追加到行缓冲区
                decoded_data = data.decode("utf-8", errors="replace")
                line_buffer += decoded_data

                # 检查是否有完整的行（以 \n 结尾）
                while "\n" in line_buffer:
                    line, line_buffer = self._extract_complete_line(line_buffer)
                    if line:
                        self._on_line_received(line)

            except Exception as e:
                logger.error("串口读取循环异常: %s", e)
                if self._on_error:
                    self._on_error(str(e))

        logger.info("串口读取线程退出")

        # 处理残留的缓冲区数据
        if line_buffer.strip():
            logger.debug("处理残留缓冲区数据: %r", line_buffer)

        # 连接断开清理
        self._close_serial()

    def _extract_complete_line(self, buffer: str) -> tuple[str, str]:
        """从缓冲区提取完整的行。

        Args:
            buffer: 累积的缓冲区

        Returns:
            (完整行, 剩余缓冲区)
        """
        if "\r\n" in buffer:
            line, remaining = buffer.split("\r\n", 1)
            return line + "\r\n", remaining
        elif "\n" in buffer:
            line, remaining = buffer.split("\n", 1)
            return line + "\n", remaining
        elif "\r" in buffer:
            line, remaining = buffer.split("\r", 1)
            return line + "\r", remaining
        return "", buffer

    def _on_line_received(self, line: str) -> None:
        """处理完整的行数据。

        Args:
            line: 完整的行数据（包含换行符）
        """
        # 触发数据接收回调
        if self._on_data_received:
            try:
                self._on_data_received(line)
            except Exception:
                pass

        # 处理完整帧（以 '+' 结尾的协议帧）
        self._process_buffer_for_frame(line)

    def _process_buffer_for_frame(self, line: str) -> None:
        """处理缓冲区中的数据，提取完整帧。

        注意：此方法需要在持有锁的情况下调用，或确保线程安全调用。
        """
        frames_to_process: list[tuple[str, dict]] = []

        # 在锁内完成所有缓冲区操作
        with self._lock:
            buffer_bytes = bytes(self._buffer)

            # 查找帧分隔符 '+'
            while b"+" in buffer_bytes:
                # 查找完整的帧（从 '@' 开始到 '+' 结束）
                try:
                    start_idx = buffer_bytes.index(b"@")
                    end_idx = buffer_bytes.index(b"+", start_idx)
                except ValueError:
                    # 没有完整的帧，清除无效数据
                    if b"@" in buffer_bytes:
                        # 保留最后的 '@' 可能开始的帧
                        self._buffer = bytearray(buffer_bytes[buffer_bytes.index(b"@"):])
                    else:
                        self._buffer.clear()
                    break

                # 提取完整帧
                frame_bytes = buffer_bytes[start_idx:end_idx + 1]
                buffer_bytes = buffer_bytes[end_idx + 1:]

                try:
                    frame_str = frame_bytes.decode("utf-8")
                    logger.debug("收到原始帧: %r", frame_str)

                    # 解析指令
                    result = ArmProtocol.parse_command(frame_str)
                    if result:
                        frames_to_process.append(result)
                    else:
                        logger.warning("无法解析指令帧: %s", frame_str.strip())
                except UnicodeDecodeError as e:
                    logger.warning("帧解码失败: %s", e)

            # 更新缓冲区
            self._buffer = bytearray(buffer_bytes)

        # 在锁外执行回调，避免长时间持有锁
        for cmd_type, params in frames_to_process:
            if cmd_type == "START_TEST":
                group = params.get("group", "")
                bitmask = params.get("bitmask", "")
                logger.info("收到 START_TEST - Group: %s, Bitmask: %s", group, bitmask)
                if self._on_start_test:
                    self._on_start_test(group, bitmask)
            else:
                logger.warning("收到未知指令: %s", cmd_type)
