"""pytest 共享配置。

将 tools 目录（check_exemption_baseline.py 所在目录）加入模块搜索路径，
使测试文件无需重复 sys.path 注入样板。conftest.py 由 pytest 在收集测试
模块之前自动加载。
"""

import sys
from pathlib import Path

_tools_root = Path(__file__).resolve().parent.parent
if str(_tools_root) not in sys.path:
    sys.path.insert(0, str(_tools_root))
