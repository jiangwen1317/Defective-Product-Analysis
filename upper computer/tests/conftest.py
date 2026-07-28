"""pytest 共享配置。

统一将项目根目录加入模块搜索路径，各测试文件无需重复 sys.path 注入样板。
conftest.py 由 pytest 在收集测试模块之前自动加载。
"""

import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))
