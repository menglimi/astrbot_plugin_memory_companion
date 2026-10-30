"""发布物卫生检查：仓库里不能混入运行时/本地垃圾。

审核报告 L13：2.5.0 的发布包 615 个文件里夹着 211 个 .pyc（5 个 __pycache__），
还有 data/cmd_config.json。这个脚本把「发出去的目录必须干净」变成可执行检查：
CI 在打包前跑一次，tests/test_release_hygiene.py 也直接调它。

用法：
    python scripts/check_release.py --repo .

发现违规：逐行列出相对仓库根的路径，exit 1；干净则 exit 0。
只读扫描，不删除、不修改任何文件。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


# 这些目录本身就不该出现在发布包里。遇到即报，且不再深入（避免逐个文件刷屏）。
DENY_DIRS = (
    "__pycache__",
    "data",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    "node_modules",
)

# 这些目录只跳过，不报：版本库与虚拟环境是本地基础设施，不是发布内容。
SKIP_DIRS = (".git", ".hg", ".svn")

# 后缀黑名单：编译产物、补丁残留、本地数据库。
DENY_SUFFIXES = (
    ".pyc",
    ".pyo",
    ".orig",
    ".rej",
    ".db",
    ".sqlite",
    ".sqlite3",
    ".db-wal",
    ".db-shm",
    ".db-journal",
)


def find_violations(root: Path) -> list[str]:
    """返回相对 root 的违规路径（目录以 / 结尾），已排序。"""
    violations: list[str] = []
    root = root.resolve()
    for dirpath, dirnames, filenames in os.walk(root):
        current = Path(dirpath)
        kept: list[str] = []
        for name in sorted(dirnames):
            if name in SKIP_DIRS:
                continue
            child = current / name
            if name in DENY_DIRS:
                rel = child.relative_to(root).as_posix()
                violations.append(rel + "/")
                continue
            kept.append(name)
        dirnames[:] = kept
        for name in sorted(filenames):
            if name.lower().endswith(DENY_SUFFIXES):
                violations.append((current / name).relative_to(root).as_posix())
    return sorted(violations)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="检查发布目录是否混入本地残留")
    parser.add_argument("--repo", default=".", help="要扫描的仓库根目录，默认当前目录")
    args = parser.parse_args(argv)

    try:
        sys.stdout.reconfigure(errors="replace")  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        pass

    root = Path(args.repo)
    if not root.is_dir():
        print(f"扫描目录不存在或不是目录：{root}")
        return 2

    violations = find_violations(root)
    if not violations:
        print("发布物卫生检查通过：未发现 __pycache__、.pyc、data/ 等本地残留。")
        return 0

    print(f"发布物卫生检查失败：发现 {len(violations)} 处本地残留，不应进入发布包：")
    for item in violations:
        print(f"  {item}")
    print("清理后可重跑：python scripts/check_release.py --repo .")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())