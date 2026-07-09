"""
机械臂中转网关 - 程序入口。

v2.0 主动触发模式中转网关，实现机械臂与 3720 测试仪之间的信号透传。

支持两种启动方式：
- 主动触发：用户点击"触发测试"，上位机发送 @TEST_DONE（指定要测试的板子），
            机械臂响应 @START_TEST，触发测试流程
- 被动监听：接收机械臂主动发送的 @START_TEST 指令，自动触发测试流程

使用 PyQt5 构建图形界面，支持多 DUT 并发测试。

架构：
  机械臂 <──TCP/串口──> 网关 <──TCP──> 3720测试仪
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


def preflight_check() -> bool:
    """启动前自检。

    Returns:
        检查是否通过。
    """
    # 获取项目根目录
    project_root = Path(__file__).parent

    # 检查配置文件存在
    config_path = project_root / "config.json"
    if not config_path.exists():
        print("错误: 配置文件 config.json 不存在", file=sys.stderr)
        print("提示: 请复制 config.example.json 为 config.json 并修改配置", file=sys.stderr)
        return False

    # 检查日志目录可写
    log_dir = project_root / "logs"
    if not log_dir.exists():
        try:
            log_dir.mkdir(exist_ok=True)
        except OSError as e:
            print(f"错误: 无法创建日志目录: {e}", file=sys.stderr)
            return False

    if not os.access(log_dir, os.W_OK):
        print("错误: 日志目录不可写", file=sys.stderr)
        return False

    # 检查 Python 版本
    if sys.version_info < (3, 10):
        print(f"错误: 需要 Python 3.10+, 当前版本: {sys.version_info.major}.{sys.version_info.minor}",
              file=sys.stderr)
        return False

    return True


if __name__ == "__main__":
    # 启动前自检
    if not preflight_check():
        sys.exit(1)

    # 配置日志（控制台 + 文件）
    setup_logging()

    # 启动应用
    main()
