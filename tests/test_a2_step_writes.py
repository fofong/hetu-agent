"""A2 · step_writes 任务级幂等实验。

夹具: 重复投递 / 外部效果完成后、checkpoint 写入前崩溃。
反例: 禁用 step_writes -> 重放重复执行外部效果。
"""
import os
import tempfile
import unittest

from hetu.kernel.effect_ledger import CONFIRMED, INTENT, EffectLedger
from hetu.kernel.step_writes import CrashInjected, StepWrites, deterministic_task_id


class TestA2(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="hetu-a2-")
        self.db = os.path.join(self.dir, "hetu.db")
        self.sw = StepWrites(self.db)
        self.ledger = EffectLedger(self.db)

    def test_deterministic_task_id(self):
        a = deterministic_task_id("job", "2026-11-18", "run")
        b = deterministic_task_id("job", "2026-11-18", "run")
        c = deterministic_task_id("job", "2026-11-18", "retry")
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)

    def test_duplicate_delivery_zero_effect(self):
        calls = []
        tid = deterministic_task_id("j1", "t1", "schedule")
        self.sw.run(tid, "step1", lambda: calls.append(1) or "r1")
        self.sw.run(tid, "step1", lambda: calls.append(1) or "r1")  # 重复投递
        self.assertEqual(len(calls), 1)

    def test_crash_after_effect_before_checkpoint(self):
        """外部成功 + step 写入前崩溃: 重放靠 ledger 已 CONFIRMED 跳过外部效果。"""
        tid = deterministic_task_id("j2", "t2", "schedule")
        calls = []

        def guarded_effect():
            # 先写 ledger 意图, 外部效果经 ledger 提交(先写后 checkpoint)
            if self.ledger.state("eff-1") == CONFIRMED:
                return "recovered-from-ledger"
            self.ledger.intent("api_call", {}, "eff-1")
            tok = self.ledger.acquire("eff-1", "w1")
            self.ledger.execute("eff-1", "w1", tok, lambda: calls.append(1) or "sent")
            return "sent"

        with self.assertRaises(CrashInjected):
            self.sw.run(tid, "step1", guarded_effect,
                        crash_after_effect_before_write=True)
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.ledger.state("eff-1"), CONFIRMED)
        # 崩溃后重放: step 无记录 -> 重入 step -> ledger 已 CONFIRMED -> 外部零重复
        out = self.sw.run(tid, "step1", guarded_effect)
        self.assertEqual(out, "recovered-from-ledger")
        self.assertEqual(len(calls), 1)

    def test_counterexample_no_step_writes_reexecutes(self):
        """反例夹具: 禁用 step_writes 必红 —— 崩溃重放重复执行外部效果。"""
        calls = []
        first = [True]

        def naive_run():
            calls.append(1)  # 无 step 记录, 每次都真执行
            if first[0]:
                first[0] = False
                raise CrashInjected("crash after effect")

        try:
            naive_run()
        except CrashInjected:
            pass
        naive_run()  # 重放
        self.assertEqual(len(calls), 2, "反例夹具失效: 应复现重复执行")


if __name__ == "__main__":
    unittest.main()
