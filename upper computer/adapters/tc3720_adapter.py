"""
3720 芯片测试仪设备适配器。

预留通信接口，当前阶段使用模拟信号。
支持 TCP/串口/IO 等多种物理层，待实际设备确认后实现。

使用 threading 实现，与 PyQt5 原生集成。
"""

import logging
import random
import threading
import time
from enum import Enum
from typing import Callable

logger = logging.getLogger(__name__)


class TC3720Status(Enum):
    """3720 设备状态枚举。"""

    OFFLINE = "offline"
    IDLE = "idle"
    TESTING = "testing"
    ERROR = "error"


class TC3720Adapter:
    """3720 芯片测试仪设备适配器（模拟实现）。

    当前阶段使用模拟信号，待实际设备确认后替换为真实实现。
    使用独立线程处理模拟测试，定时器回调通知结果。
    预留接口：
    - TCP 模式（待实现）
    - 串口模式（待实现）
    - IO 模式（待实现）
    """

    def __init__(
        self,
        mode: str = "simulator",  # simulator | tcp | serial | io
        host: str = "192.168.1.101",
        port: int = 9090,
        on_status_changed: Callable[[TC3720Status], None] | None = None,
        on_test_complete: Callable[[list[str]], None] | None = None,  # error_codes
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        """初始化 3720 适配器。

        Args:
            mode: 通信模式，simulator=模拟器，tcp/serial/io=待实现。
            host: TCP 模式下的设备地址（待实现）。
            port: TCP 模式下的设备端口（待实现）。
            on_status_changed: 状态变化回调。
            on_test_complete: 测试完成回调（返回错误码列表）。
            on_error: 错误发生回调。
        """
        self._mode = mode
        self._host = host
        self._port = port
        self._on_status_changed = on_status_changed
        self._on_test_complete = on_test_complete
        self._on_error = on_error

        # 内部状态
        self._status = TC3720Status.OFFLINE
        self._running = False
        self._test_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

        # 锁
        self._lock = threading.Lock()

    @property
    def mode(self) -> str:
        """通信模式。"""
        return self._mode

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
        """建立与 3720 设备的连接。

        Returns:
            连接是否成功。
        """
        with self._lock:
            if self._running:
                return True

        if self._mode == "simulator":
            # 模拟器模式：直接标记为在线
            with self._lock:
                self._running = True
            self._stop_event.clear()
            self._set_status(TC3720Status.IDLE)
            logger.info("3720 模拟器已连接")
            return True

        elif self._mode == "tcp":
            raise NotImplementedError("TCP 模式尚未实现，请联系开发者配置真实设备")

        elif self._mode == "serial":
            raise NotImplementedError("串口模式尚未实现，请联系开发者配置真实设备")

        elif self._mode == "io":
            raise NotImplementedError("IO 模式尚未实现，请联系开发者配置真实设备")

        elif self._mode == "simulator":
            pass  # 模拟器模式由 start() 统一处理

        else:
            raise NotImplementedError(f"未知的通信模式: {self._mode}")

    def disconnect(self) -> None:
        """断开与 3720 设备的连接。"""
        with self._lock:
            self._running = False
        self._stop_event.set()

        # 等待测试线程结束
        if self._test_thread and self._test_thread.is_alive():
            self._test_thread.join(timeout=1.0)
            self._test_thread = None

        self._set_status(TC3720Status.OFFLINE)
        logger.info("3720 设备已断开连接")

    def start_test(
        self, group: str, bitmask: str, timeout: float = 30.0
    ) -> bool:
        """向 3720 发送启动测试指令。

        Args:
            group: 组号。
            bitmask: DUT 位掩码（需要测试哪些 DUT）。
            timeout: 测试超时时间（秒）。

        Returns:
            启动是否成功（不表示测试是否成功）。
        """
        with self._lock:
            if not self._running:
                logger.error("3720 未连接，无法启动测试")
                return False

            if self._status == TC3720Status.TESTING:
                logger.warning("3720 正在测试中，忽略重复请求")
                return False

        logger.info("向 3720 发送启动测试 - Group: %s, Bitmask: %s", group, bitmask)

        if self._mode == "simulator":
            return self._start_simulate_test(group, bitmask, timeout)
        else:
            # connect() 已在启动时抛出 NotImplementedError，这里不会到达
            raise NotImplementedError(f"模式 {self._mode} 未实现测试启动")

    def abort_test(self) -> bool:
        """中止当前测试。

        Returns:
            中止是否成功。
        """
        # 发出停止信号
        self._stop_event.set()

        # 等待测试线程结束
        if self._test_thread and self._test_thread.is_alive():
            self._test_thread.join(timeout=0.5)
            self._test_thread = None

        self._stop_event.clear()
        self._set_status(TC3720Status.IDLE)
        logger.info("已中止 3720 测试")
        return True

    def _start_simulate_test(
        self, group: str, bitmask: str, timeout: float
    ) -> bool:
        """启动模拟测试。

        Args:
            group: 组号。
            bitmask: DUT 位掩码。
            timeout: 超时时间。

        Returns:
            启动是否成功。
        """
        self._set_status(TC3720Status.TESTING)

        # 重置停止事件
        self._stop_event.clear()

        # 创建测试线程
        self._test_thread = threading.Thread(
            target=self._simulate_test_task,
            args=(group, bitmask, timeout),
            name="TC3720-Simulator",
            daemon=True,
        )
        self._test_thread.start()

        return True

    def _simulate_test_task(
        self, group: str, bitmask: str, timeout: float
    ) -> None:
        """模拟测试任务（在线程中运行）。

        模拟过程：
        1. 根据 bitmask 确定需要测试的 DUT
        2. 等待模拟测试时间（1-3秒）
        3. 检查停止事件
        4. 随机生成错误码（90% 通过率，10% 随机错误）
        5. 触发完成回调

        Args:
            group: 组号。
            bitmask: DUT 位掩码。
            timeout: 超时时间。
        """
        try:
            # 模拟测试时间（1-3秒随机）
            test_duration = random.uniform(1.0, 3.0)
            elapsed = 0.0
            interval = 0.1

            while elapsed < test_duration:
                # 检查停止事件
                if self._stop_event.is_set():
                    logger.info("模拟测试被中止")
                    self._set_status(TC3720Status.IDLE)
                    return

                time.sleep(interval)
                elapsed += interval

            # 检查停止事件
            if self._stop_event.is_set():
                logger.info("模拟测试被中止")
                self._set_status(TC3720Status.IDLE)
                return

            # 生成错误码
            error_codes: list[str] = []
            for bit in bitmask:
                if bit == "1":
                    # 需要测试的 DUT
                    if random.random() < 0.9:
                        # 90% 通过率：0000
                        error_codes.append("0000")
                    else:
                        # 10% 随机错误
                        error_code = f"{random.randint(1, 9):X}{random.randint(0, 15):X}{random.randint(0, 15):X}{random.randint(1, 15):X}"
                        error_codes.append(error_code)
                else:
                    # 不测试的 DUT：0000
                    error_codes.append("0000")

            self._set_status(TC3720Status.IDLE)

            logger.info(
                "3720 模拟测试完成 - Group: %s, ErrorCodes: %s",
                group,
                error_codes,
            )

            if self._on_test_complete:
                self._on_test_complete(error_codes)

        except Exception as e:
            logger.error("模拟测试异常: %s", e)
            self._set_status(TC3720Status.ERROR)
            if self._on_error:
                self._on_error(f"测试异常: {e}")
