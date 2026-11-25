"""L1 证据与观察层实验: 哈希链防篡改 / 独立探针结论门 / 滞回 stall / 沙箱白名单。"""
import os
import tempfile
import unittest

from hetu.evidence.chain import EvidenceChain
from hetu.evidence.probes import IndependentProbe, verdict
from hetu.evidence.stall import StallCounter
from hetu.kernel import sandbox


class TestEvidenceChain(unittest.TestCase):
    def setUp(self):
        self.db = os.path.join(tempfile.mkdtemp(prefix="hetu-l1-"), "hetu.db")
        self.chain = EvidenceChain(self.db)

    def test_chain_valid_then_tamper_detected(self):
        for i in range(5):
            self.chain.append("kernel", "event-%d" % i, {"i": i})
        ok, bad = self.chain.verify()
        self.assertTrue(ok)
        # 篡改第 3 条 detail
        import sqlite3
        con = sqlite3.connect(self.db)
        con.execute("UPDATE evidence_chain SET detail='{\"i\":999}' WHERE seq=3")
        con.commit(); con.close()
        ok, bad = self.chain.verify()
        self.assertFalse(ok)
        self.assertEqual(bad, 3)

    def test_probe_overrides_self_report(self):
        """自报绿≠实际绿: 自评与探针冲突时以探针为准; 无探针不给结论。"""
        lying_worker = True  # 执行体自称成功
        probe = IndependentProbe(sensor=lambda: "external-says-failed")
        res = probe.check(lambda obs: obs == "external-says-ok")
        self.assertFalse(verdict(lying_worker, res))   # 自评绿被探针否决
        self.assertFalse(verdict(True, None))          # 无独立探针 -> 不算绿
        honest = IndependentProbe(sensor=lambda: "external-says-ok")
        self.assertTrue(verdict(True, honest.check(lambda o: o == "external-says-ok")))

    def test_stall_hysteresis_triggers_only(self):
        sc = StallCounter(threshold=3)
        self.assertFalse(sc.tick(False))
        self.assertFalse(sc.tick(True))   # 有进展清零
        self.assertFalse(sc.tick(False))
        self.assertFalse(sc.tick(False))
        self.assertTrue(sc.tick(False))   # 连续第3拍触发 replan
        self.assertFalse(sc.tick(False))  # 已触发的滞回: 不重复轰炸
        sc.reset()
        self.assertTrue(all(sc.tick(False) is False for _ in range(2)))


class TestSandbox(unittest.TestCase):
    def test_whitelist_accepts_plain_json(self):
        obj = sandbox.safe_loads('{"a": [1, 2.5, true, null, "s"]}')
        self.assertEqual(obj["a"][0], 1)

    def test_rejects_magic_keys(self):
        with self.assertRaises(sandbox.UnsafePayload):
            sandbox.safe_loads('{"__reduce__": "evil"}')
        with self.assertRaises(sandbox.UnsafePayload):
            sandbox.validate({"nested": {"deep": {"__class__": "x"}}})


if __name__ == "__main__":
    unittest.main()
