"""local_chat transports: effort mapping, SSE/NDJSON streaming, mid-stream stop.

No network beyond a loopback stub; resolves local_chat.py in BOTH repo layout
and built-app layout (the in-app tests job runs from the bundle).
"""

import json
from pathlib import Path
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_HERE = Path(__file__).resolve()
for _cand in (_HERE.parents[1] / "packaging" / "macos", _HERE.parents[2]):
    if (_cand / "local_chat.py").is_file():   # repo layout / built-app layout
        sys.path.insert(0, str(_cand))
        break

import local_chat  # noqa: E402


class _Stub(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _payload(self):
        return json.loads(self.rfile.read(int(self.headers["Content-Length"])))

    def _json(self, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _lines(self, pieces, wrap):
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for index, piece in enumerate(pieces):
                self.wfile.write(wrap(piece, index == len(pieces) - 1))
                self.wfile.flush()
                threading.Event().wait(0.05)
        except (BrokenPipeError, ConnectionResetError):
            pass  # client stopped early on purpose

    def do_POST(self):
        payload = self._payload()
        if self.path == "/api/chat":
            messages = payload.get("messages") or []
            last = messages[-1].get("content") if messages else ""
            if last == "停止测试":
                pieces = list("0123456789")
            else:
                pieces = ["AB", "CD", "|think=" + str(payload.get("think", "-"))]
            if payload.get("stream") is True:
                self._lines(pieces, lambda piece, last:
                            (json.dumps({"done": last,
                                         "message": {"role": "assistant",
                                                     "content": piece}}) + "\n").encode())
            else:
                self._json({"done": True, "message": {"role": "assistant",
                            "content": "".join(pieces)}})
            return
        if self.path == "/v1/chat/completions":
            pieces = ["AB", "CD", "|eff=" + str(payload.get("reasoning_effort", "-"))]
            if payload.get("stream") is True:
                def wrap(piece, last):
                    event = {"choices": [{"index": 0,
                                          "delta": {"content": piece},
                                          "finish_reason": "stop" if last else None}]}
                    return b"data: " + json.dumps(event).encode() + b"\n\n"
                self._lines(pieces, wrap)
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
            else:
                self._json({"choices": [{"message": {"role": "assistant",
                                         "content": "".join(pieces)}}]})
            return
        self.send_error(404)


class EffortMappingTests(unittest.TestCase):
    def test_ollama_think_flag(self):
        self.assertIs(local_chat._ollama_think("off"), False)
        for effort in ("minimal", "low", "medium", "high", "xhigh", "max"):
            with self.subTest(effort=effort):
                self.assertIs(local_chat._ollama_think(effort), True)
        self.assertIsNone(local_chat._ollama_think("auto"))

    def test_normalize_falls_back_to_auto(self):
        self.assertEqual(local_chat.normalize_effort(" LOW "), "low")
        self.assertEqual(local_chat.normalize_effort("bogus"), "auto")
        self.assertEqual(local_chat.normalize_effort(None), "auto")


class HistoryBudgetTests(unittest.TestCase):
    def test_bounds_history_to_recent_complete_turns_and_keeps_current_message(self):
        messages = [
            {"role": "user", "content": "old " * 1000},
            {"role": "assistant", "content": "old answer"},
            {"role": "user", "content": "recent " * 500},
            {"role": "assistant", "content": "recent answer"},
            {"role": "user", "content": "current"},
        ]

        bounded = local_chat.bound_history(messages, max_chars=5000)

        self.assertEqual([item["role"] for item in bounded], ["user", "assistant", "user"])
        self.assertEqual(bounded[0]["content"], "recent " * 500)
        self.assertEqual(bounded[-1]["content"], "current")

    def test_keeps_current_message_even_when_it_exceeds_budget(self):
        current = {"role": "user", "content": "x" * 6000}
        self.assertEqual(local_chat.bound_history([current], max_chars=100), [current])


class TransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _Stub)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.port = cls.server.server_port

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def ollama(self):
        return local_chat.LocalChat(port=self.port)

    def remote(self):
        return local_chat.OpenAIChat(base_url="http://127.0.0.1:%d/v1" % self.port)

    def test_ollama_stream_aggregates_and_maps_effort(self):
        deltas = []
        text = self.ollama().reply_stream("m", [{"role": "user", "content": "x"}],
                                          effort="low", on_delta=deltas.append)
        self.assertEqual(text, "ABCD|think=True")
        self.assertEqual(deltas, ["AB", "CD", "|think=True"])

    def test_ollama_auto_omits_think_and_off_disables(self):
        auto = self.ollama().reply_stream("m", [{"role": "user", "content": "x"}],
                                          effort="auto")
        self.assertEqual(auto, "ABCD|think=-")
        off = self.ollama().reply("m", [{"role": "user", "content": "x"}], effort="off")
        self.assertEqual(off, "ABCD|think=False")

    def test_ollama_stop_returns_partial_text(self):
        seen = []
        text = self.ollama().reply_stream("m", [{"role": "user", "content": "停止测试"}],
                                          on_delta=seen.append,
                                          should_stop=lambda: len(seen) >= 2)
        self.assertEqual(text, "01")

    def test_ollama_http_error(self):
        with self.assertRaises(ValueError):
            local_chat.LocalChat(port=1).reply("m", [{"role": "user", "content": "x"}])

    def test_openai_sse_aggregates_and_maps_effort(self):
        deltas = []
        text = self.remote().reply_stream("m", [{"role": "user", "content": "x"}],
                                          effort="off", on_delta=deltas.append)
        self.assertEqual(text, "ABCD|eff=none")
        self.assertEqual(deltas, ["AB", "CD", "|eff=none"])

    def test_openai_auto_sends_no_reasoning_effort(self):
        text = self.remote().reply_stream("m", [{"role": "user", "content": "x"}],
                                          effort="auto")
        self.assertEqual(text, "ABCD|eff=-")

    def test_openai_nonstream_reply(self):
        for effort, token in local_chat.EFFORT_PARAM.items():
            with self.subTest(effort=effort):
                text = self.remote().reply("m", [{"role": "user", "content": "x"}],
                                           effort=effort)
                self.assertEqual(text, "ABCD|eff=" + token)

    def test_identity_prompt_constant(self):
        self.assertIn("Hetu super agent", local_chat.SYSTEM_PROMPT)
        self.assertIn("HongYun", local_chat.SYSTEM_PROMPT)

    def test_openai_bad_base_url(self):
        with self.assertRaises(ValueError):
            local_chat.OpenAIChat(base_url="not-a-url")


if __name__ == "__main__":
    unittest.main()
