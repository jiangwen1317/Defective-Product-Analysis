"""
设备管理器 - 多 3720 测试仪并发管理。

根据 Bitmask 确定需要测试的 DUT，然后向对应的 3720 测试仪发送启动信号。
支持 8 个 DUT 并发测试（对应 8 台独立的 3720 测试仪）。

架构：
    Bitmask (e.g., "10100000")
         │
         ▼
    bitmask_to_duts() → [1, 3]
         │
         ▼
    DeviceManager.start_test(dut_indices)
         │
         ▼
    向每个设备发送 START 信号
"""

import logging
import threading
from dataclasses import dataclass
from typing import Callable

from adapters import TC3720Status, TC3720TcpAdapter

logger = logging.getLogger(__name__)


@dataclass
class TestResult:
    """单个 DUT 的测试结果。"""

    dut_index: int  # 1-8
    device_name: str
    ip: str
    port: int
    error_code: str  # 4位十六进制错误码
    success: bool


class DeviceManager:
    """多设备管理器。

    管理 8 个 DUT 对应的 3720 测试仪连接，支持并发测试。
    """

    # DUT 数量：协议级常量，表示机械臂通信协议支持的最大 DUT 数量
    # 实际运行的 DUT 数量由 config.json 中的 devices 配置决定
    DUT_COUNT: int = 8

    def __init__(
        self,
        devices_config: dict[str, dict],
        test_timeout: float = 30.0,
        on_device_status_changed: Callable[[int, TC3720Status], None] | None = None,
        on_test_result: Callable[[TestResult], None] | None = None,
        on_error: Callable[[int, str], None] | None = None,
    ) -> None:
        """初始化设备管理器。

        Args:
            devices_config: 设备配置字典，格式为：
                {
                    "dut1": {"ip": "192.168.1.101", "port": 9090, "name": "Board-1"},
                    ...
                }
            test_timeout: 测试超时时间（秒）。
            on_device_status_changed: 设备状态变化回调 (dut_index, status)。
            on_test_result: 测试完成回调 (TestResult)。
            on_error: 错误回调 (dut_index, error_msg)。
        """
        self._devices_config = devices_config
        self._test_timeout = test_timeout
        self._on_device_status_changed = on_device_status_changed
        self._on_test_result = on_test_result
        self._on_error = on_error

        # 设备适配器映射
        self._adapters: dict[int, TC3720TcpAdapter] = {}

        # 锁
        self._lock = threading.Lock()

        # 运行时状态
        self._running = False

    def start(self) -> bool:
        """启动设备管理器，初始化所有设备连接。

        Returns:
            启动是否成功。
        """
        if self._running:
            logger.warning("设备管理器已在运行")
            return True

        logger.info("启动设备管理器...")
        self._running = True

        # 初始化所有设备连接
        for dut_index in range(1, self.DUT_COUNT + 1):
            self._init_device(dut_index)

        logger.info("设备管理器已启动，共 %d 个设备", len(self._adapters))
        return True

    def stop(self) -> None:
        """停止设备管理器，断开所有连接。"""
        if not self._running:
            return

        logger.info("停止设备管理器...")
        self._running = False

        # 锁内只取快照，disconnect 在锁外执行：
        # disconnect 内部会 join 线程（最长数秒）并触发状态回调，
        # 持锁执行会长时间阻塞其它线程并有回调重入锁的风险
        with self._lock:
            adapters = dict(self._adapters)
            self._adapters.clear()

        for dut_index, adapter in adapters.items():
            try:
                adapter.disconnect()
            except Exception as e:
                logger.warning("断开 DUT#%d 连接时出错: %s", dut_index, e)

        logger.info("设备管理器已停止")

    def _init_device(self, dut_index: int) -> None:
        """初始化单个设备连接。

        Args:
            dut_index: DUT 编号 (1-8)。
        """
        key = f"dut{dut_index}"
        if key not in self._devices_config:
            logger.warning("DUT#%d 配置不存在，跳过", dut_index)
            return

        config = self._devices_config[key]

        # 如果没有配置 IP，跳过
        ip = config.get("ip", "")
        if not ip:
            logger.warning("DUT#%d IP 未配置，跳过", dut_index)
            return

        port = config.get("port", 9090)
        name = config.get("name", f"Board-{dut_index}")

        logger.info("初始化 DUT#%d: %s (%s:%d)", dut_index, name, ip, port)

        # 创建适配器（必须接线 on_error：测试超时仅通过 on_error 上报，
        # 不接线则超时结果永远传不到网关，网关只能等满 2×timeout）
        adapter = TC3720TcpAdapter(
            host=ip,
            port=port,
            reconnect_interval=5.0,
            on_status_changed=lambda s, di=dut_index: self._on_device_status(di, s),
            on_test_complete=lambda ec, di=dut_index, dn=name, ip_=ip, pt=port: self._on_device_test_complete(di, dn, ip_, pt, ec),
            on_error=lambda msg, di=dut_index: self._on_device_error(di, msg),
        )

        with self._lock:
            self._adapters[dut_index] = adapter

        # 启动连接
        adapter.connect()

    def _on_device_status(self, dut_index: int, status: TC3720Status) -> None:
        """设备状态变化回调。

        Args:
            dut_index: DUT 编号。
            status: 新状态。
        """
        logger.debug("DUT#%d 状态变化: %s", dut_index, status.value)

        if self._on_device_status_changed:
            self._on_device_status_changed(dut_index, status)

    def _on_device_test_complete(
        self,
        dut_index: int,
        device_name: str,
        ip: str,
        port: int,
        error_codes: list[str],
    ) -> None:
        """设备测试完成回调。

        Args:
            dut_index: DUT 编号。
            device_name: 设备名称。
            ip: 设备 IP。
            port: 设备端口。
            error_codes: 错误码列表。
        """
        logger.info("DUT#%d 测试完成: %s", dut_index, error_codes)

        # 取第一个错误码作为结果
        error_code = error_codes[0] if error_codes else "0000"

        # 构建结果
        result = TestResult(
            dut_index=dut_index,
            device_name=device_name,
            ip=ip,
            port=port,
            error_code=error_code.upper().zfill(4),
            success=True,
        )

        if self._on_test_result:
            self._on_test_result(result)

    def _on_device_error(self, dut_index: int, error_msg: str) -> None:
        """设备错误回调。

        Args:
            dut_index: DUT 编号。
            error_msg: 错误消息。
        """
        logger.error("DUT#%d 错误: %s", dut_index, error_msg)

        # 构建错误结果
        result = TestResult(
            dut_index=dut_index,
            device_name=self._get_device_name(dut_index),
            ip=self._get_device_ip(dut_index),
            port=self._get_device_port(dut_index),
            error_code="EEEE",  # 错误码
            success=False,
        )

        if self._on_test_result:
            self._on_test_result(result)

        if self._on_error:
            self._on_error(dut_index, error_msg)

    def _get_device_name(self, dut_index: int) -> str:
        """获取设备名称。"""
        key = f"dut{dut_index}"
        return self._devices_config.get(key, {}).get("name", f"Board-{dut_index}")

    def _get_device_ip(self, dut_index: int) -> str:
        """获取设备 IP。"""
        key = f"dut{dut_index}"
        return self._devices_config.get(key, {}).get("ip", "")

    def _get_device_port(self, dut_index: int) -> int:
        """获取设备端口。"""
        key = f"dut{dut_index}"
        return int(self._devices_config.get(key, {}).get("port", 9090))

    def get_adapter(self, dut_index: int) -> TC3720TcpAdapter | None:
        """获取指定 DUT 的适配器。

        Args:
            dut_index: DUT 编号 (1-8)。

        Returns:
            对应的 TC3720TcpAdapter 实例，不存在时返回 None。
        """
        with self._lock:
            return self._adapters.get(dut_index)

    def get_all_adapters(self) -> dict[int, TC3720TcpAdapter]:
        """获取所有设备适配器。

        Returns:
            {dut_index: adapter} 字典。
        """
        with self._lock:
            return self._adapters.copy()

    def start_test(self, dut_indices: list[int]) -> dict[int, bool]:
        """向多个 DUT 发送启动测试信号。

        Args:
            dut_indices: DUT 编号列表 (1-8)。

        Returns:
            {dut_index: success} 字典。
        """
        results: dict[int, bool] = {}

        for dut_index in dut_indices:
            adapter = self.get_adapter(dut_index)
            if not adapter:
                logger.error("DUT#%d 适配器不存在", dut_index)
                results[dut_index] = False
                continue

            if not adapter.is_connected:
                logger.error("DUT#%d 未连接", dut_index)
                results[dut_index] = False
                continue

            if adapter.is_testing:
                logger.warning("DUT#%d 正在测试中", dut_index)
                results[dut_index] = False
                continue

            # 发送 START 信号（trigger_test 内部设置待处理状态）
            success = adapter.trigger_test(timeout=self._test_timeout)
            results[dut_index] = success

            if success:
                logger.info("已向 DUT#%d 发送启动信号", dut_index)
            else:
                logger.error("向 DUT#%d 发送启动信号失败", dut_index)

        return results

    def get_status(self, dut_index: int) -> TC3720Status:
        """获取指定 DUT 的状态。

        Args:
            dut_index: DUT 编号 (1-8)。

        Returns:
            设备状态。
        """
        adapter = self.get_adapter(dut_index)
        if adapter:
            return adapter.status
        return TC3720Status.OFFLINE
