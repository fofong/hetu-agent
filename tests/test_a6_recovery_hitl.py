"""A6 · plan-hash 恢复点校验 + HITL 持久挂起实验。

夹具: 计划漂移 -> 拒续转人工; interrupt 跨进程重启(新连接)仍在。
反例: 禁用 plan-hash 校验 -> 带漂移计划继续执行。
"""
import os
import tempfile
import unittest

from hetu.kernel.hitl import PENDING, RELEASED, Interrupts
from hetu.kernel.recovery import PlanDrift, RecoveryPoints


class TestA6(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="hetu-a6-")
        self.db = os.path.join(self.dir, "hetu.db")
        self.rp = RecoveryPoints(self.db)
        self.hitl = Interrupts(self.db)

    def test_resume_same_plan_ok(self):
        plan = {"steps": ["a", "b", "c"]}
        self.rp.save("task1", plan, {"done": ["a"]})
        self.assertEqual(self.rp.resume("task1", plan), {"done": ["a"]})

    def test_plan_drift_refuses_and_escalates(self):
        plan = {"steps": ["a", "b", "c"]}
        self.rp.save("task2", plan, {"done": ["a"]})
        drifted = {"steps": ["a", "b", "c", "extra"]}
        with self.assertRaises(PlanDrift):
            self.rp.resume("task2", drifted)
        # 拒续 -> 转人工(HITL 持久挂起)
        iid = self.hitl.raise_interrupt("task2", "plan-drift", {"plan_hash_expected": True})
        self.assertEqual(self.hitl.state(iid), PENDING)
        self.hitl.release(iid, "supervisor-1")
        self.assertEqual(self.hitl.state(iid), RELEASED)

    def test_interrupt_survives_process_restart(self):
        iid = self.hitl.raise_interrupt("task3", "high-risk", {"action": "wire_transfer"})
        # 模拟进程重启: 全新实例(新 SQLite 连接)读同一库
        fresh = Interrupts(self.db)
        self.assertEqual(fresh.state(iid), PENDING)
        self.assertEqual([r["interrupt_id"] for r in fresh.pending()], [iid])
        fresh.release(iid, "human-ops")
        self.assertEqual(fresh.state(iid), RELEASED)

    def test_counterexample_no_plan_hash_check_resumes_drifted(self):
        """反例夹具: 禁用恢复点校验必红 —— 漂移计划被直接续跑。"""
        plan = {"steps": ["a", "b", "c"]}
        self.rp.save("task4", plan, {"done": ["a"]})
        drifted = {"steps": ["a", "b", "c", "extra"]}
        state = self.rp.resume("task4", drifted, enforce=False)  # 禁用机制
        self.assertEqual(state, {"done": ["a"]},
                         "反例夹具失效: 无校验时漂移计划应被危险续跑")


if __name__ == "__main__":
    unittest.main()
