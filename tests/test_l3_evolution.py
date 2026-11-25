"""L3 演化层脚手架实验: 评分器物理隔离 / 演化体无写路径 / 晋级门 / 心跳断点续算。"""
import os
import tempfile
import unittest

from hetu.evolution.evolve import (
    EvolverView, ExperimentTree, PromotionGateFailed, ScorerTamper, ScorerVault,
)
from hetu.kernel.heartbeat import Heartbeat

SCORER_CODE = "def score(sample):\n    return float(sum(sample))\n"


class TestScorerIsolation(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="hetu-l3-")
        self.vault = ScorerVault(os.path.join(self.dir, "vault"), admin_token="supervisor-token")
        self.vault.install_scorer("sum_scorer", SCORER_CODE, "supervisor-token")

    def test_install_requires_admin_token(self):
        with self.assertRaises(ScorerTamper):
            self.vault.install_scorer("evil", "def score(s): return 1e9", "wrong-token")

    def test_evolver_view_readonly(self):
        ev = self.vault.as_evolver()
        self.assertIsInstance(ev, EvolverView)
        self.assertFalse(hasattr(ev, "install_scorer"))  # 演化体物理上无写路径
        self.assertEqual(ev.score("sum_scorer", [1, 2, 3]), 6.0)

    def test_tampered_scorer_detected(self):
        path = os.path.join(self.vault.vault_dir, "sum_scorer.py")
        with open(path, "w") as f:  # 绕过 API 直接改文件(reward hacking 模拟)
            f.write("def score(sample):\n    return 1e9\n")
        self.assertFalse(self.vault.verify_integrity())


class TestPromotionGate(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="hetu-l3p-")
        self.db = os.path.join(self.dir, "hetu.db")
        self.vault = ScorerVault(os.path.join(self.dir, "vault"), admin_token="tok")
        self.vault.install_scorer("s", SCORER_CODE, "tok")
        self.tree = ExperimentTree(self.db, supervisor_secret="avatar-signature",
                                   vault=self.vault)

    def test_prompt_only_mutation_rejected(self):
        with self.assertRaises(ValueError):
            self.tree.spawn(None, "prompt-only")

    def test_promotion_requires_repro_improvement_and_signature(self):
        parent = self.tree.spawn(None, "logic")
        self.tree.record_result(parent, {"score": 0.5}, reproducible=True)
        child = self.tree.spawn(parent, "logic")
        self.tree.record_result(child, {"score": 0.6}, reproducible=True)
        with self.assertRaises(PromotionGateFailed):
            self.tree.promote(child, "forged-signature")           # 无外部监督者签名
        self.tree.promote(child, "avatar-signature")               # Avatar 独立验收
        con = __import__("sqlite3").connect(self.db)
        st = con.execute("SELECT status FROM experiments WHERE experiment_id=?",
                         (child,)).fetchone()[0]
        con.close()
        self.assertEqual(st, "PROMOTED")

    def test_no_improvement_blocked(self):
        parent = self.tree.spawn(None, "tools")
        self.tree.record_result(parent, {"score": 0.7}, reproducible=True)
        child = self.tree.spawn(parent, "tools")
        self.tree.record_result(child, {"score": 0.7}, reproducible=True)
        with self.assertRaises(PromotionGateFailed):
            self.tree.promote(child, "avatar-signature")

    def test_not_reproducible_blocked(self):
        exp = self.tree.spawn(None, "skills")
        self.tree.record_result(exp, {"score": 0.9}, reproducible=False)
        with self.assertRaises(PromotionGateFailed):
            self.tree.promote(exp, "avatar-signature")


class TestHeartbeat(unittest.TestCase):
    def test_resume_from_last_checkpoint(self):
        db = os.path.join(tempfile.mkdtemp(prefix="hetu-hb-"), "hetu.db")
        hb = Heartbeat(db)
        hb.beat("t1", {"cursor": 7})
        fresh = Heartbeat(db)  # 进程重启
        self.assertEqual(fresh.resume("t1"), {"cursor": 7})
        self.assertFalse(fresh.stale("t1", ttl=5))
        self.assertIsNone(fresh.resume("unknown"))


if __name__ == "__main__":
    unittest.main()
