"""pytest 共享配置。

统一将 Log-Download 目录（log_downloader.py 所在目录）加入模块搜索路径，
使各测试文件无需重复 sys.path 注入样板。conftest.py 由 pytest 在收集测试
模块之前自动加载。
"""

import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))
