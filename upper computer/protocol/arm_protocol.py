"""
机械臂通讯协议处理器。

根据《机械臂测试通信协议规范》实现指令的构建与解析。
指令格式：以 '@' 开头，以 '+' 结尾。
"""

import logging
import re
from typing import Final

logger = logging.getLogger(__name__)


class ArmProtocol:
    """机械臂通讯协议处理器。

    负责指令的构建、验证与解析。

    通信流程（主动模式）：
    1. 上位机发送 @TEST_DONE 00 <EC1> <EC2> ... <EC8>+ 触发机械臂
       - EC 字段为 "0001" 表示该位置有数据需要测试，"0000" 表示不测试
    2. 机械臂收到后，发送 @START_TEST 00 <bitmask>+ 启动测试
    3. 3720 测试完成后返回 ErrorCode: XXXX
    4. 上位机组装 @TEST_DONE 返回给机械臂
    """

    # 指令标识
    CMD_START: Final[str] = "@START_TEST"
    CMD_DONE: Final[str] = "@TEST_DONE"
    CMD_TERMINATOR: Final[str] = "+"

    # DUT 数量
    DUT_COUNT: Final[int] = 8

    # 错误码格式：4位十六进制（大写 A-F）
    ERROR_CODE_PATTERN: Final[str] = r"^[0-9A-F]{4}$"

    @classmethod
    def build_start_test(cls, group: str, bitmask: str) -> str:
        """构建 START_TEST 指令。

        ⚠️ 警告：此方法仅在被动监听模式下使用。
        主动触发模式下，上位机不发送此指令，而是由机械臂自动发送。

        Args:
            group: 组号，2位十六进制数（如 '00'）。
            bitmask: 8位二进制字符串，从左至右对应 DUT #1 至 DUT #8。
                    '1' 表示测试该 DUT，'0' 表示不测试。

        Returns:
            完整的指令字符串，格式为：@START_TEST <Group> <Bitmask>+

        Raises:
            ValueError: 参数格式不正确时抛出。

        Example:
            >>> ArmProtocol.build_start_test("00", "11111111")
            '@START_TEST 00 11111111+'
            >>> ArmProtocol.build_start_test("00", "10100000")
            '@START_TEST 00 10100000+'
        """
        # 验证 group（当前协议版本固定为 '00'）
        if not cls._validate_group(group):
            raise ValueError(f"Group 必须是 '00'（当前协议版本固定），当前值: {group}")

        # 验证 bitmask
        if not cls._validate_bitmask(bitmask):
            raise ValueError(
                f"Bitmask 必须是8位二进制字符串（仅含0/1），当前值: {bitmask}"
            )

        return f"{cls.CMD_START} {group} {bitmask}{cls.CMD_TERMINATOR}"

    @classmethod
    def build_test_done(cls, group: str, error_codes: list[str]) -> str:
        """构建 TEST_DONE 指令。

        Args:
            group: 组号，2位十六进制数（如 '00'）。
            error_codes: 8个错误码列表，每个错误码为4位十六进制数（大写）。
                        按顺序对应 DUT #1 至 DUT #8。
                        不足4位时前方补零（如 '0904' 而非 '904'）。

        Returns:
            完整的指令字符串，格式为：@TEST_DONE <Group> <EC1> <EC2> ... <EC8>+

        Raises:
            ValueError: 参数格式不正确时抛出。

        Example:
            >>> codes = ["1901", "1902", "1903", "1904", "0151", "0401", "0152", "0904"]
            >>> ArmProtocol.build_test_done("00", codes)
            '@TEST_DONE 00 1901 1902 1903 1904 0151 0401 0152 0904+'
        """
        # 验证 group（当前协议版本固定为 '00'）
        if not cls._validate_group(group):
            raise ValueError(f"Group 必须是 '00'（当前协议版本固定），当前值: {group}")

        # 验证 error_codes 数量
        if len(error_codes) != cls.DUT_COUNT:
            raise ValueError(
                f"error_codes 必须包含 {cls.DUT_COUNT} 个元素，当前数量: {len(error_codes)}"
            )

        # 验证并格式化每个错误码
        formatted_codes: list[str] = []
        for i, code in enumerate(error_codes, start=1):
            if not cls._validate_hex4(code):
                raise ValueError(
                    f"EC{i} 必须是4位十六进制数，当前值: {code}"
                )
            # 转为大写并确保4位（前方补零）
            formatted_codes.append(code.upper().zfill(4))

        return (
            f"{cls.CMD_DONE} {group} "
            + " ".join(formatted_codes)
            + cls.CMD_TERMINATOR
        )

    @classmethod
    def parse_command(cls, raw: str) -> tuple[str, dict] | None:
        """解析接收到的指令字符串。

        Args:
            raw: 原始指令字符串（可能包含首尾空白字符和换行符）。

        Returns:
            解析成功的指令类型（如 'START_TEST'、'TEST_DONE'），
            以及包含的参数字典。解析失败时返回 None。

        Example:
            >>> result = ArmProtocol.parse_command("@START_TEST 00 11111111+")
            >>> result[0]
            'START_TEST'
            >>> result[1]
            {'group': '00', 'bitmask': '11111111'}
        """
        if not raw:
            return None

        # 去除首尾空白字符（包括 \r, \n, 空格等）
        raw = raw.strip()

        if not raw:
            return None

        # 容错处理：跳过帧首前的异常字符（如 \x00）
        if not raw.startswith("@"):
            at_pos = raw.find("@")
            if at_pos > 0:
                logger.debug("跳过帧首前 %d 个异常字符: %r", at_pos, raw[:at_pos])
                raw = raw[at_pos:]
            elif at_pos == -1:
                logger.warning("指令格式错误：缺少帧首 '@' %r", raw)
                return None

        # 验证帧首尾标识
        if not raw.startswith("@") or not raw.endswith("+"):
            logger.warning("指令格式错误：缺少首尾标识 %s", raw)
            return None

        # 验证首字符后不能直接是空格（帧头后必须有内容）
        if len(raw) < 3 or raw[1] == " ":
            logger.warning("指令格式错误：帧首 '@' 后不能直接是空格")
            return None

        # 验证 '+' 后面不能有额外字符
        if raw.index("+") != len(raw) - 1:
            logger.warning("指令格式错误：结束符 '+' 后不能有额外字符")
            return None

        # 验证帧尾 '+' 前不能是空格
        if raw[-2] == " ":
            logger.warning("指令格式错误：结束符 '+' 前不能是空格")
            return None

        # 去除首尾标识后提取内容
        content = raw[1:-1]

        # 分割指令类型和参数（使用单个空格分隔）
        parts = content.split(" ")
        if not parts or not parts[0]:
            logger.warning("指令内容为空: %s", raw)
            return None

        # 验证各字段之间没有多余空格（不能有空字段）
        if any(not part for part in parts):
            logger.warning("指令中存在多余空格或连续空格: %s", raw)
            return None

        cmd = parts[0]

        if cmd == "START_TEST":
            return cls._parse_start_test(parts[1:])
        elif cmd == "TEST_DONE":
            return cls._parse_test_done(parts[1:])
        else:
            logger.warning("未知的指令类型: %s", cmd)
            return None

    @classmethod
    def _parse_start_test(cls, parts: list[str]) -> tuple[str, dict] | None:
        """解析 START_TEST 指令参数。"""
        if len(parts) < 2:
            logger.warning("START_TEST 指令参数不足")
            return None

        group = parts[0]
        bitmask = parts[1]

        if not cls._validate_group(group) or not cls._validate_bitmask(bitmask):
            logger.warning("START_TEST 指令参数格式错误: group=%s, bitmask=%s", group, bitmask)
            return None

        return ("START_TEST", {"group": group, "bitmask": bitmask})

    @classmethod
    def _parse_test_done(cls, parts: list[str]) -> tuple[str, dict] | None:
        """解析 TEST_DONE 指令参数。"""
        if len(parts) < 9:  # group + 8个 error_codes
            logger.warning("TEST_DONE 指令参数不足")
            return None

        group = parts[0]
        error_codes = parts[1:9]

        if not cls._validate_group(group):
            logger.warning("TEST_DONE 指令 group 格式错误: %s", group)
            return None

        for i, code in enumerate(error_codes, start=1):
            if not cls._validate_hex4(code):
                logger.warning("TEST_DONE 指令 EC%d 格式错误: %s", i, code)
                return None

        return (
            "TEST_DONE",
            {
                "group": group,
                "error_codes": [c.upper() for c in error_codes],
            },
        )

    @staticmethod
    def _validate_hex2(value: str) -> bool:
        """验证2位十六进制数（任意值）。"""
        return bool(re.fullmatch(r"^[0-9A-Fa-f]{2}$", value))

    @staticmethod
    def _validate_hex4(value: str) -> bool:
        """验证4位十六进制数（大写 A-F）。

        协议要求：必须是固定4位十六进制数，字母必须大写。
        """
        return bool(re.fullmatch(r"^[0-9A-F]{4}$", value))

    @staticmethod
    def _validate_group(value: str) -> bool:
        """验证组号字段。

        当前协议版本中 Group 位置固定为 "00"，若未来需支持多组并行测试，
        将通过协议版本升级重新定义该字段语义。
        """
        return value == "00"

    @staticmethod
    def _validate_bitmask(value: str) -> bool:
        """验证8位二进制字符串（仅含0/1）。"""
        return bool(re.fullmatch(r"^[01]{8}$", value))

    @classmethod
    def bitmask_to_duts(cls, bitmask: str) -> list[int]:
        """将 Bitmask 转换为 DUT 编号列表。

        Args:
            bitmask: 8位二进制字符串（'1'=测试，'0'=不测试）。

        Returns:
            需要测试的 DUT 编号列表（如 [1, 3] 表示测试 DUT #1 和 DUT #3）。

        Example:
            >>> ArmProtocol.bitmask_to_duts("10100000")
            [1, 3]
            >>> ArmProtocol.bitmask_to_duts("11111111")
            [1, 2, 3, 4, 5, 6, 7, 8]
        """
        if not cls._validate_bitmask(bitmask):
            logger.warning("Bitmask 格式错误，返回空列表: %s", bitmask)
            return []

        return [i for i, bit in enumerate(bitmask, start=1) if bit == "1"]

    @classmethod
    def duts_to_bitmask(cls, duts: list[int]) -> str:
        """将 DUT 编号列表转换为 Bitmask。

        Args:
            duts: 要测试的 DUT 编号列表（如 [1, 3, 5]）。

        Returns:
            8位二进制字符串。

        Example:
            >>> ArmProtocol.duts_to_bitmask([1, 3])
            '10100000'
            >>> ArmProtocol.duts_to_bitmask([1, 2, 3, 4, 5, 6, 7, 8])
            '11111111'
        """
        # 验证 DUT 编号范围（1-8）
        invalid_duts = [d for d in duts if not (1 <= d <= 8)]
        if invalid_duts:
            raise ValueError(f"DUT 编号必须在 1-8 范围内，非法值: {invalid_duts}")

        return "".join("1" if i in duts else "0" for i in range(1, 9))

    @classmethod
    def build_trigger(cls, boards_to_test: list[int] | None = None) -> str:
        """构建触发命令，通知机械臂开始测试。

        上位机发送此命令触发机械臂开始测试流程。
        机械臂收到后会发送 @START_TEST 指令。

        协议规定：EC 字段为 "0001" 表示该位置有数据需要测试，
        "0000" 表示该位置无数据（不测试）。

        Args:
            boards_to_test: 要测试的板子编号列表（1-8），默认为 [1, 2]（测试前两个板子）。

        Returns:
            触发命令字符串，格式为：
            - 测试板子1和2: @TEST_DONE 00 0001 0001 0000 0000 0000 0000 0000 0000+
            - 只测试板子1: @TEST_DONE 00 0001 0000 0000 0000 0000 0000 0000 0000+
            - 测试板子1和3: @TEST_DONE 00 0001 0000 0001 0000 0000 0000 0000 0000+
        """
        if boards_to_test is None:
            boards_to_test = [1, 2]  # 默认测试前两个板子

        error_codes = []
        for i in range(1, 9):
            error_codes.append("0001" if i in boards_to_test else "0000")

        return f"{cls.CMD_DONE} 00 {' '.join(error_codes)}{cls.CMD_TERMINATOR}"

    @classmethod
    def parse_error_code_response(cls, raw: str) -> str | None:
        """解析 3720 返回的错误码响应。

        3720 返回格式: ErrorCode: XXXX

        Args:
            raw: 原始响应字符串。

        Returns:
            4位十六进制错误码，解析失败返回 None。
        """
        if not raw:
            return None

        # 去除首尾空白
        raw = raw.strip()

        # 匹配 "ErrorCode: XXXX" 格式
        match = re.match(r"^ErrorCode:\s*([0-9A-Fa-f]{4})$", raw, re.IGNORECASE)
        if match:
            return match.group(1).upper()

        # 尝试直接匹配 4 位十六进制
        if re.fullmatch(r"^[0-9A-Fa-f]{4}$", raw):
            return raw.upper()

        logger.warning("无法解析 3720 错误码响应: %r", raw)
        return None
