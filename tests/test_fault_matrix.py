"""故障注入矩阵(备忘录 §5 M1): 崩溃/重复投递/并发执行/网络超时/DB写失败/回执丢失。

崩溃与回执丢失已在 e2e 覆盖; 本文件补齐: 并发执行、网络超时、DB 写失败。
"""
from __future__ import annotations

import os
import sqlite3
import tempfile
import threading
import time
import unittest

from hetu.kernel.effect_ledger import (CONFIRMED, EXECUTING, INTENT,
                                       EffectLedger, LeaseHeld,
                                       LedgerCorrupted, NotReconciled)
from hetu.runtime import Step, TaskRunner


class TempDB(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "h.db")

    def tearDown(self):
        self.tmp.cleanup()


class SimCrash(Exception):
    """模拟"外部效果已成功、回执持久化前进程死亡"。"""


class TestReceiptPersistCrashCombo(TempDB):
    """验收评审风险#1 组合故障: 外部副作用成功 + 回执未持久化 + 租约到期 + 任务恢复。"""

    def _crash_setup(self, probes=None):
        runner = TaskRunner(self.db, probes=probes, lease_ttl=0)
        side = []

        def charge():
            side.append(1)                      # 外部效果已发生
            raise SimCrash("died before receipt persisted")

        r1 = runner.run_task("t", ["charge"], [Step("s1", "charge", charge)])
        time.sleep(0.01)                        # 租约(ttl=0)过期 = 执行者疑似死亡
        return runner, side, r1

    def test_probe_confirms_success_zero_replay(self):
        runner, side, r1 = self._crash_setup(probes={"charge": lambda: {"tx": "EXT-42"}})
        self.assertEqual(r1["status"], "INTERRUPTED")
        r2 = runner.run_task("t", ["charge"],
                             [Step("s1", "charge", lambda: "MUST-NOT-RUN")])
        self.assertEqual(r2["status"], "DONE")
        self.assertEqual(len(side), 1, "外部已成功: 恢复必须经对账确认, 零重放")
        self.assertEqual(r2["results"]["s1"], "reconciled-from-ledger")

    def test_no_probe_escalates_never_blind(self):
        runner, side, _ = self._crash_setup(probes=None)
        r2 = runner.run_task("t", ["charge"],
                             [Step("s1", "charge", lambda: "MUST-NOT-RUN")])
        self.assertEqual(r2["status"], "RECONCILE")
        self.assertEqual(len(side), 1, "无法确认结果时禁止盲目重放, 转对账")

    def test_probe_absent_allows_controlled_replay(self):
        runner, side, _ = self._crash_setup(probes={"charge": lambda: None})
        r2 = runner.run_task("t", ["charge"], [Step("s1", "charge", lambda: "ok")])
        self.assertEqual(r2["status"], "DONE")
        self.assertEqual(len(side), 1, "探针确认外部未发生, 重放为受控新执行")

    def test_expired_executing_acquire_requires_reconcile(self):
        led = EffectLedger(self.db)
        led.intent("x", {}, "k")
        led.acquire("k", "w1", lease_ttl=0)
        time.sleep(0.01)
        with self.assertRaises(NotReconciled):
            led.acquire("k", "w2")             # 孤儿禁盲接管


class TestConcurrentExecution(TempDB):
    def test_concurrent_runners_effect_exactly_once(self):
        """并发执行: 两 runner 同任务同步长, 租约互斥保证副作用恰好一次。"""
        runner = TaskRunner(self.db)
        side = []

        def slow():
            time.sleep(0.2)
            side.append(1)
            return "ok"

        out = {}

        def go(name, delay):
            time.sleep(delay)
            out[name] = runner.run_task("t", ["s"], [Step("s1", "slow", slow)])["status"]

        t1 = threading.Thread(target=go, args=("A", 0.0))
        t2 = threading.Thread(target=go, args=("B", 0.05))
        t1.start(); t2.start(); t1.join(); t2.join()
        self.assertEqual(len(side), 1, "副作用必须恰好一次")
        self.assertEqual(sorted(out.values()), ["DONE", "RECONCILE"],
                         "败者须转对账(孤儿禁盲接管), 不得双跑")

    def test_lease_held_blocks_second_executor(self):
        led = EffectLedger(self.db)
        led.intent("x", {}, "k1")
        tok = led.acquire("k1", "w1", lease_ttl=30)
        with self.assertRaises(LeaseHeld):
            led.acquire("k1", "w2", lease_ttl=30)
        led.execute("k1", "w1", tok, lambda: "ok")
        self.assertEqual(led.state("k1"), CONFIRMED)


class TestNetworkTimeout(TempDB):
    def test_timeout_leaves_executing_reconcile_then_retry(self):
        """网络超时: 状态滞留 EXECUTING(不谎报失败); 对账确认未发生后受控重放。"""
        led = EffectLedger(self.db)
        led.intent("api", {}, "k1")
        tok = led.acquire("k1", "w1", lease_ttl=0)
        with self.assertRaises(TimeoutError):
            led.execute("k1", "w1", tok, self._boom)
        time.sleep(0.01)
        self.assertEqual(led.state("k1"), EXECUTING)
        self.assertIn("k1", [o["idem_key"] for o in led.orphans(stale_seconds=0)])
        # 独立探针确认外部未发生 → 回 INTENT 允许受控重放
        self.assertEqual(led.reconcile("k1", lambda: None), INTENT)
        tok2 = led.acquire("k1", "w1")
        self.assertEqual(led.execute("k1", "w1", tok2, lambda: "ok"), CONFIRMED)

    def test_timeout_via_runtime_then_reconcile_resume(self):
        runner = TaskRunner(self.db, lease_ttl=0)
        calls = {"flaky": 0}

        def flaky():
            calls["flaky"] += 1
            raise TimeoutError("network timeout")

        r1 = runner.run_task("t", ["s"], [Step("s1", "api", flaky)])
        self.assertEqual(r1["status"], "INTERRUPTED")
        # 对账(探针确认未发生)后续跑: 断点续算, 不盲重放旧效果
        self.assertEqual(runner.ledger.reconcile("t:s1", lambda: None), INTENT)
        r2 = runner.run_task("t", ["s"], [Step("s1", "api", lambda: "ok")])
        self.assertEqual(r2["status"], "DONE")
        self.assertEqual(calls["flaky"], 1)

    @staticmethod
    def _boom():
        raise TimeoutError("network timeout")


class TestDBWriteFailure(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "h.db")

    def tearDown(self):
        os.chmod(self.db, 0o644)
        self.tmp.cleanup()

    def test_write_failure_fail_open_only_reversible(self):
        """DB 写失败: 仅显式可逆操作降级 fail-open(带告警); 不可逆/高风险 fail-closed。"""
        led = EffectLedger(self.db)
        led.intent("warm", {}, "k0")          # 先证明可写
        os.chmod(self.db, 0o444)             # 模拟写通道损坏
        self.assertEqual(led.intent("audit_log", {}, "k1", reversible=True),
                         "BYPASSED_FAILOPEN")
        self.assertTrue(led.fail_open_alerts, "fail-open 必须留告警")
        with self.assertRaises(LedgerCorrupted):
            led.intent("irreversible-normal", {}, "k2")   # 默认不可逆: 禁降级
        with self.assertRaises(LedgerCorrupted):
            led.intent("danger", {}, "k3", risk="high")


if __name__ == "__main__":
    unittest.main()
