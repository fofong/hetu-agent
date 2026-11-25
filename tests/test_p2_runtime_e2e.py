"""Phase 2 一体化运行时端到端实验: 崩溃恢复零重复 / 漂移转人工 / 高风险挂起 / 对账续跑。"""
import os
import tempfile
import unittest

from hetu.evidence.chain import EvidenceChain
from hetu.kernel.effect_ledger import EffectLedger
from hetu.kernel.hitl import PENDING, Interrupts
from hetu.runtime import DONE, ESCALATED, PAUSED_WAIT, Step, TaskRunner, run_due
from hetu.sched.scheduler import DurableScheduler


class Base(unittest.TestCase):
    def setUp(self):
        self.db = os.path.join(tempfile.mkdtemp(prefix="hetu-p2-"), "hetu.db")
        self.counters = {}

    def effect(self, name):
        def f():
            self.counters[name] = self.counters.get(name, 0) + 1
            return "done-%s" % name
        return f

    def steps(self):
        return [Step("s1", "fetch", self.effect("s1")),
                Step("s2", "charge", self.effect("s2")),
                Step("s3", "notify", self.effect("s3"))]


class TestHappyPath(Base):
    def test_three_steps_all_confirmed(self):
        r = TaskRunner(self.db)
        out = r.run_task("t1", ["a", "b"], self.steps())
        self.assertEqual(out["status"], DONE)
        self.assertEqual(self.counters, {"s1": 1, "s2": 1, "s3": 1})
        ok, _ = EvidenceChain(self.db).verify()
        self.assertTrue(ok)

    def test_rerun_completed_task_zero_effects(self):
        r = TaskRunner(self.db)
        r.run_task("t1", ["a", "b"], self.steps())
        out = r.run_task("t1", ["a", "b"], self.steps())  # 全量重放
        self.assertEqual(out["status"], DONE)
        self.assertEqual(self.counters, {"s1": 1, "s2": 1, "s3": 1})  # 零重复
        # 重放必须读回原始业务回执, 而非字符串标记
        self.assertEqual(out["results"],
                         {"s1": "done-s1", "s2": "done-s2", "s3": "done-s3"})


class TestCrashRecovery(Base):
    def test_crash_mid_task_resumes_zero_duplicate(self):
        r = TaskRunner(self.db)
        out = r.run_task("t2", ["a", "b"], self.steps(), crash_at_step="s2")
        self.assertEqual(out["status"], "INTERRUPTED")
        self.assertEqual(self.counters, {"s1": 1, "s2": 1})  # s2 外部已发生
        out = r.run_task("t2", ["a", "b"], self.steps())     # 崩溃后重跑
        self.assertEqual(out["status"], DONE)
        self.assertEqual(self.counters, {"s1": 1, "s2": 1, "s3": 1})  # 副作用零重复(M2 语义)

    def test_receipt_lost_reconciles_then_done(self):
        from hetu.kernel.effect_ledger import ReceiptLost
        calls = {"x": 0}

        def flaky():
            calls["x"] += 1
            raise ReceiptLost("external ok, receipt lost")

        r = TaskRunner(self.db, probes={"charge": lambda: {"external": "charged"}})
        steps = [Step("s1", "charge", flaky)]
        out = r.run_task("t3", ["p"], steps)
        self.assertEqual(out["status"], "RECONCILE")
        out = r.run_task("t3", ["p"], steps)  # 重跑 -> 对账确认外部成功, 不重放
        self.assertEqual(out["status"], DONE)
        self.assertEqual(calls["x"], 1)


class TestHITL(Base):
    def test_plan_drift_escalates(self):
        r = TaskRunner(self.db)
        r.run_task("t4", ["a", "b"], self.steps()[:1])
        out = r.run_task("t4", ["a", "b", "extra"], self.steps()[:1])  # 计划漂移
        self.assertEqual(out["status"], ESCALATED)
        self.assertEqual(len(Interrupts(self.db).pending()), 1)

    def test_high_risk_step_pauses_then_release_completes(self):
        r = TaskRunner(self.db)
        steps = [Step("s1", "fetch", self.effect("s1")),
                 Step("s2", "wire_transfer", self.effect("s2"), risk="high")]
        out = r.run_task("t5", ["p"], steps)
        self.assertEqual(out["status"], PAUSED_WAIT)
        self.assertNotIn("s2", self.counters)  # 未放行绝不执行
        hitl = Interrupts(self.db)
        pend = hitl.pending()
        self.assertEqual(len(pend), 1)
        hitl.release(pend[0]["interrupt_id"], "human-ops")
        EffectLedger(self.db).release_high_risk("t5:s2")
        out = r.run_task("t5", ["p"], steps)
        self.assertEqual(out["status"], DONE)
        self.assertEqual(self.counters.get("s2"), 1)


class TestSchedulerIntegration(Base):
    def test_run_due_executes_pending_once(self):
        sched = DurableScheduler(self.db)
        sched.add_job("nightly", 60)
        sched.fire("nightly", 1000.0)
        sched.fire("nightly", 1000.0)  # 重复投递
        runs = []
        n = run_due(sched, {"nightly": lambda: runs.append(1)})
        self.assertEqual(n, 1)
        self.assertEqual(len(runs), 1)
        self.assertEqual(run_due(sched, {"nightly": lambda: runs.append(1)}), 0)


if __name__ == "__main__":
    unittest.main()
