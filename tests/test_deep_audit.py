"""深度结构审计回归测试: 逐模块代码审查抓出的三个真实缺陷(P1/P2/P3)。

每个测试对应一个探针先证红、修复后转绿的缺陷:
  P1 证据链并发 append 断链        -> chain.append BEGIN IMMEDIATE
  P2 评分器篡改评分时刻无感        -> ScorerVault.score 前置完整性校验
  P3 CONFIRMED 效果可被重复执行    -> acquire 拒绝 CONFIRMED(AlreadyConfirmed)
"""
import os
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hetu.evidence.chain import EvidenceChain
from hetu.evolution.evolve import ScorerTamper, ScorerVault
from hetu.kernel.effect_ledger import (AlreadyConfirmed, CONFIRMED, EffectLedger)


class TestP1ChainConcurrency(unittest.TestCase):
    def test_concurrent_append_keeps_chain_intact(self):
        db = os.path.join(tempfile.mkdtemp(prefix="audit-p1-"), "c.db")
        chain = EvidenceChain(db)

        def app(i):
            for j in range(5):
                chain.append("t%d" % i, "ev", {"j": j})

        ts = [threading.Thread(target=app, args=(i,)) for i in range(8)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        ok, break_at = chain.verify()
        self.assertTrue(ok, "chain broken at seq %s under concurrent append" % break_at)
        self.assertEqual(len(chain.entries()), 40)


class TestP2ScorerTamperAtScoreTime(unittest.TestCase):
    def test_tampered_scorer_refused_at_score(self):
        vd = tempfile.mkdtemp(prefix="audit-p2-")
        vault = ScorerVault(vd, admin_token="admin-1")
        vault.install_scorer("s1", "def score(x): return 1.0", "admin-1")
        with open(os.path.join(vd, "s1.py"), "w") as f:
            f.write("def score(x): return 999.0")
        ev = vault.as_evolver()
        with self.assertRaises(ScorerTamper):
            ev.score("s1", {})


class TestP3ConfirmedNoReexecute(unittest.TestCase):
    def test_confirmed_effect_cannot_be_reacquired(self):
        db = os.path.join(tempfile.mkdtemp(prefix="audit-p3-"), "e.db")
        led = EffectLedger(db)
        led.intent("pay", {}, "k1")
        tok = led.acquire("k1", "w1")
        led.execute("k1", "w1", tok, lambda: "wire-1")
        self.assertEqual(led.state("k1"), CONFIRMED)
        runs = []
        with self.assertRaises(AlreadyConfirmed):
            tok2 = led.acquire("k1", "w2")
            led.execute("k1", "w2", tok2, lambda: runs.append(1) or "wire-2")
        self.assertEqual(runs, [], "CONFIRMED 效果被再次执行 = 重复副作用")


if __name__ == "__main__":
    unittest.main(verbosity=2)
