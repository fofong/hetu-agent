"""大模型接入管理 (model_providers) registry tests — no network, no pyobjc."""

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

_HERE = Path(__file__).resolve()
for _cand in (_HERE.parents[1] / "packaging" / "macos", _HERE.parents[2]):
    if (_cand / "model_providers.py").is_file():   # repo layout / built-app layout
        sys.path.insert(0, str(_cand))
        break

import model_providers  # noqa: E402


def entry(**over):
    item = {"id": "p1", "name": "测试接入", "kind": "openai",
            "base_url": "http://127.0.0.1:9/v1", "api_key": "", "enabled": True}
    item.update(over)
    return item


def config(*providers, default=None):
    return {"version": model_providers.VERSION, "default": default,
            "providers": list(providers)}


class ValidateTests(unittest.TestCase):
    def test_defaults_valid(self):
        model_providers.validate(model_providers.defaults())

    def test_rejects_duplicate_id(self):
        with self.assertRaises(ValueError):
            model_providers.validate(config(entry(), entry(name="另一个")))

    def test_rejects_bad_kind(self):
        with self.assertRaises(ValueError):
            model_providers.validate(config(entry(kind="grpc")))

    def test_rejects_non_http_url(self):
        for bad in ("ftp://x/y", "not a url", "", "://x"):
            with self.assertRaises(ValueError):
                model_providers.validate(config(entry(base_url=bad)))

    def test_rejects_bad_id(self):
        for bad in ("P1", "-x", "带中文", "", "a" * 33):
            with self.assertRaises(ValueError):
                model_providers.validate(config(entry(id=bad)))

    def test_rejects_empty_and_oversized_list(self):
        with self.assertRaises(ValueError):
            model_providers.validate(config())
        many = [entry(id="p%d" % i) for i in range(model_providers.MAX_PROVIDERS + 1)]
        with self.assertRaises(ValueError):
            model_providers.validate({"version": 1, "default": None, "providers": many})

    def test_rejects_missing_default(self):
        with self.assertRaises(ValueError):
            model_providers.validate(config(entry(), default="ghost"))

    def test_rejects_non_bool_enabled(self):
        with self.assertRaises(ValueError):
            model_providers.validate(config(entry(enabled="yes")))


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(prefix="hetu-providers-")
        self.addCleanup(self.dir.cleanup)
        self.path = Path(self.dir.name) / "Providers.json"

    def test_missing_file_gives_defaults(self):
        cfg, error = model_providers.load(self.path)
        self.assertIsNone(error)
        self.assertEqual([p["id"] for p in cfg["providers"]], ["ollama"])

    def test_defaults_add_remote_only_when_env_configured(self):
        with mock.patch.dict(os.environ, {"HETU_HOST66_BASE_URL": "http://10.0.0.1:1234/v1"}):
            cfg = model_providers.defaults()
        self.assertEqual([p["id"] for p in cfg["providers"]], ["ollama", "remote"])
        self.assertEqual(cfg["default"], "remote")

    def test_save_load_roundtrip(self):
        cfg = config(entry(name="公司网关", api_key="sk-secret-123"), default="p1")
        model_providers.save(self.path, cfg)
        loaded, error = model_providers.load(self.path)
        self.assertIsNone(error)
        self.assertEqual(loaded, cfg)
        self.assertEqual(loaded["default"], "p1")

    def test_corrupt_file_falls_back_with_error(self):
        self.path.write_text("{not json", encoding="utf-8")
        cfg, error = model_providers.load(self.path)
        self.assertIsNotNone(error)
        self.assertEqual([p["id"] for p in cfg["providers"]], ["ollama"])

    def test_invalid_content_falls_back_with_error(self):
        self.path.write_text(json.dumps(config(entry(kind="nope"))), encoding="utf-8")
        cfg, error = model_providers.load(self.path)
        self.assertIsNotNone(error)
        self.assertEqual([p["id"] for p in cfg["providers"]], ["ollama"])

    def test_save_rejects_invalid_without_touching_file(self):
        good = config(entry())
        model_providers.save(self.path, good)
        with self.assertRaises(ValueError):
            model_providers.save(self.path, config(entry(kind="nope")))
        loaded, error = model_providers.load(self.path)
        self.assertIsNone(error)
        self.assertEqual(loaded, good)


class MaskMergeTests(unittest.TestCase):
    def test_mask_hides_key_but_keeps_tail(self):
        masked = model_providers.mask(config(entry(api_key="sk-secret-1234")))
        key = masked["providers"][0]["api_key"]
        self.assertTrue(key.startswith(model_providers.MASK_PREFIX))
        self.assertEqual(key[-4:], "1234")
        self.assertNotIn("secret", key)

    def test_mask_keeps_empty_key_empty(self):
        masked = model_providers.mask(config(entry(api_key="")))
        self.assertEqual(masked["providers"][0]["api_key"], "")

    def test_masked_key_merges_back_to_stored(self):
        current = config(entry(api_key="sk-real"))
        incoming = config(entry(api_key=model_providers.MASK_PREFIX + "real"))
        merged = model_providers.merge_keys(incoming, current)
        self.assertEqual(merged["providers"][0]["api_key"], "sk-real")

    def test_new_key_replaces_and_blank_clears(self):
        current = config(entry(api_key="sk-real"))
        replaced = model_providers.merge_keys(config(entry(api_key="sk-new")), current)
        self.assertEqual(replaced["providers"][0]["api_key"], "sk-new")
        cleared = model_providers.merge_keys(config(entry(api_key="")), current)
        self.assertEqual(cleared["providers"][0]["api_key"], "")

    def test_masked_key_for_unknown_id_becomes_empty(self):
        merged = model_providers.merge_keys(
            config(entry(id="ghost", api_key=model_providers.MASK_PREFIX + "abcd")),
            config(entry()))
        self.assertEqual(merged["providers"][0]["api_key"], "")


class ClientTests(unittest.TestCase):
    def test_client_for_kinds(self):
        from local_chat import LocalChat, OpenAIChat
        self.assertIsInstance(
            model_providers.client_for(entry(kind="ollama", base_url="http://127.0.0.1:11434")),
            LocalChat)
        client = model_providers.client_for(entry(base_url="http://example.test:1234/v1",
                                                  api_key="k"))
        self.assertIsInstance(client, OpenAIChat)
        self.assertEqual(client.port, 1234)
        self.assertEqual(client.api_key, "k")


if __name__ == "__main__":
    unittest.main()
