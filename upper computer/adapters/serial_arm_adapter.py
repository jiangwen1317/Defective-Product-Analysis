"""
机械臂设备适配器 - 串口模式。

支持串口通信，用于接收机械臂的指令。

协议格式：@<CMD> <参数>+ (如 @START_TEST 00 11111111+)

使用 threading + pyserial 实现，与 PyQt5 原生集成。
"""

import logging
import threading
import time
from typing import Callable

import serial

from adapters.base_arm_adapter import BaseArmAdapter

logger = logging.getLogger(__name__)


class SerialArmAdapter(BaseArmAdapter):
    """机械臂设备串口适配器。

    通过串口与机械臂通信，接收测试指令并返回测试结果。

    使用独立线程持续读取串口数据，事件驱动回调通知上层应用。
    """

    # 默认串口配置
    DEFAULT_BAUDRATE: int = 115200
    DEFAULT_BYTESIZE: int = serial.EIGHTBITS
    DEFAULT_STOPBITS: int = serial.STOPBITS_ONE
    DEFAULT_PARITY: str = serial.PARITY_NONE
    DEFAULT_TIMEOUT: float = 0.1

    def __init__(
        self,
        port: str = "COM3",
        baudrate: int = DEFAULT_BAUDRATE,
        bytesize: int = DEFAULT_BYTESIZE,
        stopbits: int = DEFAULT_STOPBITS,
        parity: str = DEFAULT_PARITY,
        timeout: float = DEFAULT_TIMEOUT,
        reconnect_interval: float = 5.0,
        on_connected: Callable[["SerialArmAdapter"], None] | None = None,
        on_disconnected: Callable[["SerialArmAdapter"], None] | None = None,
        on_data_received: Callable[[str], None] | None = None,
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
            reconnect_interval: 重连间隔秒数。
            on_connected: 串口打开成功回调。
            on_disconnected: 串口关闭回调。
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

        self._port = port
        self._baudrate = baudrate
        self._bytesize = bytesize
        self._stopbits = stopbits
        self._parity = parity
        self._timeout = timeout
        self._serial: serial.Serial | None = None
        self._receive_thread: threading.Thread | None = None

    @property
    def port_name(self) -> str:
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

    def start(self) -> bool:
        """启动适配器，打开串口并开始监听。

        Returns:
            启动是否成功。
        """
        if self._running:
            logger.warning("适配器已在运行")
            return True

        if not self._do_connect():
            return False

        # 发送初始化序列
        self._send_init_sequence()

        self._running = True
        self._stop_reconnect.clear()
        self._start_receive_thread()

        logger.info("机械臂串口适配器已启动 [端口: %s, 波特率: %d]", self._port, self._baudrate)
        return True

    def _do_connect(self) -> bool:
        """执行实际连接操作。"""
        # 先释放可能残留的旧句柄（重连场景），
        # 否则 Windows 下 COM 口可能被旧句柄占用导致重连永远失败
        self._close_serial()

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

            logger.info("串口已打开: %s", self._port)
            self._on_connected_internal()
            return True

        except serial.SerialException as e:
            logger.error("打开串口失败: %s - %s", self._port, e)
            # 重连循环中的失败只记日志，避免每个重连周期都向 UI 弹告警刷屏
            if not self._reconnecting and self._on_error:
                self._on_error(f"打开串口失败: {e}")
            return False

    def _do_disconnect(self) -> None:
        """执行实际断开连接操作。"""
        with self._lock:
            self._connected = False
        self._close_serial()

    def _close_serial(self) -> None:
        """关闭并清空串口句柄（已失效句柄的关闭异常可安全忽略）。"""
        with self._lock:
            if self._serial:
                try:
                    self._serial.close()
                except Exception:
                    pass
                self._serial = None

    def _read_available(self) -> bytes | None:
        """读取可用数据。

        Returns:
            读取的字节数据，无数据时返回 None。

        Raises:
            ConnectionError: 串口失效（如 USB 设备拔出）时。
        """
        if not self._serial or not self._serial.is_open:
            return None

        try:
            if self._serial.in_waiting > 0:
                return self._serial.read(self._serial.in_waiting)
            return None
        except serial.SerialException as e:
            # USB 拔出等串口失效：必须抛出让接收循环走断开流程，
            # 否则返回 None 会导致断线永远检测不到，UI 持续显示在线
            raise ConnectionError(f"串口异常: {e}") from e

    def _write_data(self, data: str) -> bool:
        """发送数据。"""
        try:
            self._serial.write(data.encode("utf-8"))
            self._serial.flush()
            logger.debug("已发送数据: %r", data)
            return True
        except Exception as e:
            logger.error("发送数据失败: %s", e)
            return False

    def _send_init_sequence(self) -> None:
        """发送初始化序列到机械臂。

        初始化流程：
        1. 发送 'e' 触发机械臂进入配置模式
        2. 发送 '4' 启动测试脚本
        """
        logger.info("发送初始化序列到机械臂...")
        time.sleep(0.5)

        # 步骤1：发送 'e' 触发机械臂进入配置模式
        try:
            self._serial.write(b'e')
            self._serial.flush()
            logger.info("已发送: 'e' (触发配置模式)")
        except Exception as e:
            logger.error("发送 'e' 失败: %s", e)
            return

        time.sleep(1.0)

        # 读取响应
        try:
            if self._serial.in_waiting > 0:
                response = self._serial.read(self._serial.in_waiting)
                logger.info("机械臂响应: %r", response)
        except Exception as e:
            logger.warning("读取响应失败: %s", e)

        # 步骤2：发送 '4' 启动测试脚本
        try:
            self._serial.write(b'4')
            self._serial.flush()
            logger.info("已发送: '4' (启动测试脚本)")
        except Exception as e:
            logger.error("发送 '4' 失败: %s", e)
            return

        time.sleep(1.0)

        # 读取响应
        try:
            if self._serial.in_waiting > 0:
                response = self._serial.read(self._serial.in_waiting)
                logger.info("机械臂响应: %r", response)
        except Exception as e:
            logger.warning("读取响应失败: %s", e)

        logger.info("初始化序列发送完成，等待机械臂进入传输状态...")

    def _on_reconnect_success(self) -> None:
        """重连成功：补发初始化序列后再启动接收线程。

        机械臂重新上电后需要重新进入传输状态，
        与首次 start() 的初始化流程保持一致。
        """
        self._send_init_sequence()
        super()._on_reconnect_success()
