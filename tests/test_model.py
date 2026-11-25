"""hetu.model client: stub-server unit tests + optional live test.

仓库内不内置任何端点：活体测试仅在环境显式提供 HETU_MODEL_BASE_URL 时运行。
"""

import json
import os
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from hetu import model


class _Stub(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path.endswith("/models"):
            body = json.dumps({"data": [{"id": "stub-a"}, {"id": "stub-b"}]}).encode()
            self.send_response(200)
        else:
            self.send_response(404)
            return
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if payload.get("model") != "stub-a" or not payload.get("messages"):
            self.send_response(400)
            self.end_headers()
            return
        last = payload["messages"][-1]["content"]
        if last == "身份检查":
            head = payload["messages"][0]
            ok = (head.get("role") == "system"
                  and "Hetu super agent" in head.get("content", ""))
            content = "sys=1" if ok else "sys=0"
        else:
            suffix = ("|eff=" + str(payload["reasoning_effort"])
                      if "reasoning_effort" in payload else "")
            content = "回声:" + last + suffix
        body = json.dumps({"choices": [{"message": {
            "role": "assistant", "content": content}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)


class ModelClientTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _Stub)
        cls.thread = __import__("threading").Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = "http://127.0.0.1:%d/v1" % cls.server.server_port

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_discover_and_reply(self):
        client = model.ModelClient(base_url=self.base)
        self.assertEqual(client.discover(), ["stub-a", "stub-b"])
        self.assertEqual(client.reply([{"role": "user", "content": "你好"}], model="stub-a"),
                         "回声:你好")

    def test_bad_base_url(self):
        with self.assertRaises(model.ModelError):
            model.ModelClient(base_url="not-a-url")

    def test_unreachable_status(self):
        with self.assertRaises(model.ModelError):
            model.ModelClient(base_url="http://127.0.0.1:1/v1", timeout=1).discover()

    def test_normalize_effort(self):
        for effort in model.EFFORTS:
            with self.subTest(effort=effort):
                self.assertEqual(model.normalize_effort(" " + effort.upper() + " "), effort)
        self.assertEqual(model.normalize_effort("bogus"), "auto")
        self.assertEqual(model.normalize_effort(None), "auto")

    def test_reply_effort_injection(self):
        msgs = [{"role": "user", "content": "你好"}]
        client = model.ModelClient(base_url=self.base)
        self.assertEqual(client.reply(msgs, model="stub-a"), "回声:你好")
        self.assertEqual(client.reply(msgs, model="stub-a", effort="auto"), "回声:你好")
        for effort, token in model.EFFORT_PARAM.items():
            with self.subTest(effort=effort):
                self.assertEqual(client.reply(msgs, model="stub-a", effort=effort),
                                 "回声:你好|eff=" + token)

    def test_reply_carries_identity_system_prompt(self):
        client = model.ModelClient(base_url=self.base)
        msgs = [{"role": "user", "content": "身份检查"}]
        self.assertEqual(client.reply(msgs, model="stub-a"), "sys=1")
        # 调用方自带 system 时不重复注入、不覆盖
        custom = [{"role": "system", "content": "自定义"}, *msgs]
        self.assertEqual(client.reply(custom, model="stub-a"), "sys=0")

    def test_config_effort_from_env(self):
        import os
        from unittest import mock
        with mock.patch.dict(os.environ, {"HETU_MODEL_EFFORT": "medium"}):
            self.assertEqual(model.config()["effort"], "medium")
        with mock.patch.dict(os.environ, {"HETU_MODEL_EFFORT": "bogus"}):
            self.assertEqual(model.config()["effort"], "auto")
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(model.config()["effort"], "auto")


_LIVE_CONFIGURED = bool(os.environ.get("HETU_MODEL_BASE_URL"))


@unittest.skipUnless(_LIVE_CONFIGURED, "活体测试需环境提供 HETU_MODEL_BASE_URL")
class LiveModelTest(unittest.TestCase):
    def test_live_roundtrip(self):
        status = model.status()
        self.assertTrue(status["reachable"], status)
        self.assertTrue(status["has_default"], status)
        reply = model.ModelClient().reply(
            [{"role": "user", "content": "只回复四个字：接入成功"}])
        self.assertTrue(reply.strip())


if __name__ == "__main__":
    unittest.main()
