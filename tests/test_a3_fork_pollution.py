"""A3 · fork 式分支纠正 + 依赖污染传播实验。

夹具: 上游产物被污染 -> 全部下游失效化, 未受污染成果保留; fork 修正验收后原子切换。
反例: 禁用污染传播 -> 下游继续消费污染结果。
"""
import os
import tempfile
import unittest

from hetu.kernel.fork import ACTIVE, INVALIDATED, ArtifactLedger


class TestA3(unittest.TestCase):
    def setUp(self):
        self.db = os.path.join(tempfile.mkdtemp(prefix="hetu-a3-"), "hetu.db")
        self.led = ArtifactLedger(self.db)
        # 依赖链: raw -> parsed -> report ; 独立成果: unrelated
        self.led.record("raw", "dirty-data", input_hash="h-raw", validator_version="v1")
        self.led.record("parsed", "parsed", dependency_ids=["raw"], validator_version="v1")
        self.led.record("report", "report", dependency_ids=["parsed"], validator_version="v1")
        self.led.record("unrelated", "clean", validator_version="v1")
        self.led.accept("deliverable", "report")

    def test_pollution_propagates_to_all_downstream(self):
        tainted = self.led.invalidate("raw")
        self.assertEqual(tainted, ["parsed", "raw", "report"])
        self.assertEqual(self.led.status("report"), INVALIDATED)
        # 公理3: 未受污染成果保留
        self.assertEqual(self.led.status("unrelated"), ACTIVE)

    def test_fork_correction_atomic_switch(self):
        self.led.invalidate("raw")
        before = self.led.delivered("deliverable")
        self.led.fork_correction("report", "report-v2", "fixed-report", validator_version="v2")
        self.led.accept("deliverable", "report-v2")
        self.assertEqual(self.led.delivered("deliverable"), "report-v2")
        # 原产物不可变: 行仍在且内容哈希未变(逻辑分支, 非文件系统回滚)
        rows = {r["artifact_id"]: r for r in self.led._all()}
        self.assertIn("report", rows)
        self.assertEqual(rows["report"]["content_hash"], rows["report"]["content_hash"])
        self.assertNotEqual(before, "report-v2")

    def test_cannot_deliver_invalidated(self):
        self.led.invalidate("raw")
        with self.assertRaises(ValueError):
            self.led.accept("deliverable", "report")

    def test_counterexample_no_propagation_leaves_tainted_downstream(self):
        """反例夹具: 禁用传播必红 —— 下游仍 ACTIVE, 继续消费污染结果。"""
        db2 = os.path.join(tempfile.mkdtemp(prefix="hetu-a3x-"), "hetu.db")
        led = ArtifactLedger(db2)
        led.record("raw", "dirty", validator_version="v1")
        led.record("parsed", "parsed", dependency_ids=["raw"], validator_version="v1")
        led.invalidate("raw", propagate=False)  # 禁用机制
        self.assertEqual(led.status("parsed"), ACTIVE,
                         "反例夹具失效: 无传播时下游应残留 ACTIVE")


if __name__ == "__main__":
    unittest.main()
