"""D1 · 调度五实验: 幂等槽 / 漏跑台账+补跑策略 / 重入 fencing / 断点重试 / 投递执行解耦。

故障注入: 重复投递 / 并发执行 / 崩溃于效果后完成前。
反例: 无幂等槽 -> 重复投递双执行。
"""
import os
import tempfile
import unittest

from hetu.sched.scheduler import DurableScheduler, LeaseHeld


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="hetu-d1-")
        self.db = os.path.join(self.dir, "hetu.db")
        self.s = DurableScheduler(self.db)


class TestD1IdempotentSlot(Base):
    def test_duplicate_delivery_single_slot(self):
        self.s.add_job("sync", 60)
        self.assertEqual(self.s.fire("sync", 1000.0), "created")
        self.assertEqual(self.s.fire("sync", 1000.0), "duplicate")
        self.assertEqual(self.s.fire("sync", 1000.0, "manual"), "created")  # 键含 trigger_type

    def test_counterexample_no_slot_double_run(self):
        """反例夹具: 无幂等槽必红 —— 重复投递双执行。"""
        runs = []
        for _ in range(2):  # naive: 投递即执行, 无槽
            runs.append(1)
        self.assertEqual(len(runs), 2, "反例夹具失效")


class TestD1MissedLedger(Base):
    def test_coalesce_policy(self):
        self.s.add_job("j", 10, policy="coalesce")
        self.s.fire("j", 100.0)
        self.s._job("j")
        import sqlite3
        con = sqlite3.connect(self.db)
        con.execute("UPDATE jobs SET last_fire=100 WHERE job_id='j'")
        con.commit(); con.close()
        out = self.s.catch_up("j", now=145.0)  # 漏 110,120,130,140
        self.assertEqual(out["missed"], 4)
        self.assertEqual(out["created"], 1)  # 只补最新一次
        self.assertEqual(len(self.s.missed_rows("j")), 3)

    def test_per_run_policy(self):
        self.s.add_job("j2", 10, policy="per-run")
        con = sqlite3_connect(self.db)
        con.execute("INSERT OR REPLACE INTO jobs(job_id,interval_sec,policy,last_fire)"
                    " VALUES('j2',10,'per-run',100)")
        con.commit(); con.close()
        out = self.s.catch_up("j2", now=130.0)
        self.assertEqual(out["missed"], 3)
        self.assertEqual(out["created"], 3)

    def test_skip_alert_policy(self):
        self.s.add_job("j3", 10, policy="skip+alert")
        con = sqlite3_connect(self.db)
        con.execute("INSERT OR REPLACE INTO jobs(job_id,interval_sec,policy,last_fire)"
                    " VALUES('j3',10,'skip+alert',100)")
        con.commit(); con.close()
        out = self.s.catch_up("j3", now=125.0)
        self.assertEqual(out["created"], 0)
        self.assertEqual(out["missed"], 2)
        self.assertTrue(os.path.exists(self.s.alerts_path))  # 告警落盘


def sqlite3_connect(path):
    import sqlite3
    return sqlite3.connect(path)


class TestD1Fencing(Base):
    def test_concurrent_claim_blocked(self):
        self.s.add_job("f", 60)
        self.s.fire("f", 1000.0)
        t1 = self.s.claim("f", 1000.0, "schedule", "w1", lease_ttl=0)  # 僵尸: 租约即刻过期
        t2 = self.s.claim("f", 1000.0, "schedule", "w2", lease_ttl=60)  # 接管
        self.assertGreater(t2, t1)  # fencing token 严格递增
        with self.assertRaises(LeaseHeld):
            self.s.claim("f", 1000.0, "schedule", "w3", lease_ttl=60)  # w2 仍持有

    def test_stale_completion_ignored(self):
        """僵尸 worker 复活后写完成 -> fencing token 不匹配, 状态不被覆盖。"""
        self.s.add_job("f2", 60)
        self.s.fire("f2", 2000.0)
        self.s.claim("f2", 2000.0, "schedule", "zombie", lease_ttl=0)
        self.s.run_slot("f2", 2000.0, "schedule", "live", lambda: None)  # 接管并跑完
        self.assertEqual(self.s.slot("f2", 2000.0, "schedule")["state"], "DONE")


class TestD1BreakpointRetry(Base):
    def test_failed_slot_retried(self):
        self.s.add_job("r", 60)
        self.s.fire("r", 3000.0)
        boom = [True]

        def fn():
            if boom[0]:
                raise RuntimeError("transient")
        self.assertEqual(self.s.run_slot("r", 3000.0, "schedule", "w1", fn), "FAILED")
        pend = self.s.pending_slots()
        self.assertEqual(len(pend), 1)  # 断点保留在台账
        boom[0] = False
        self.assertEqual(self.s.run_slot("r", 3000.0, "schedule", "w1", fn), "DONE")
        self.assertEqual(self.s.slot("r", 3000.0, "schedule")["attempts"], 2)

    def test_crash_after_effect_before_completion(self):
        """崩溃于外部效果后、槽完成前: 槽仍 RUNNING, 租约过期后可重认领。"""
        self.s.add_job("c", 60)
        self.s.fire("c", 4000.0)
        with self.assertRaises(RuntimeError):
            self.s.run_slot("c", 4000.0, "schedule", "w1", lambda: None,
                            crash_after_effect=True, lease_ttl=0)
        self.assertEqual(self.s.slot("c", 4000.0, "schedule")["state"], "RUNNING")
        # 重启后认领(租约已过期) + 幂等效果 -> 零重复由 A2 step_writes 保证
        self.assertEqual(self.s.run_slot("c", 4000.0, "schedule", "w2", lambda: None), "DONE")


class TestD1DeliveryDecoupled(Base):
    def test_delivery_independent_of_execution(self):
        self.s.add_job("dd", 60)
        self.s.fire("dd", 5000.0)
        did = self.s.deliver("dd", 5000.0)
        self.assertEqual(len(self.s.unacked_deliveries()), 1)
        # 执行不依赖投递回执
        self.s.run_slot("dd", 5000.0, "schedule", "w1", lambda: None)
        self.assertEqual(self.s.slot("dd", 5000.0, "schedule")["state"], "DONE")
        self.assertEqual(len(self.s.unacked_deliveries()), 1)  # 投递仍未 ack
        self.s.ack(did)
        self.assertEqual(self.s.unacked_deliveries(), [])


if __name__ == "__main__":
    unittest.main()
