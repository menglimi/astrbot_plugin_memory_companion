"""pytest 运行时的 sys.path 兜底（tests 目录内版本）。

pyproject.toml 的 addopts 把 confcutdir 钉在 tests/：pytest 只加载
confcutdir 及其下方之外的 conftest，仓库根的 conftest.py 因此不会被加载，
所以真正生效的路径兜底放在这里。行为与根 conftest.py 完全一致：只把插件
checkout 根目录放进 sys.path，不注册 fixture、不改测试行为。
"""

from __future__ import annotations

import sys
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
