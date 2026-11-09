"""发布物卫生自证：scripts/check_release.py 必须真的拦得住本地残留。

审核报告 L13：2.5.0 的发布包 615 个文件里混进 211 个 .pyc（5 个 __pycache__）
和 data/cmd_config.json。光有检查脚本不够——这里在临时目录里分别造「干净树」
和「脏树」，断言脚本的退出码、输出与命中路径，防止脚本写坏了还 exit 0 的假绿。

这里只断言临时目录，不拿真实仓库当「必须干净」：跑测试本身会生成
__pycache__ 和 data/，真实仓库的清理由发布流程负责。
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_release.py"
GITIGNORE = ROOT / ".gitignore"


def run_check(repo: Path) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(repo)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=120,
    )


def make_clean_tree(root: Path) -> None:
    (root / "core").mkdir()
    (root / "core" / "__init__.py").write_text("", encoding="utf-8")
    (root / "core" / "config.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "main.py").write_text("", encoding="utf-8")
    (root / "requirements.txt").write_text("astrbot>=4.27\n", encoding="utf-8")
    # 版本库目录是本地基础设施，必须静默跳过而不是报违规。
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text("[core]\n", encoding="utf-8")
    (root / ".git" / "objects.db").write_text("", encoding="utf-8")


class ReleaseHygieneTests(unittest.TestCase):
    def test_check_release_script_exists(self) -> None:
        self.assertTrue(SCRIPT.is_file(), f"缺少发布物检查脚本：{SCRIPT}")

    def test_clean_tree_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_clean_tree(root)
            result = run_check(root)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("通过", result.stdout)

    def test_pycache_and_data_directory_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_clean_tree(root)
            cache = root / "core" / "__pycache__"
            cache.mkdir()
            (cache / "config.cpython-312.pyc").write_bytes(b"pyc")
            (root / "data").mkdir()
            (root / "data" / "cmd_config.json").write_text("{}", encoding="utf-8")
            result = run_check(root)
            self.assertEqual(1, result.returncode, result.stdout + result.stderr)
            self.assertIn("core/__pycache__/", result.stdout)
            self.assertIn("data/", result.stdout)

    def test_single_pyc_without_pycache_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_clean_tree(root)
            (root / "stray.pyc").write_bytes(b"pyc")
            result = run_check(root)
            self.assertEqual(1, result.returncode, result.stdout + result.stderr)
            self.assertIn("stray.pyc", result.stdout)

    def test_patch_leftovers_and_local_databases_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_clean_tree(root)
            (root / "core" / "config.py.orig").write_text("", encoding="utf-8")
            (root / "core" / "config.py.rej").write_text("", encoding="utf-8")
            (root / "storage.db").write_bytes(b"db")
            (root / "storage.db-wal").write_bytes(b"wal")
            (root / "storage.db-shm").write_bytes(b"shm")
            result = run_check(root)
            self.assertEqual(1, result.returncode, result.stdout + result.stderr)
            for expected in (
                "core/config.py.orig",
                "core/config.py.rej",
                "storage.db",
                "storage.db-wal",
                "storage.db-shm",
            ):
                self.assertIn(expected, result.stdout)

    def test_gitignore_covers_runtime_artifacts(self) -> None:
        text = GITIGNORE.read_text(encoding="utf-8")
        for pattern in ("__pycache__/", "data/", "*.pyc", "*.db", "*.db-wal", "*.db-shm"):
            self.assertIn(pattern, text, f".gitignore 缺少 {pattern}")


if __name__ == "__main__":
    unittest.main()