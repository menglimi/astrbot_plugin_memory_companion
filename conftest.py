"""pytest 启动兜底：把插件 checkout 根目录放进 sys.path。

从仓库根跑 pytest 本来就能 import core.*，但在 CI 或别的机器上用
python -m pytest /abs/path/tests、或把 checkout 当子目录挂载时，根目录
（即插件包根）可能不在 sys.path 上。这里只做无副作用的路径兜底，
不注册任何 fixture，也不改动测试行为。
"""

from __future__ import annotations

import sys
from pathlib import Path


_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
