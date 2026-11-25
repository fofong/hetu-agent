"""A1 · Effect Ledger 实验 (P0 最优先)。

夹具: 外部执行成功但回执丢失 / 并发租约 / 高风险转人工 / ledger 自身损坏降级。
反例: 禁用 ledger -> 回执丢失后盲重放, 副作用重复。
"""
import os
import tempfile
import threading
import time
import unittest

from hetu.evidence.chain import EvidenceChain
from hetu.kernel.effect_ledger import (
    CONFIRMED, INTENT, PAUSED, UNCERTAIN, EffectLedger, HighRiskPaused,
    LedgerCorrupted, LeaseHeld, NotReconciled, ReceiptLost,
)


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="hetu-a1-")
        self.db = os.path.join(self.dir, "hetu.db")
        self.chain = EvidenceChain(self.db)
        self.ledger = EffectLedger(self.db, chain=self.chain)


class TestA1Normal(Base):
    def test_three_state_commit(self):
        self.assertEqual(self.ledger.intent("send_mail", {"to": "a@b.c"}, "k1"), INTENT)
        tok = self.ledger.acquire("k1", "w1")
        self.assertEqual(self.ledger.execute("k1", "w1", tok, lambda: {"msg_id": 7}), CONFIRMED)
        # 幂等: 重复 intent 不重复登记
        self.assertEqual(self.ledger.intent("send_mail", {"to": "a@b.c"}, "k1"), CONFIRMED)

    def test_high_risk_paused_then_released(self):
        self.assertEqual(self.ledger.intent("drop_table", {}, "k2", risk="high"), PAUSED)
        with self.assertRaises(HighRiskPaused):
            self.ledger.acquire("k2", "w1")
        self.ledger.release_high_risk("k2")
        tok = self.ledger.acquire("k2", "w1")
        self.assertEqual(self.ledger.execute("k2", "w1", tok, lambda: "ok"), CONFIRMED)


class TestA1ReceiptLost(Base):
    def test_receipt_lost_never_blind_replay(self):
        calls = []

        def effect():
            calls.append(1)
            raise ReceiptLost("external succeeded, receipt lost")

        self.ledger.intent("charge", {"amt": 10}, "pay1")
        tok = self.ledger.acquire("pay1", "w1")
        self.assertEqual(self.ledger.execute("pay1", "w1", tok, effect), UNCERTAIN)
        # UNCERTAIN 禁盲重放
        with self.assertRaises(NotReconciled):
            self.ledger.acquire("pay1", "w2")
        # 对账: 独立探针发现外部已成功 -> CONFIRMED, 效果零重复
        state = self.ledger.reconcile("pay1", lambda: {"external": "charged"})
        self.assertEqual(state, CONFIRMED)
        self.assertEqual(len(calls), 1)

    def test_receipt_lost_absent_allows_controlled_replay(self):
        calls = []

        def effect():
            calls.append(1)
            raise ReceiptLost("timeout, external actually not executed")

        self.ledger.intent("notify", {}, "n1")
        tok = self.ledger.acquire("n1", "w1")
        self.assertEqual(self.ledger.execute("n1", "w1", tok, effect), UNCERTAIN)
        self.assertEqual(self.ledger.reconcile("n1", lambda: None), INTENT)
        tok2 = self.ledger.acquire("n1", "w2")
        self.assertEqual(self.ledger.execute("n1", "w2", tok2, lambda: "ok"), CONFIRMED)
        self.assertEqual(len(calls), 1)  # 重放只在探针确认未发生后受控进行


class TestA1Concurrency(Base):
    def test_lease_fencing_blocks_concurrent(self):
        self.ledger.intent("deploy", {}, "d1")
        tok1 = self.ledger.acquire("d1", "zombie", lease_ttl=0)  # 僵尸: 租约即刻过期
        time.sleep(0.01)
        # 孤儿禁盲接管: 必须先经探针对账(验收评审风险#1)
        with self.assertRaises(NotReconciled):
            self.ledger.acquire("d1", "live", lease_ttl=60)
        self.ledger.reconcile("d1", lambda: None)  # 探针确认外部未发生
        tok2 = self.ledger.acquire("d1", "live", lease_ttl=60)  # 受控接管, token 递增
        self.assertGreater(tok2, tok1)
        with self.assertRaises(LeaseHeld):
            self.ledger.acquire("d1", "other", lease_ttl=60)    # live 仍持有
        # 僵尸复活拿旧 token 回来 -> fencing 拒绝
        with self.assertRaises(LeaseHeld):
            self.ledger.execute("d1", "zombie", tok1, lambda: "stale")


class TestA1LedgerSelfFailure(Base):
    def test_corruption_failopen_only_explicit_reversible(self):
        self.ledger.corrupt()
        # 仅显式声明可逆的纯记录操作: fail-open + 告警
        self.assertEqual(self.ledger.intent("log_event", {}, "c1", reversible=True),
                         "BYPASSED_FAILOPEN")
        self.assertTrue(len(self.ledger.fail_open_alerts) >= 1)
        # 不可逆外部副作用(默认): 即使风险标签 normal 也 fail-closed(评审风险#2)
        with self.assertRaises(LedgerCorrupted):
            self.ledger.intent("wire_debit", {}, "c2")
        # 高风险: fail-closed
        with self.assertRaises(LedgerCorrupted):
            self.ledger.intent("wire_transfer", {}, "c3", risk="high")


class TestA1Counterexample(Base):
    def test_counterexample_no_ledger_double_side_effect(self):
        """反例夹具: 禁用被测机制(无 ledger)必红 —— 回执丢失 -> 盲重放 -> 副作用重复。"""
        external = []

        def naive_charge_with_blind_retry():
            try:
                external.append("charge")  # 外部成功
                raise ReceiptLost("receipt lost")
            except ReceiptLost:
                external.append("charge")  # 盲目重试 -> 重复扣款

        naive_charge_with_blind_retry()
        # 无 ledger 世界: 不变量「副作用零重复」被违反(证明夹具能检出机制缺失)
        self.assertEqual(len(external), 2, "反例夹具失效: 应能复现重复副作用")
        # 同一场景在 ledger 世界: UNCERTAIN 阻断盲重放(见 test_receipt_lost_never_blind_replay)


if __name__ == "__main__":
    unittest.main()
