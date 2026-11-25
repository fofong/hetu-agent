"""A5 · 压缩即归档实验。

夹具: 压缩后原文必须仍在(追加归档), 工作集缩小。
反例: 破坏性压缩删除原文 -> 不变量检查必红。
"""
import os
import tempfile
import unittest

from hetu.kernel.archive import Archiver


class TestA5(unittest.TestCase):
    def setUp(self):
        self.db = os.path.join(tempfile.mkdtemp(prefix="hetu-a5-"), "hetu.db")
        self.ar = Archiver(self.db)
        for i in range(10):
            self.ar.add("msg-%d" % i, {"text": "history %d" % i})

    def test_compact_archives_without_deleting_originals(self):
        ids = ["msg-%d" % i for i in range(6)]
        n = self.ar.compact(ids)
        self.assertEqual(n, 6)
        for iid in ids:
            self.assertTrue(self.ar.archived(iid), "%s 应已归档" % iid)
            self.assertTrue(self.ar.original_exists(iid), "%s 原文必须保留" % iid)
        self.assertEqual(self.ar.working_count(), 4)  # 工作集缩小

    def test_counterexample_destructive_compact_violates_invariant(self):
        """反例夹具: 禁用「永不删除原文」约束必红。"""
        ids = ["msg-0", "msg-1"]
        self.ar.compact(ids, destructive=True)  # naive 压缩: 直接删
        gone = [i for i in ids if not self.ar.original_exists(i)]
        self.assertEqual(len(gone), 2, "反例夹具失效: 破坏性压缩应复现原文丢失")


if __name__ == "__main__":
    unittest.main()
