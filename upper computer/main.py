"""
机械臂中转网关 - 程序入口。

v3.0 纯被动响应式全自动中转网关。
监听机械臂信号，自动转发至 3720 测试仪，结果自动回传。
"""

import logging
import sys

from ui.main_window import main

if __name__ == "__main__":
    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s.%(msecs)03d - %(name)s - %(levelname)s - %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
        ],
    )

    # 启动应用
    main()
