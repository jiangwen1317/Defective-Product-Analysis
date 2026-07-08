"""
机械臂中转网关 - 程序入口。

v2.0 主动触发模式中转网关。
支持两种工作模式：
- 主动触发：上位机发送 @TEST_DONE 触发机械臂，机械臂返回 @START_TEST
- 被动监听：接收机械臂的 @START_TEST 指令，自动转发至 3720 测试仪

使用 PyQt5 构建图形界面，支持多 DUT 并发测试。
"""

import logging
import sys

# 抑制 libpng 警告（Pillow/PyQt5 加载 PNG 时的元数据警告）
import os
os.environ["PIL_SUPPRESS_LIBPNG_WARNS"] = "1"

from ui.main_window import main

if __name__ == "__main__":
    # 配置日志
    logging.basicConfig(
        level=logging.DEBUG,  # 临时启用 DEBUG 以诊断问题
        format="%(asctime)s.%(msecs)03d - %(name)s - %(levelname)s - %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
        ],
    )

    # 启动应用
    main()
