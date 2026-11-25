"""记忆与云同步桥接 (memory_cloud) tests — no network, no pyobjc, fake CLI."""

import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest

_HERE = Path(__file__).resolve()
for _cand in (_HERE.parents[1] / "packaging" / "macos", _HERE.parents[2]):
    if (_cand / "memory_cloud.py").is_file():   # repo layout / built-app layout
        sys.path.insert(0, str(_cand))
        break

import memory_cloud  # noqa: E402

STATUS = {
    "schema": "memorax_cloud_sync.v1",
    "config_path": "/tmp/config.json",
    "sources": [{"name": "personal-memory", "path": "/tmp/x", "exists": True, "file_count": 3}],
    "providers": {
        "icloud": {"enabled": False, "ready": True, "destination": "/tmp/icloud"},
        "gdrive": {"enabled": False, "ready": False, "hint": "装 Google Drive"},
    },
    "log_tail": ["2026-11-18 synced 11 files"],
}

FAKE = """#!/bin/sh
case "$1" in
  status) echo '%s' ;;
  enable|disable) echo "$1 $2 ok" ;;
  sync) echo "synced 1 file(s)" ;;
  fail) echo "boom" >&2; exit 3 ;;
esac
""" % json.dumps(STATUS, ensure_ascii=False)


class FakeCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cli = Path(self.tmp.name) / "memorax-cloud-sync"
        self.cli.write_text(FAKE, encoding="utf-8")
        self.cli.chmod(self.cli.stat().st_mode | stat.S_IEXEC)
        self._saved = os.environ.get(memory_cloud.ENV_CLI)
        os.environ[memory_cloud.ENV_CLI] = str(self.cli)

    def tearDown(self):
        if self._saved is None:
            os.environ.pop(memory_cloud.ENV_CLI, None)
        else:
            os.environ[memory_cloud.ENV_CLI] = self._saved
        self.tmp.cleanup()


class StatusTests(FakeCliTests):
    def test_status_parses_json(self):
        data = memory_cloud.status()
        self.assertNotIn("error", data)
        self.assertEqual(data["schema"], "memorax_cloud_sync.v1")
        self.assertEqual(data["sources"][0]["file_count"], 3)
        self.assertFalse(data["providers"]["gdrive"]["ready"])

    def test_missing_cli_returns_error(self):
        os.environ[memory_cloud.ENV_CLI] = str(Path(self.tmp.name) / "nope")
        data = memory_cloud.status()
        self.assertIn("error", data)


class ToggleTests(FakeCliTests):
    def test_toggle_returns_fresh_status(self):
        data = memory_cloud.set_enabled("icloud", True)
        self.assertNotIn("error", data)
        self.assertIn("providers", data)

    def test_rejects_unknown_provider(self):
        self.assertIn("error", memory_cloud.set_enabled("dropbox", True))

    def test_rejects_non_bool_switch(self):
        self.assertIn("error", memory_cloud.set_enabled("icloud", "yes"))


class SyncTests(FakeCliTests):
    def test_sync_ok(self):
        result = memory_cloud.sync("icloud")
        self.assertTrue(result.get("ok"))
        self.assertIn("synced", " ".join(result["output"]))

    def test_sync_all_providers(self):
        self.assertTrue(memory_cloud.sync().get("ok"))

    def test_sync_rejects_unknown_provider(self):
        self.assertIn("error", memory_cloud.sync("dropbox"))


if __name__ == "__main__":
    unittest.main()
