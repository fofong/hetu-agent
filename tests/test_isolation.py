"""与旧产品树严格区别机制的实验(反例驱动)。

正例: 守卫拒绝旧产品树路径/环境变量; 静态扫描全过。
反例: 证明守卫确实能拦截(把 DB 放进模拟的 hasu 树 -> 必红)。
"""
import os
import subprocess
import sys
import tempfile
import unittest

from hetu.db import connect
from hetu.guard import IsolationViolation, check_env, check_path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestRuntimeGuard(unittest.TestCase):
    def test_refuses_db_inside_legacy_tree(self):
        fake = tempfile.mkdtemp(prefix="legacy-")
        hasu_tree = os.path.join(fake, "hasu-" + "agent-20261115")
        os.makedirs(hasu_tree)
        with self.assertRaises(IsolationViolation):
            connect(os.path.join(hasu_tree, "hetu.db"))
        with self.assertRaises(IsolationViolation):
            check_path(os.path.join(fake, "." + "hermes", "x.db"))

    def test_refuses_hetu_env_pointing_into_legacy_tree(self):
        with self.assertRaises(IsolationViolation):
            check_env({"HETU_DB": "/Users/x/." + "hermes" + "/hetu.db"})
        check_env({"HETU_DB": "/tmp/hetu.db"})          # 干净配置通过
        check_env({"HERMES_" + "HOME": "/Users/x/." + "hermes"})  # 宿主旧产品变量不算违规
        check_env({})

    def test_allows_clean_paths(self):
        d = tempfile.mkdtemp(prefix="hetu-ok-")
        connect(os.path.join(d, "hetu.db")).close()


class TestStaticScan(unittest.TestCase):
    def test_isolation_check_passes(self):
        r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "isolation_check.py")],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
