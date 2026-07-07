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
from protocol.arm_protocol import ArmProtocol

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
    # 测试配置
    test_timeout: float = 30.0
    enable_debug: bool = False
    # 多设备配置：DUT#1-8 → IP 映射
    devices_config: dict[str, dict] | None = None


class PassthroughGateway:
    """透明中转网关。

    协议处理模式：
    1. 接收机械臂的 @START_TEST 指令
    2. 解析 Bitmask，根据为 1 的位置找到对应 DUT 的 3720 IP
    3. 向对应的 3720 设备发送 START 信号
    4. 收集测试结果，组装 @TEST_DONE 返回给机械臂

    支持多设备：根据 Bitmask 中的 8 个位置，对应 8 个独立的 3720 测试仪。
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
        self._device_manager = None

        # 测试结果收集（等待所有设备返回结果）
        self._test_results: dict[int, str] = {}  # dut_index -> error_code
        self._test_lock = threading.Lock()

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
        """3720 设备状态（返回聚合状态：任一设备繁忙则繁忙）。"""
        if self._device_manager:
            # 检查所有设备，如果有正在测试的则返回 TESTING
            adapters = self._device_manager.get_all_adapters()
            for adapter in adapters.values():
                if adapter.is_testing:
                    return TC3720Status.TESTING
            # 如果有设备在线则返回 IDLE
            for adapter in adapters.values():
                if adapter.is_online:
                    return TC3720Status.IDLE
            return TC3720Status.OFFLINE
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

    def trigger_test(self) -> bool:
        """主动触发测试。

        向上位机发送 @TEST_DONE 命令，触发机械臂开始测试流程。
        机械臂收到后会发送 @START_TEST 指令，上位机随后处理测试请求。

        Returns:
            触发命令发送是否成功。
        """
        if not self._arm_adapter:
            logger.error("机械臂未连接，无法发送触发命令")
            return False

        if not self.is_arm_connected:
            logger.error("机械臂未连接，无法发送触发命令")
            return False

        # 构建触发命令
        trigger_cmd = ArmProtocol.build_trigger()

        # 发送触发命令
        if hasattr(self._arm_adapter, 'send_raw'):
            success = self._arm_adapter.send_raw(trigger_cmd)
            if success:
                logger.info("[ARM-TX] 已发送触发命令: %s", trigger_cmd)

                # 记录
                record = self._create_record("arm_to_3720", trigger_cmd)
                if self._on_record:
                    self._on_record(record)
                if self._on_raw_data:
                    self._on_raw_data("arm_to_3720", trigger_cmd)

                return True
            else:
                logger.error("[ARM-TX] 发送触发命令失败")
                return False
        else:
            logger.error("机械臂适配器不支持 send_raw 方法")
            return False

    def get_device_status_summary(self) -> dict[int, dict]:
        """获取所有设备的状态摘要。

        Returns:
            {dut_index: {"status": str, "ip": str, "online": bool}} 字典。
        """
        summary = {}

        if self._device_manager:
            adapters = self._device_manager.get_all_adapters()
            for dut_idx, adapter in adapters.items():
                summary[dut_idx] = {
                    "status": adapter.status.value,
                    "ip": adapter.host,
                    "online": adapter.is_online,
                    "testing": adapter.is_testing,
                }

        return summary

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
            # 初始化多设备管理器
            from router.device_manager import DeviceManager

            logger.info("初始化多设备管理器...")

            self._device_manager = DeviceManager(
                devices_config=self._config.devices_config or {},
                test_timeout=self._config.test_timeout,
                on_device_status_changed=self._on_device_status_changed_callback,
                on_test_result=self._on_device_test_result,
                on_error=self._on_device_error,
            )

            # 启动设备管理器（会初始化所有设备连接）
            if not self._device_manager.start():
                self._cleanup()
                return False

        except Exception as e:
            logger.error("初始化设备管理器失败: %s", e)
            self._running = False
            raise

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

        if self._device_manager:
            self._device_manager.stop()
            self._device_manager = None

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
        """机械臂数据接收回调（协议解析模式）。

        解析 @START_TEST 指令，向对应的 3720 设备发送启动信号，
        收集测试结果后组装 @TEST_DONE 返回给机械臂。

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

        # 尝试解析为协议指令
        result = ArmProtocol.parse_command(data)
        if result is None:
            logger.warning("[ARM-RX] 无法解析指令: %r", data)
            return

        cmd_type, params = result
        logger.info("[ARM-RX] 解析指令: %s, 参数: %s", cmd_type, params)

        if cmd_type == "START_TEST":
            self._handle_start_test(params)
        else:
            logger.warning("[ARM-RX] 不支持的指令类型: %s", cmd_type)

    def _handle_start_test(self, params: dict) -> None:
        """处理 START_TEST 指令。

        1. 解析 group 和 bitmask
        2. 根据 bitmask 确定要测试的 DUT 编号
        3. 向对应的 3720 设备发送 START 信号
        4. 等待所有测试完成
        5. 收集错误码并返回给机械臂

        Args:
            params: 解析后的参数字典，包含 group 和 bitmask。
        """
        group = params.get("group", "00")
        bitmask = params.get("bitmask", "")

        if not group or not bitmask:
            logger.error("[ARM-RX] START_TEST 参数不完整")
            return

        # 将 bitmask 转换为 DUT 编号列表
        dut_indices = ArmProtocol.bitmask_to_duts(bitmask)

        if not dut_indices:
            logger.warning("[ARM-RX] Bitmask 没有需要测试的 DUT: %s", bitmask)
            # 返回空的测试结果
            self._send_test_done_to_arm(group, ["0000"] * 8)
            return

        logger.info("[ARM-RX] 需要测试的 DUT: %s (Bitmask: %s)", dut_indices, bitmask)

        # 更新状态为测试中
        self._set_state(GatewayState.FORWARDING)

        # 重置测试结果
        with self._test_lock:
            self._test_results.clear()
            for dut_idx in dut_indices:
                self._test_results[dut_idx] = None

        # 检查设备管理器是否就绪
        if not self._device_manager:
            logger.error("[ARM-RX] 设备管理器未初始化")
            self._set_state(GatewayState.ERROR)
            self._send_error_to_arm("Device manager not initialized")
            return

        # 向对应的 3720 设备发送 START 信号
        results = self._device_manager.start_test(dut_indices)

        # 检查启动是否全部成功
        failed_duts = [dut for dut, success in results.items() if not success]
        if failed_duts:
            logger.error("[ARM-RX] 以下 DUT 启动失败: %s", failed_duts)
            # 标记失败的结果
            with self._test_lock:
                for dut_idx in failed_duts:
                    self._test_results[dut_idx] = "EEEE"

        # 等待所有测试完成
        timeout = self._config.test_timeout * 2  # 使用较长的超时时间
        start_time = time.time()
        check_interval = 0.1  # 每 100ms 检查一次

        while time.time() - start_time < timeout:
            with self._test_lock:
                # 检查是否所有 DUT 都返回了结果
                if all(code is not None for code in self._test_results.values()):
                    break
            time.sleep(check_interval)

        # 收集结果
        with self._test_lock:
            final_results = self._test_results.copy()

        # 检查超时未返回的 DUT
        pending = [dut for dut, code in final_results.items() if code is None]
        if pending:
            logger.warning("[ARM-RX] 以下 DUT 测试超时: %s", pending)
            for dut_idx in pending:
                final_results[dut_idx] = "EEEE"  # 超时错误码

        # 组装错误码列表（按 DUT #1-#8 顺序）
        error_codes = []
        for dut_idx in range(1, 9):
            error_codes.append(final_results.get(dut_idx, "EEEE"))

        logger.info("[ARM-RX] 测试完成，错误码: %s", error_codes)

        # 更新状态
        self._set_state(GatewayState.IDLE)

        # 发送 TEST_DONE 响应给机械臂
        self._send_test_done_to_arm(group, error_codes)

    def _on_device_test_result(self, result) -> None:
        """设备测试完成回调（收集结果）。

        Args:
            result: TestResult 对象，包含 dut_index 和 error_code。
        """
        logger.info("[3720-RX] DUT#%d 测试完成，错误码: %s",
                   result.dut_index, result.error_code)

        with self._test_lock:
            if result.dut_index in self._test_results:
                self._test_results[result.dut_index] = result.error_code

    def _on_device_error(self, dut_index: int, error_msg: str) -> None:
        """设备错误回调。

        Args:
            dut_index: DUT 编号。
            error_msg: 错误消息。
        """
        logger.error("[3720-ERR] DUT#%d 错误: %s", dut_index, error_msg)

        with self._test_lock:
            if dut_index in self._test_results:
                self._test_results[dut_index] = "EEEE"

    def _on_device_status_changed_callback(self, dut_index: int, status: TC3720Status) -> None:
        """设备状态变化回调（转发到 UI）。

        Args:
            dut_index: DUT 编号。
            status: 新状态。
        """
        logger.debug("DUT#%d 状态变化: %s", dut_index, status.value)

        if self._on_3720_status_changed:
            # 聚合状态：只要有设备在测试就返回 TESTING
            if status == TC3720Status.TESTING:
                self._on_3720_status_changed(TC3720Status.TESTING)
            elif status == TC3720Status.IDLE:
                # 只有当没有设备在测试时才返回 IDLE
                if self._device_manager and self._device_manager.is_all_idle():
                    self._on_3720_status_changed(TC3720Status.IDLE)
            else:
                self._on_3720_status_changed(status)

    def _send_test_done_to_arm(self, group: str, error_codes: list[str]) -> None:
        """发送 TEST_DONE 响应给机械臂。

        Args:
            group: 组号。
            error_codes: 8 个错误码列表。
        """
        if not self._arm_adapter:
            logger.error("[ARM-TX] 机械臂未连接，无法发送响应")
            return

        # 组装协议指令
        response = ArmProtocol.build_test_done(group, error_codes)

        # 发送响应
        if hasattr(self._arm_adapter, 'send_raw'):
            success = self._arm_adapter.send_raw(response)
            if success:
                logger.info("[ARM-TX] 已发送 TEST_DONE: %s", response)
            else:
                logger.error("[ARM-TX] 发送 TEST_DONE 失败")

        # 记录
        record = self._create_record("3720_to_arm", response)
        if self._on_record:
            self._on_record(record)
        if self._on_raw_data:
            self._on_raw_data("3720_to_arm", response)

    def _send_error_to_arm(self, error_msg: str) -> None:
        """发送错误信息给机械臂。

        Args:
            error_msg: 错误消息。
        """
        logger.error("[ARM-TX] 错误: %s", error_msg)
        # 可以发送一个错误码为 EEEE 的 TEST_DONE 表示失败


# 保持向后兼容
SignalGateway = PassthroughGateway
