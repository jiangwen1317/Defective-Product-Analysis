"""
机械臂中转网关 - 程序入口。

v2.0 主动触发模式中转网关。
支持两种工作模式：
- 主动触发：上位机发送 @TEST_DONE 触发机械臂，机械臂返回 @START_TEST
- 被动监听：接收机械臂的 @START_TEST 指令，自动转发至 3720 测试仪

使用 PyQt5 构建图形界面，支持多 DUT 并发测试。
"""

import logging
import os
import sys
import warnings
from pathlib import Path

# 抑制 libpng 警告（Pillow/PyQt5 加载 PNG 时的元数据警告）
os.environ["PIL_SUPPRESS_LIBPNG_WARNS"] = "1"
warnings.filterwarnings("ignore", message=".*iCCP.*")

from ui.main_window import main


def setup_logging() -> None:
    """配置日志系统，支持控制台和文件双输出。

    日志文件使用追加模式，支持自动轮转（通过外部工具如 logrotate）。
    """
    # 确保日志目录存在
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    # 日志文件路径（按日期）
    log_file = log_dir / "gateway.log"

    # 获取根 logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # 避免重复添加 handler
    if root_logger.handlers:
        root_logger.handlers.clear()

    # 格式化器
    formatter = logging.Formatter(
        fmt="%(asctime)s.%(msecs)03d - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # 文件处理器（追加模式，UTF-8 编码）
    file_handler = logging.FileHandler(
        log_file,
        mode="a",
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)  # 文件记录 DEBUG 级别
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)


if __name__ == "__main__":
    # 配置日志（控制台 + 文件）
    setup_logging()

    # 启动应用
    main()
