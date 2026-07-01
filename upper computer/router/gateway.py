"""
信号路由层 - 核心中转网关。

实现机械臂与 3720 芯片测试仪之间的全自动信号透传。
使用 threading + Queue 架构，与 PyQt5 原生集成。
事件驱动架构，零人工干预。
"""

import logging
import queue
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Callable

from adapters import ArmAdapter, TC3720Adapter, TC3720Status

logger = logging.getLogger(__name__)


class GatewayState(Enum):
    """网关状态枚举。"""

    IDLE = "idle"  # 空闲监听
    RECEIVED_START = "received_start"  # 收到 START_TEST
    FORWARDED_3720 = "forwarded_3720"  # 已转发 3720
    WAITING_RESULT = "waiting_result"  # 等待 3720 结果
    AUTO_REPLY = "auto_reply"  # 已自动回传
    ERROR = "error"  # 异常状态


class ErrorCode(Enum):
    """网关错误码定义。"""

    NONE = "0000"  # 无错误
    TIMEOUT_ARM = "E001"  # 机械臂通信超时
    TIMEOUT_3720 = "E002"  # 3720 测试超时
    ARM_DISCONNECTED = "E003"  # 机械臂断连
    TC3720_ERROR = "E004"  # 3720 设备错误
    PROTOCOL_ERROR = "E005"  # 协议解析错误
    UNKNOWN = "EEEE"  # 未知错误


@dataclass
class TransferRecord:
    """中转记录。"""

    timestamp: str
    state: GatewayState
    group: str
    bitmask: str
    error_codes: list[str] | None = None
    error_code: ErrorCode = ErrorCode.NONE
    error_message: str = ""
    duration_ms: int = 0


@dataclass
class GatewayConfig:
    """网关配置。"""

    arm_host: str = "0.0.0.0"
    arm_port: int = 8080
    tc3720_mode: str = "simulator"
    tc3720_host: str = "192.168.1.101"
    tc3720_port: int = 9090
    test_timeout: float = 30.0
    enable_debug: bool = False


class SignalGateway:
    """全自动信号中转网关。

    核心职责：
    1. 监听机械臂的 START_TEST 请求（TCP Server 被动接收）
    2. 自动转发至 3720 测试仪
    3. 接收 3720 测试结果
    4. 自动回传机械臂（替换人工发送逻辑）
    5. 异常处理与状态重置

    业务流程（零人工干预）：
    START_TEST → 转发 3720 → 等待结果 → 自动回传 → 重置空闲

    使用 threading + Queue 架构，通过事件队列向 UI 线程推送更新。
    """

    def __init__(
        self,
        config: GatewayConfig | None = None,
        on_state_changed: Callable[[GatewayState], None] | None = None,
        on_arm_connected: Callable[[bool], None] | None = None,  # connected
        on_3720_status_changed: Callable[[TC3720Status], None] | None = None,
        on_record: Callable[[TransferRecord], None] | None = None,
        on_error: Callable[[ErrorCode, str], None] | None = None,
    ) -> None:
        """初始化信号网关。

        Args:
            config: 网关配置。
            on_state_changed: 状态变化回调。
            on_arm_connected: 机械臂连接状态变化回调。
            on_3720_status_changed: 3720 状态变化回调。
            on_record: 中转记录回调。
            on_error: 错误发生回调。
        """
        self._config = config or GatewayConfig()
        self._on_state_changed = on_state_changed
        self._on_arm_connected = on_arm_connected
        self._on_3720_status_changed = on_3720_status_changed
        self._on_record = on_record
        self._on_error = on_error

        # 设备适配器
        self._arm_adapter: ArmAdapter | None = None
        self._tc3720_adapter: TC3720Adapter | None = None

        # 内部状态
        self._state = GatewayState.IDLE
        self._running = False
        self._record_start_time: float = 0

        # 当前任务上下文（用于异常处理）
        self._current_group: str = ""
        self._current_bitmask: str = ""

        # 锁
        self._lock = threading.Lock()

        # 超时监控线程
        self._timeout_thread: threading.Thread | None = None
        self._timeout_event = threading.Event()

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
            return self._arm_adapter.client_address
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

    def _set_record_start(self) -> None:
        """记录任务开始时间。"""
        self._record_start_time = time.perf_counter()

    def _create_record(
        self,
        state: GatewayState,
        group: str,
        bitmask: str,
        error_codes: list[str] | None = None,
        error_code: ErrorCode = ErrorCode.NONE,
        error_message: str = "",
    ) -> TransferRecord:
        """创建中转记录。"""
        duration_ms = 0
        if self._record_start_time > 0:
            duration_ms = int(
                (time.perf_counter() - self._record_start_time) * 1000
            )

        return TransferRecord(
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
            state=state,
            group=group,
            bitmask=bitmask,
            error_codes=error_codes,
            error_code=error_code,
            error_message=error_message,
            duration_ms=duration_ms,
        )

    def start(self) -> bool:
        """启动网关服务。

        Returns:
            启动是否成功。
        """
        if self._running:
            logger.warning("网关已在运行")
            return True

        logger.info("启动信号中转网关...")
        self._running = True

        # 初始化机械臂适配器
        self._arm_adapter = ArmAdapter(
            host=self._config.arm_host,
            port=self._config.arm_port,
            on_connected=self._on_arm_connected_callback,
            on_disconnected=self._on_arm_disconnected_callback,
            on_start_test=self._on_start_test_received,
            on_error=self._on_arm_error,
        )

        # 初始化 3720 适配器
        self._tc3720_adapter = TC3720Adapter(
            mode=self._config.tc3720_mode,
            host=self._config.tc3720_host,
            port=self._config.tc3720_port,
            on_status_changed=self._on_3720_status_changed_callback,
            on_test_complete=self._on_3720_test_complete,
            on_error=self._on_3720_error,
        )

        # 启动机械臂监听
        if not self._arm_adapter.start():
            self._cleanup()
            return False

        # 连接 3720 设备
        if not self._tc3720_adapter.connect():
            self._cleanup()
            return False

        self._set_state(GatewayState.IDLE)
        logger.info("信号中转网关已启动，等待机械臂连接...")
        return True

    def stop(self) -> None:
        """停止网关服务。"""
        if not self._running:
            return

        logger.info("停止信号中转网关...")
        self._running = False

        # 停止超时监控
        self._timeout_event.set()
        if self._timeout_thread and self._timeout_thread.is_alive():
            self._timeout_thread.join(timeout=1.0)
            self._timeout_thread = None

        self._set_state(GatewayState.IDLE)
        self._cleanup()
        logger.info("信号中转网关已停止")

    def _cleanup(self) -> None:
        """清理资源。"""
        if self._arm_adapter:
            self._arm_adapter.stop()
            self._arm_adapter = None

        if self._tc3720_adapter:
            self._tc3720_adapter.disconnect()
            self._tc3720_adapter = None

    def _on_arm_connected_callback(self, adapter: ArmAdapter) -> None:
        """机械臂连接回调。"""
        logger.info("机械臂已连接: %s", adapter.client_address)
        if self._on_arm_connected:
            self._on_arm_connected(True)

    def _on_arm_disconnected_callback(self, adapter: ArmAdapter) -> None:
        """机械臂断开连接回调。"""
        logger.info("机械臂已断开连接")
        if self._on_arm_connected:
            self._on_arm_connected(False)

        # 如果正在处理任务，标记异常
        with self._lock:
            current_state = self._state

        if current_state not in (GatewayState.IDLE, GatewayState.ERROR):
            self._report_error(ErrorCode.ARM_DISCONNECTED, "机械臂在任务执行中断开连接")

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

    def _on_3720_test_complete(self, error_codes: list[str]) -> None:
        """3720 测试完成回调。"""
        logger.info("3720 测试完成，ErrorCodes: %s", error_codes)
        self._handle_test_complete(error_codes)

    def _on_3720_error(self, error: str) -> None:
        """3720 错误回调。"""
        logger.error("3720 通信错误: %s", error)
        if self._on_error:
            self._on_error(ErrorCode.TC3720_ERROR, error)

        # 通知机械臂异常
        self._send_abort_to_arm(ErrorCode.TC3720_ERROR, error)

    def on_start_test(self, group: str, bitmask: str) -> None:
        """收到 START_TEST 指令的回调（供外部调用）。

        Args:
            group: 组号。
            bitmask: DUT 位掩码。
        """
        if not self._running:
            logger.warning("网关未运行，忽略 START_TEST")
            return

        with self._lock:
            current_state = self._state

        if current_state != GatewayState.IDLE:
            logger.warning(
                "网关忙碌（状态: %s），忽略重复 START_TEST", current_state.value
            )
            return

        logger.info("收到 START_TEST - Group: %s, Bitmask: %s", group, bitmask)

        # 记录任务开始
        self._set_record_start()
        self._current_group = group
        self._current_bitmask = bitmask

        # 更新状态：已收到 START_TEST
        self._set_state(GatewayState.RECEIVED_START)

        # 自动转发至 3720
        self._forward_to_3720(group, bitmask)

    def _on_start_test_received(self, group: str, bitmask: str) -> None:
        """收到 START_TEST 指令的回调（由适配器触发）。"""
        self.on_start_test(group, bitmask)

    def _forward_to_3720(self, group: str, bitmask: str) -> None:
        """转发测试请求至 3720。

        Args:
            group: 组号。
            bitmask: DUT 位掩码。
        """
        if not self._tc3720_adapter:
            self._report_error(ErrorCode.UNKNOWN, "3720 适配器未初始化")
            return

        # 更新状态：已转发 3720
        self._set_state(GatewayState.FORWARDED_3720)

        # 启动 3720 测试
        success = self._tc3720_adapter.start_test(
            group, bitmask, timeout=self._config.test_timeout
        )

        if not success:
            self._report_error(ErrorCode.TC3720_ERROR, "3720 测试启动失败")
            self._send_abort_to_arm(ErrorCode.TC3720_ERROR, "3720 测试启动失败")
            return

        # 更新状态：等待结果
        self._set_state(GatewayState.WAITING_RESULT)
        logger.info("等待 3720 测试结果，超时时间: %.1f秒", self._config.test_timeout)

        # 启动超时监控线程
        self._start_timeout_monitor()

    def _start_timeout_monitor(self) -> None:
        """启动超时监控线程。"""
        self._timeout_event.clear()

        self._timeout_thread = threading.Thread(
            target=self._timeout_monitor_loop,
            name="Gateway-TimeoutMonitor",
            daemon=True,
        )
        self._timeout_thread.start()

    def _timeout_monitor_loop(self) -> None:
        """超时监控循环（在线程中运行）。"""
        timeout = self._config.test_timeout
        interval = 0.5  # 检查间隔
        elapsed = 0.0

        while elapsed < timeout:
            # 检查停止事件
            if self._timeout_event.is_set():
                return

            # 等待
            time.sleep(interval)
            elapsed += interval

            # 检查是否仍在等待结果
            with self._lock:
                current_state = self._state

            if current_state == GatewayState.WAITING_RESULT:
                continue
            elif current_state in (GatewayState.IDLE, GatewayState.AUTO_REPLY):
                # 正常完成
                return
            else:
                # 其他状态
                return

        # 超时
        if self._running:
            logger.error("3720 测试超时")
            tc3720_adapter = None
            with self._lock:
                current_state = self._state
                if current_state == GatewayState.WAITING_RESULT:
                    # 在锁内获取适配器引用，避免竞态条件
                    tc3720_adapter = self._tc3720_adapter

            if tc3720_adapter:
                tc3720_adapter.abort_test()
            self._report_error(
                ErrorCode.TIMEOUT_3720, "3720 测试超时"
            )
            self._send_abort_to_arm(
                ErrorCode.TIMEOUT_3720, "3720 测试超时"
            )

    def _handle_test_complete(self, error_codes: list[str]) -> None:
        """处理 3720 测试完成。

        Args:
            error_codes: 错误码列表。
        """
        # 停止超时监控
        self._timeout_event.set()

        with self._lock:
            current_state = self._state

        if current_state != GatewayState.WAITING_RESULT:
            logger.warning(
                "状态异常（%s），忽略测试完成事件", current_state.value
            )
            return

        logger.info("处理测试完成，回传机械臂 - Group: %s", self._current_group)

        # 更新状态：自动回传
        self._set_state(GatewayState.AUTO_REPLY)

        # 自动回传机械臂
        if self._arm_adapter and self._arm_adapter.is_connected:
            success = self._arm_adapter.send_test_done(
                self._current_group, error_codes
            )

            if not success:
                self._report_error(
                    ErrorCode.UNKNOWN, "回传机械臂失败"
                )
        else:
            self._report_error(
                ErrorCode.ARM_DISCONNECTED, "机械臂未连接，无法回传"
            )

        # 记录完成
        record = self._create_record(
            state=GatewayState.AUTO_REPLY,
            group=self._current_group,
            bitmask=self._current_bitmask,
            error_codes=error_codes,
        )
        if self._on_record:
            self._on_record(record)

        # 重置为空闲状态
        self._reset_to_idle()

    def _send_abort_to_arm(
        self, error_code: ErrorCode, message: str
    ) -> None:
        """向机械臂发送异常中止信号。

        Args:
            error_code: 错误码。
            message: 错误消息。
        """
        logger.warning("发送异常中止信号 - %s: %s", error_code.value, message)

        if self._arm_adapter and self._arm_adapter.is_connected:
            self._arm_adapter.send_abort(error_code.value)

    def _report_error(self, error_code: ErrorCode, message: str) -> None:
        """报告错误。

        Args:
            error_code: 错误码。
            message: 错误消息。
        """
        logger.error("网关错误 [%s]: %s", error_code.value, message)

        # 记录错误
        record = self._create_record(
            state=GatewayState.ERROR,
            group=self._current_group,
            bitmask=self._current_bitmask,
            error_code=error_code,
            error_message=message,
        )
        if self._on_record:
            self._on_record(record)

        # 触发错误回调
        if self._on_error:
            self._on_error(error_code, message)

        # 更新状态
        self._set_state(GatewayState.ERROR)

    def _reset_to_idle(self) -> None:
        """重置为空闲状态。"""
        self._current_group = ""
        self._current_bitmask = ""

        # 短暂延迟后重置为空闲
        time.sleep(0.1)
        self._set_state(GatewayState.IDLE)

    def clear_alarm(self) -> None:
        """清除告警，重置网关状态。"""
        with self._lock:
            current_state = self._state

        if current_state == GatewayState.ERROR:
            self._reset_to_idle()
            logger.info("告警已清除")
