"""
ArmProtocol 协议处理器单元测试。
"""

import pytest

from protocol.arm_protocol import ArmProtocol


class TestArmProtocolBitmask:
    """Bitmask 转换测试。"""

    def test_bitmask_to_duts_all_ones(self):
        """测试全 1 的 bitmask。"""
        result = ArmProtocol.bitmask_to_duts("11111111")
        assert result == [1, 2, 3, 4, 5, 6, 7, 8]

    def test_bitmask_to_duts_all_zeros(self):
        """测试全 0 的 bitmask。"""
        result = ArmProtocol.bitmask_to_duts("00000000")
        assert result == []

    def test_bitmask_to_duts_first_two(self):
        """测试前两位为 1。"""
        result = ArmProtocol.bitmask_to_duts("11000000")
        assert result == [1, 2]

    def test_bitmask_to_duts_alternate(self):
        """测试交替位。"""
        result = ArmProtocol.bitmask_to_duts("10101010")
        assert result == [1, 3, 5, 7]

    def test_bitmask_to_duts_invalid_format(self):
        """测试无效格式（应返回空列表）。"""
        assert ArmProtocol.bitmask_to_duts("invalid") == []
        assert ArmProtocol.bitmask_to_duts("12345678") == []
        assert ArmProtocol.bitmask_to_duts("") == []

    def test_bitmask_to_duts_wrong_length(self):
        """测试错误长度。"""
        assert ArmProtocol.bitmask_to_duts("111") == []
        assert ArmProtocol.bitmask_to_duts("111111111") == []


class TestArmProtocolDutsToBitmask:
    """DUT 列表转 Bitmask 测试。"""

    def test_duts_to_bitmask_all(self):
        """测试全部 DUT。"""
        result = ArmProtocol.duts_to_bitmask([1, 2, 3, 4, 5, 6, 7, 8])
        assert result == "11111111"

    def test_duts_to_bitmask_none(self):
        """测试空列表。"""
        result = ArmProtocol.duts_to_bitmask([])
        assert result == "00000000"

    def test_duts_to_bitmask_first_two(self):
        """测试前两个 DUT。"""
        result = ArmProtocol.duts_to_bitmask([1, 2])
        assert result == "11000000"

    def test_duts_to_bitmask_invalid_dut(self):
        """测试无效 DUT 编号（应抛出异常）。"""
        with pytest.raises(ValueError, match="DUT 编号必须在 1-8 范围内"):
            ArmProtocol.duts_to_bitmask([0])
        with pytest.raises(ValueError, match="DUT 编号必须在 1-8 范围内"):
            ArmProtocol.duts_to_bitmask([9])
        with pytest.raises(ValueError, match="DUT 编号必须在 1-8 范围内"):
            ArmProtocol.duts_to_bitmask([1, 10])


class TestArmProtocolBuildTestDone:
    """构建 TEST_DONE 指令测试。"""

    def test_build_test_done_valid(self):
        """测试有效输入。"""
        error_codes = ["1901", "1902", "1903", "1904", "0151", "0401", "0152", "0904"]
        result = ArmProtocol.build_test_done("00", error_codes)
        assert result == "@TEST_DONE 00 1901 1902 1903 1904 0151 0401 0152 0904+"

    def test_build_test_done_lowercase(self):
        """测试小写字母（应自动转大写）。"""
        error_codes = ["1901", "ABCD", "1903", "1904", "0151", "0401", "0152", "0904"]
        result = ArmProtocol.build_test_done("00", error_codes)
        assert "ABCD" in result

    def test_build_test_done_padding(self):
        """测试不足4位的错误码自动补零。"""
        error_codes = ["0001", "0022", "0333", "4444", "5555", "6666", "7777", "8888"]
        result = ArmProtocol.build_test_done("00", error_codes)
        assert "0001" in result
        assert "0022" in result
        assert "0333" in result

    def test_build_test_done_wrong_count(self):
        """测试错误码数量不足。"""
        with pytest.raises(ValueError, match="error_codes 必须包含 8 个元素"):
            ArmProtocol.build_test_done("00", ["1901"] * 7)

    def test_build_test_done_invalid_code(self):
        """测试无效错误码。"""
        error_codes = ["1901", "invalid", "1903", "1904", "0151", "0401", "0152", "0904"]
        with pytest.raises(ValueError, match="EC2 必须是4位十六进制数"):
            ArmProtocol.build_test_done("00", error_codes)


class TestArmProtocolParseCommand:
    """解析指令测试。"""

    def test_parse_command_valid_start_test(self):
        """测试解析有效的 START_TEST。"""
        result = ArmProtocol.parse_command("@START_TEST 00 11111111+")
        assert result == ("START_TEST", {"group": "00", "bitmask": "11111111"})

    def test_parse_command_valid_test_done(self):
        """测试解析有效的 TEST_DONE。"""
        raw = "@TEST_DONE 00 1901 1902 1903 1904 0151 0401 0152 0904+"
        result = ArmProtocol.parse_command(raw)
        assert result is not None
        cmd_type, params = result
        assert cmd_type == "TEST_DONE"
        assert params["group"] == "00"
        assert len(params["error_codes"]) == 8

    def test_parse_command_with_whitespace(self):
        """测试带空白的指令。"""
        result = ArmProtocol.parse_command("  @START_TEST 00 11111111+  ")
        assert result == ("START_TEST", {"group": "00", "bitmask": "11111111"})

    def test_parse_command_with_noise_prefix(self):
        """测试带前缀噪声。"""
        result = ArmProtocol.parse_command("\x00\x00@START_TEST 00 11111111+")
        assert result == ("START_TEST", {"group": "00", "bitmask": "11111111"})

    def test_parse_command_with_newline(self):
        """测试带换行符。"""
        result = ArmProtocol.parse_command("@START_TEST 00 11111111+\n")
        assert result == ("START_TEST", {"group": "00", "bitmask": "11111111"})

    def test_parse_command_missing_at(self):
        """测试缺少 @ 前缀。"""
        result = ArmProtocol.parse_command("START_TEST 00 11111111+")
        assert result is None

    def test_parse_command_missing_terminator(self):
        """测试缺少 + 结尾。"""
        result = ArmProtocol.parse_command("@START_TEST 00 11111111")
        assert result is None

    def test_parse_command_empty(self):
        """测试空字符串。"""
        assert ArmProtocol.parse_command("") is None
        assert ArmProtocol.parse_command("   ") is None
        assert ArmProtocol.parse_command(None) is None

    def test_parse_command_unknown_command(self):
        """测试未知指令。"""
        result = ArmProtocol.parse_command("@UNKNOWN 00 11111111+")
        assert result is None

    def test_parse_command_invalid_group(self):
        """测试无效组号。"""
        result = ArmProtocol.parse_command("@START_TEST 01 11111111+")
        assert result is None

    def test_parse_command_invalid_bitmask(self):
        """测试无效 bitmask。"""
        result = ArmProtocol.parse_command("@START_TEST 00 invalid+")
        assert result is None


class TestArmProtocolBuildTrigger:
    """构建触发命令测试。"""

    def test_build_trigger_default(self):
        """测试默认触发（板子 1、2）。"""
        result = ArmProtocol.build_trigger()
        assert "@TEST_DONE 00" in result
        assert result.endswith("+")
        # 前两个应该是 0001
        parts = result.split()
        assert parts[2] == "0001"  # EC1
        assert parts[3] == "0001"  # EC2
        # 后面的应该是 0000
        assert parts[4] == "0000"  # EC3

    def test_build_trigger_single_board(self):
        """测试触发单个板子。"""
        result = ArmProtocol.build_trigger([1])
        parts = result.split()
        assert parts[2] == "0001"  # EC1
        assert parts[3] == "0000"  # EC2

    def test_build_trigger_multiple_boards(self):
        """测试触发多个板子。"""
        result = ArmProtocol.build_trigger([1, 3, 5])
        parts = result.split()
        assert parts[2] == "0001"  # EC1
        assert parts[3] == "0000"  # EC2
        assert parts[4] == "0001"  # EC3
        assert parts[5] == "0000"  # EC4
        assert parts[6] == "0001"  # EC5
