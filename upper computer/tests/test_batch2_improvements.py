"""第二批改进回归测试。

覆盖以下改进：
1. 网关分帧缓冲的粘包/分包处理（此前测试缺口：每 chunk 都是完整帧，
   没有"一帧跨多 chunk"与"单 chunk 多帧"的用例）
2. gateway.on_start_test 改投递 _test_queue（修复前直接同步调用
   _handle_start_test，与工作线程并发共享会话状态且阻塞调用线程）
3. config.py 校验逻辑（此前仅 1 个用例覆盖）
"""

import time

import pytest
from config import get_configured_dut_indices, get_gateway_config, load_config
from router.gateway import GatewayConfig, PassthroughGateway


def _make_running_gateway(test_timeout: float = 5.0) -> PassthroughGateway:
    """构造标记为运行中的网关（不启动真实工作线程）。"""
    gateway = PassthroughGateway(config=GatewayConfig(test_timeout=test_timeout))
    gateway._running = True
    return gateway


class TestArmDataFraming:
    """网关分帧缓冲的粘包/分包处理。"""

    def test_single_frame_split_across_chunks(self):
        """一帧跨多 chunk（逐字符投喂）应正确重组为完整帧。"""
        gateway = _make_running_gateway()

        for char in "@START_TEST 00 10000000+":
            gateway._on_arm_data_received(char)

        assert gateway._test_queue.qsize() == 1
        assert gateway._test_queue.get_nowait() == {
            "group": "00",
            "bitmask": "10000000",
        }

    def test_multiple_frames_in_single_chunk(self):
        """单 chunk 含多帧（粘包）应逐帧解析且顺序不变。"""
        gateway = _make_running_gateway()

        gateway._on_arm_data_received(
            "@START_TEST 00 10000000+@START_TEST 00 01000000+"
        )

        assert gateway._test_queue.qsize() == 2
        assert gateway._test_queue.get_nowait()["bitmask"] == "10000000"
        assert gateway._test_queue.get_nowait()["bitmask"] == "01000000"

    def test_incomplete_frame_kept_in_buffer_until_complete(self):
        """半帧应暂存缓冲区，补齐后完成解析。"""
        gateway = _make_running_gateway()

        gateway._on_arm_data_received("@START_TEST 00 100")
        assert gateway._test_queue.qsize() == 0, "半帧不应被解析"

        gateway._on_arm_data_received("00000+")
        assert gateway._test_queue.qsize() == 1

    def test_garbage_before_frame_is_skipped(self):
        """帧前噪声字节（如上电噪声）应被跳过，不影响后续帧解析。"""
        gateway = _make_running_gateway()

        gateway._on_arm_data_received("\x00\x00noise@START_TEST 00 10000000+")

        assert gateway._test_queue.qsize() == 1

    def test_frame_split_with_trailing_garbage(self):
        """帧 + 尾部半帧混合：完整帧解析，剩余部分留在缓冲区。"""
        gateway = _make_running_gateway()

        gateway._on_arm_data_received("@START_TEST 00 10000000+@START_TE")

        assert gateway._test_queue.qsize() == 1
        assert gateway._arm_buffer == "@START_TE"


class TestOnStartTestQueued:
    """on_start_test 投递队列而非同步执行。"""

    def test_on_start_test_enqueues_without_blocking(self):
        """调用应立即返回并入队（修复前同步执行会阻塞最长 2×timeout）。"""
        gateway = _make_running_gateway(test_timeout=5.0)

        start = time.time()
        gateway.on_start_test("00", "10000000")
        elapsed = time.time() - start

        assert elapsed < 0.2, f"on_start_test 被阻塞 {elapsed:.2f}s"
        assert gateway._test_queue.qsize() == 1
        assert gateway._test_queue.get_nowait() == {
            "group": "00",
            "bitmask": "10000000",
        }

    def test_on_start_test_ignored_when_not_running(self):
        """网关未运行时应忽略（不入队、不抛异常）。"""
        gateway = PassthroughGateway()

        gateway.on_start_test("00", "10000000")

        assert gateway._test_queue.qsize() == 0


class TestConfigValidation:
    """config.py 校验与回退逻辑。"""

    def test_invalid_arm_port_falls_back_to_default(self):
        """非法端口（越界/非整数）回退默认值 8080。"""
        cfg = {"gateway": {"arm_mode": "tcp_server", "arm_port": 99999}}
        assert get_gateway_config(cfg).arm_port == 8080

        cfg = {"gateway": {"arm_mode": "tcp_server", "arm_port": "8080"}}
        assert get_gateway_config(cfg).arm_port == 8080

    def test_invalid_test_timeout_falls_back_to_default(self):
        """非法超时（负数/非数值）回退默认值 30.0。"""
        cfg = {"gateway": {"arm_mode": "tcp_server", "test_timeout": -1}}
        assert get_gateway_config(cfg).test_timeout == 30.0

        cfg = {"gateway": {"arm_mode": "tcp_server", "test_timeout": "abc"}}
        assert get_gateway_config(cfg).test_timeout == 30.0

    def test_missing_arm_mode_raises_value_error(self):
        """arm_mode 缺失应抛 ValueError（必填项）。"""
        with pytest.raises(ValueError, match="arm_mode"):
            get_gateway_config({"gateway": {}})

    def test_serial_mode_requires_port_and_baudrate(self):
        """串口模式缺少串口名或波特率应抛 ValueError。"""
        with pytest.raises(ValueError, match="arm_serial_port"):
            get_gateway_config({"gateway": {"arm_mode": "serial"}})

        with pytest.raises(ValueError, match="arm_serial_baudrate"):
            get_gateway_config(
                {"gateway": {"arm_mode": "serial", "arm_serial_port": "COM3"}}
            )

    def test_load_config_missing_file_returns_empty(self, tmp_path):
        """配置文件不存在时返回空字典。"""
        assert load_config(str(tmp_path / "nonexistent.json")) == {}

    def test_load_config_broken_json_returns_empty(self, tmp_path):
        """JSON 损坏时返回空字典而非抛异常。"""
        broken = tmp_path / "broken.json"
        broken.write_text("{not valid json", encoding="utf-8")

        assert load_config(str(broken)) == {}

    def test_get_configured_dut_indices_skips_empty_ip(self):
        """IP 为空或纯空白的 DUT 应被跳过。"""
        cfg = {
            "devices": {
                "dut1": {"ip": "192.168.1.101"},
                "dut2": {"ip": ""},
                "dut3": {"ip": "   "},
                "dut5": {"ip": "192.168.1.105"},
            }
        }

        assert get_configured_dut_indices(cfg) == [1, 5]
