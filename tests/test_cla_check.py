"""CLA 签署通道（scripts/cla_check.py）反例驱动测试：签署判定、幂等、豁免。"""
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from scripts.cla_check import (add_signature, check, is_signature_comment,
                               load_signatures)


class TestPhrase(unittest.TestCase):
    def test_en_phrase(self):
        self.assertTrue(is_signature_comment(
            "I have read the CLA Document and I hereby sign the CLA."))

    def test_cn_phrase(self):
        self.assertTrue(is_signature_comment(
            "我已阅读 CLA 文档（docs/CLA.md）并确认签署 CLA！"))

    def test_near_miss_rejected(self):
        # 反例：近似但不精确的语句必须拒绝（禁假通过）
        self.assertFalse(is_signature_comment("I agree to the CLA"))
        self.assertFalse(is_signature_comment("I hereby sign"))
        self.assertFalse(is_signature_comment(""))


class TestCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "cla-signatures.json")

    def test_unsigned_fails(self):
        ok, _ = check("alice", load_signatures(self.path), "fofong")
        self.assertFalse(ok)

    def test_owner_exempt(self):
        ok, _ = check("fofong", load_signatures(self.path), "fofong")
        self.assertTrue(ok)

    def test_bot_exempt(self):
        ok, _ = check("dependabot[bot]", load_signatures(self.path), "fofong")
        self.assertTrue(ok)

    def test_signed_passes(self):
        add_signature(self.path, "alice", "123", "https://x/1")
        ok, _ = check("alice", load_signatures(self.path), "fofong")
        self.assertTrue(ok)

    def test_empty_login_fails(self):
        ok, _ = check("", load_signatures(self.path), "fofong")
        self.assertFalse(ok)


class TestAdd(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "cla-signatures.json")

    def test_add_then_file_valid(self):
        add_signature(self.path, "bob", "42", "https://x/2")
        data = load_signatures(self.path)
        self.assertEqual(len(data["signatures"]), 1)
        self.assertEqual(data["signatures"][0]["login"], "bob")
        self.assertIn("date", data["signatures"][0])

    def test_add_idempotent(self):
        add_signature(self.path, "bob", "42", "https://x/2")
        r = add_signature(self.path, "bob", "42", "https://x/3")
        self.assertEqual(r["action"], "exists")
        self.assertEqual(len(load_signatures(self.path)["signatures"]), 1)

    def test_corrupt_file_rejected(self):
        with open(self.path, "w") as f:
            f.write('{"nope": 1}')
        with self.assertRaises(ValueError):
            load_signatures(self.path)


if __name__ == "__main__":
    unittest.main()
