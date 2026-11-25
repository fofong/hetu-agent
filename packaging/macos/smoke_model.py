"""Loopback HTTP fixture used by the desktop smoke run.

Supports both non-stream and stream modes (NDJSON for Ollama /api/chat, SSE for
/v1/chat/completions) and echoes the thinking-effort fields so the smoke can
assert the global effort setting actually reaches each transport:
  /api/chat            -> reply text carries "|think=<value>"
  /v1/chat/completions -> reply text carries "|eff=<reasoning_effort>"
The prompt 渲染测试 returns a Markdown reply (fenced code + bold + inline code).
"""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import time

MARKDOWN_REPLY = "```js\nconst x = 1\n```\n**加粗** 和 `行内码`"


def identity_echo(messages):
    """"身份测试" 检查请求是否携带 Hetu 身份系统提示词。"""
    head = messages[0] if messages else {}
    ok = head.get("role") == "system" and "Hetu super agent" in head.get("content", "")
    return "sys=1" if ok else "sys=0"


def chunked(text, parts=3):
    """Split a reply into N non-empty chunks to prove incremental streaming."""
    if len(text) < parts:
        return [text]
    size = len(text) // parts
    out = [text[i * size:(i + 1) * size] for i in range(parts - 1)]
    out.append(text[(parts - 1) * size:])
    return out


class Handler(BaseHTTPRequestHandler):
    def log_message(self, _format, *args):
        pass

    def send_json(self, payload):
        result = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(result)))
        self.end_headers()
        self.wfile.write(result)

    def stream_ndjson(self, text):
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        pieces = chunked(text)
        for index, piece in enumerate(pieces):
            payload = {"done": index == len(pieces) - 1,
                       "message": {"role": "assistant", "content": piece}}
            self.wfile.write((json.dumps(payload) + "\n").encode("utf-8"))
            self.wfile.flush()
            time.sleep(0.05)

    def stream_sse(self, text):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for piece in chunked(text):
            event = {"choices": [{"index": 0, "delta": {"content": piece},
                                  "finish_reason": None}]}
            self.wfile.write(b"data: " + json.dumps(event).encode("utf-8") + b"\n\n")
            self.wfile.flush()
            time.sleep(0.05)
        final = {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
        self.wfile.write(b"data: " + json.dumps(final).encode("utf-8") + b"\n\n")
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

    def do_GET(self):
        if self.path == "/api/tags":
            self.send_json({"models": [{"name": "fixture"}]})
        elif self.path == "/v1/models":
            self.send_json({"object": "list", "data": [{"id": "remote-fixture"}]})
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == "/v1/chat/completions":
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            last = payload["messages"][-1]["content"] if payload.get("messages") else ""
            if payload.get("model") != "remote-fixture":
                self.send_error(400)
                return
            if last == "渲染测试":
                text = MARKDOWN_REPLY
            elif last == "身份测试":
                text = identity_echo(payload.get("messages") or [])
            else:
                text = "远端回复:" + last + "|eff=" + str(payload.get("reasoning_effort", "-"))
            if payload.get("stream") is True:
                self.stream_sse(text)
            else:
                self.send_json({"choices": [
                    {"message": {"role": "assistant", "content": text}}]})
            return
        if self.path != "/api/chat":
            self.send_error(404)
            return
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        echo = "|think=" + str(payload.get("think", "-"))
        messages = [item for item in (payload.get("messages") or [])
                    if item.get("role") != "system"]
        first = {"role": "user", "content": "第一条测试消息"}
        second = {"role": "user", "content": "第二条测试消息"}
        reply1 = {"role": "assistant", "content": "第一轮回复" + echo}
        if payload["model"] != "fixture":
            self.send_error(400)
            return
        if messages == [first]:
            text = "第一轮回复" + echo
        elif messages == [first, reply1, second]:
            text = "第二轮回复" + echo
        elif messages and messages[-1].get("content") == "身份测试":
            text = identity_echo(payload.get("messages") or [])
        elif messages and messages[-1].get("content") == "渲染测试":
            text = MARKDOWN_REPLY
        else:
            self.send_error(400)
            return
        if payload.get("stream") is True:
            self.stream_ndjson(text)
        else:
            self.send_json({"done": True, "message": {"role": "assistant", "content": text}})


def smoke_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
