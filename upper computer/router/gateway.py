"""
信号路由层 - 透明中转网关。

实现机械臂与 3720 测试仪之间的纯数据透传，不做任何协议解析。

架构：
  机械臂 <──串口──> 上位机 <──TCP──> 3720测试仪
                     ↓
               纯数据透传
               （日志记录）

使用 threading 架构，确保线程安全。
"""

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Callable

from adapters import TC3720Status

logger = logging.getLogger(__name__)


class GatewayState(Enum):
    """网关状态枚举。"""

    IDLE = "idle"  # 空闲监听
    FORWARDING = "forwarding"  # 透传中
    ERROR = "error"  # 异常状态


class ErrorCode(Enum):
    """网关错误码定义。"""

    NONE = "0000"
    ARM_DISCONNECTED = "E003"
    TC3720_ERROR = "E004"
    UNKNOWN = "EEEE"


@dataclass
class TransferRecord:
    """中转记录。"""

    timestamp: str
    direction: str  # "arm_to_3720" 或 "3720_to_arm"
    raw_data: str
    size: int
    error_code: ErrorCode = ErrorCode.NONE
    error_message: str = ""


@dataclass
class GatewayConfig:
    """网关配置。"""

    # 机械臂配置
    arm_mode: str = "tcp_server"
    arm_host: str = "0.0.0.0"
    arm_port: int = 8080
    arm_target_host: str = ""
    arm_target_port: int = 0
    arm_reconnect_interval: float = 5.0
    # 串口模式
    arm_serial_port: str = "COM3"
    arm_serial_baudrate: int = 115200
    arm_serial_bytesize: int = 8
    arm_serial_stopbits: int = 1
    arm_serial_parity: str = "N"
    # 3720 配置
    tc3720_mode: str = "tcp"
    tc3720_host: str = "192.168.1.101"
    tc3720_port: int = 9090
    test_timeout: float = 30.0
    enable_debug: bool = False


class PassthroughGateway:
    """透明中转网关。

    纯数据透传模式：
    1. 机械臂数据 -> 直接转发到 3720
    2. 3720 数据 -> 直接转发到机械臂
    3. 记录所有中转数据

    不做任何协议解析，只是透传。
    """

    def __init__(
        self,
        config: GatewayConfig | None = None,
        on_state_changed: Callable[[GatewayState], None] | None = None,
        on_arm_connected: Callable[[bool], None] | None = None,
        on_3720_status_changed: Callable[[TC3720Status], None] | None = None,
        on_record: Callable[[TransferRecord], None] | None = None,
        on_raw_data: Callable[[str, str], None] | None = None,  # direction, data
        on_error: Callable[[ErrorCode, str], None] | None = None,
    ) -> None:
        """初始化透明中转网关。

        Args:
            config: 网关配置。
            on_state_changed: 状态变化回调。
            on_arm_connected: 机械臂连接状态变化回调。
            on_3720_status_changed: 3720 状态变化回调。
            on_record: 中转记录回调。
            on_raw_data: 原始数据回调（direction: "arm_to_3720" 或 "3720_to_arm"）。
            on_error: 错误发生回调。
        """
        self._config = config or GatewayConfig()
        self._on_state_changed = on_state_changed
        self._on_arm_connected = on_arm_connected
        self._on_3720_status_changed = on_3720_status_changed
        self._on_record = on_record
        self._on_raw_data = on_raw_data
        self._on_error = on_error

        # 适配器
        self._arm_adapter = None
        self._tc3720_adapter = None

        # 内部状态
        self._state = GatewayState.IDLE
        self._running = False

        # 锁
        self._lock = threading.Lock()

    @property
    def state(self) -> GatewayState:
        """当前网关状态。"""
        with self._lock:
            return self._state

    @property
    def is_running(self) -> bool:
        """网关是否正在运行。"""
        return self._running

    @property
    def is_arm_connected(self) -> bool:
        """机械臂是否已连接。"""
        return self._arm_adapter is not None and self._arm_adapter.is_connected

    @property
    def arm_client_address(self) -> str | None:
        """获取已连接机械臂的地址。"""
        if self._arm_adapter:
            if hasattr(self._arm_adapter, "client_address"):
                return self._arm_adapter.client_address
            if hasattr(self._arm_adapter, "port"):
                return self._arm_adapter.port
        return None

    @property
    def tc3720_status(self) -> TC3720Status:
        """3720 设备状态。"""
        if self._tc3720_adapter:
            return self._tc3720_adapter.status
        return TC3720Status.OFFLINE

    def _set_state(self, new_state: GatewayState) -> None:
        """更新网关状态并触发回调（线程安全）。"""
        with self._lock:
            if self._state == new_state:
                return
            self._state = new_state

        logger.info("网关状态变化: %s", new_state.value)
        if self._on_state_changed:
            self._on_state_changed(new_state)

    def _create_record(self, direction: str, raw_data: str) -> TransferRecord:
        """创建中转记录。"""
        return TransferRecord(
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
            direction=direction,
            raw_data=raw_data,
            size=len(raw_data),
        )

    def start(self) -> bool:
        """启动网关服务。

        Returns:
            启动是否成功。
        """
        if self._running:
            logger.warning("网关已在运行")
            return True

        logger.info("启动透明中转网关...")
        self._running = True

        try:
            # 初始化机械臂适配器（串口模式）
            if self._config.arm_mode == "serial":
                from adapters.serial_arm_adapter import SerialArmAdapter

                logger.info("初始化串口适配器: %s @ %d",
                          self._config.arm_serial_port,
                          self._config.arm_serial_baudrate)

                self._arm_adapter = SerialArmAdapter(
                    port=self._config.arm_serial_port,
                    baudrate=self._config.arm_serial_baudrate,
                    bytesize=self._config.arm_serial_bytesize,
                    stopbits=self._config.arm_serial_stopbits,
                    parity=self._config.arm_serial_parity,
                    on_connected=self._on_arm_connected_callback,
                    on_disconnected=self._on_arm_disconnected_callback,
                    on_data_received=self._on_arm_data_received,  # 透传模式：直接接收数据
                    on_error=self._on_arm_error,
                )
            else:
                # TCP 模式
                from adapters.arm_adapter import ArmAdapter

                logger.info("初始化 TCP 适配器: %s:%s", self._config.arm_mode, self._config.arm_port)
                self._arm_adapter = ArmAdapter(
                    host=self._config.arm_host,
                    port=self._config.arm_port,
                    mode=self._config.arm_mode,
                    target_host=self._config.arm_target_host,
                    target_port=self._config.arm_target_port,
                    reconnect_interval=self._config.arm_reconnect_interval,
                    on_connected=self._on_arm_connected_callback,
                    on_disconnected=self._on_arm_disconnected_callback,
                    on_data_received=self._on_arm_data_received,  # 透传模式
                    on_error=self._on_arm_error,
                )
        except Exception as e:
            logger.error("初始化机械臂适配器失败: %s", e)
            self._running = False
            raise

        try:
            # 初始化 3720 TCP 适配器
            from adapters.tc3720_tcp_adapter import TC3720TcpAdapter

            logger.info("初始化 3720 TCP 适配器: %s:%d",
                      self._config.tc3720_host,
                      self._config.tc3720_port)

            self._tc3720_adapter = TC3720TcpAdapter(
                host=self._config.tc3720_host,
                port=self._config.tc3720_port,
                on_status_changed=self._on_3720_status_changed_callback,
                on_data_received=self._on_tc3720_data_received,  # 透传模式
                on_error=self._on_3720_error,
            )
        except Exception as e:
            logger.error("初始化 3720 适配器失败: %s", e)
            self._running = False
            raise

        # 先连接 3720 设备（确保 3720 已连接后再启动机械臂监听）
        if not self._tc3720_adapter.connect():
            self._cleanup()
            return False

        # 启动机械臂监听（机械臂可能立即开始发送数据）
        if not self._arm_adapter.start():
            self._cleanup()
            return False

        self._set_state(GatewayState.IDLE)
        logger.info("透明中转网关已启动，数据将透传到 3720...")
        return True

    def stop(self) -> None:
        """停止网关服务。"""
        if not self._running:
            return

        logger.info("停止透明中转网关...")
        self._running = False
        self._set_state(GatewayState.IDLE)
        self._cleanup()
        logger.info("透明中转网关已停止")

    def _cleanup(self) -> None:
        """清理资源。"""
        if self._arm_adapter:
            self._arm_adapter.stop()
            self._arm_adapter = None

        if self._tc3720_adapter:
            self._tc3720_adapter.disconnect()
            self._tc3720_adapter = None

    def _on_arm_connected_callback(self, adapter) -> None:
        """机械臂连接回调。"""
        if hasattr(adapter, "port"):
            address = adapter.port
        elif hasattr(adapter, "client_address"):
            address = adapter.client_address
        else:
            address = "unknown"
        logger.info("机械臂已连接: %s", address)
        if self._on_arm_connected:
            self._on_arm_connected(True)

    def _on_arm_disconnected_callback(self, adapter) -> None:
        """机械臂断开连接回调。"""
        logger.info("机械臂已断开连接")
        if self._on_arm_connected:
            self._on_arm_connected(False)

    def _on_arm_error(self, error: str) -> None:
        """机械臂错误回调。"""
        logger.error("机械臂通信错误: %s", error)
        if self._on_error:
            self._on_error(ErrorCode.UNKNOWN, error)

    def _on_3720_status_changed_callback(self, status: TC3720Status) -> None:
        """3720 状态变化回调。"""
        logger.debug("3720 状态: %s", status.value)
        if self._on_3720_status_changed:
            self._on_3720_status_changed(status)

    def _on_3720_error(self, error: str) -> None:
        """3720 错误回调。"""
        logger.error("3720 通信错误: %s", error)
        if self._on_error:
            self._on_error(ErrorCode.TC3720_ERROR, error)

    def _on_arm_data_received(self, data: str) -> None:
        """机械臂数据接收回调（提取关键字段并透传到 3720）。

        Args:
            data: 从机械臂接收的原始数据。
        """
        if not data:
            return

        logger.info("收到机械臂数据 [%d 字节]: %r", len(data), data)

        # 记录原始数据
        record = self._create_record("arm_to_3720", data)
        if self._on_record:
            self._on_record(record)
        if self._on_raw_data:
            self._on_raw_data("arm_to_3720", data)

        # 提取关键字段 SendUart:Start
        if "SendUart:Start" in data:
            key_data = "SendUart:Start\r\n"
            logger.info("[ARM-RX] 检测到 SendUart:Start，准备转发到 3720...")

            # 等待 3720 连接后再发送
            wait_result = self._wait_for_tc3720_connected(timeout=10.0)

            if not wait_result:
                logger.warning("[ARM-RX] 3720 未连接，跳过发送")
                return

            # 连接成功，发送数据
            self._forward_to_tc3720(key_data)
            logger.info("[ARM-RX] 已转发 SendUart:Start 到 3720")

        elif "MAC:" in data or "W5500" in data or "Remote IP" in data:
            # 忽略配置信息，只记录日志
            logger.info("收到配置信息，等待 SendUart:Start...")
        else:
            # 其他数据透传
            logger.info("收到其他数据，等待 SendUart:Start...")

    def _wait_for_tc3720_connected(self, timeout: float = 5.0) -> bool:
        """等待 3720 连接成功。

        Args:
            timeout: 超时时间（秒）。

        Returns:
            是否连接成功。
        """
        import time
        start_time = time.time()
        last_log_time = 0  # 控制日志频率

        while time.time() - start_time < timeout:
            if self._tc3720_adapter and hasattr(self._tc3720_adapter, 'is_connected'):
                is_connected = self._tc3720_adapter.is_connected
                elapsed = time.time() - start_time

                # 每秒打印一次状态
                if elapsed - last_log_time >= 1.0:
                    status = self._tc3720_adapter.status
                    logger.info("等待 3720 连接... [%d秒] status=%s, is_connected=%s",
                              int(elapsed), status.value, is_connected)
                    last_log_time = elapsed

                if is_connected:
                    logger.info("3720 已连接，等待结束")
                    return True
            time.sleep(0.1)

        # 超时时打印详细状态
        if self._tc3720_adapter:
            status = self._tc3720_adapter.status
            is_connected = self._tc3720_adapter.is_connected if hasattr(self._tc3720_adapter, 'is_connected') else "N/A"
            logger.warning("等待 3720 连接超时 [%d秒] status=%s, is_connected=%s",
                         int(timeout), status.value, is_connected)

        return False

    def _forward_to_tc3720(self, data: str) -> None:
        """转发数据到 3720。

        Args:
            data: 要发送的数据。
        """
        if self._tc3720_adapter is None:
            logger.error("[ARM-RX] 3720 适配器未初始化")
            return

        if not self._tc3720_adapter.is_connected:
            logger.warning("[ARM-RX] 3720 未连接，发送失败")
            return

        success = self._tc3720_adapter.send_raw(data)
        if success:
            logger.debug("已转发数据到 3720 [%d 字节]", len(data))
        else:
            logger.error("转发数据到 3720 失败")

    def _on_tc3720_data_received(self, data: str) -> None:
        """3720 数据接收回调（透传到机械臂）。

        Args:
            data: 从 3720 接收的原始数据。
        """
        if not data:
            return

        logger.info("收到 3720 数据 [%d 字节]: %r", len(data), data)

        # 记录并触发回调
        record = self._create_record("3720_to_arm", data)
        if self._on_record:
            self._on_record(record)
        if self._on_raw_data:
            self._on_raw_data("3720_to_arm", data)

        # 透传到机械臂
        self._forward_to_arm(data)

    def _forward_to_arm(self, data: str) -> None:
        """转发数据到机械臂。

        Args:
            data: 要发送的数据。
        """
        if self._arm_adapter and hasattr(self._arm_adapter, 'send_raw'):
            success = self._arm_adapter.send_raw(data)
            if success:
                logger.info("已透传到机械臂 [%d 字节]: %r", len(data), data)
            else:
                logger.warning("透传到机械臂失败")
        else:
            logger.warning("机械臂未连接，无法透传")


# 保持向后兼容
SignalGateway = PassthroughGateway
