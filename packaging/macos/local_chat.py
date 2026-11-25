"""Model transports for the desktop composer: loopback Ollama and OpenAI-compatible hosts.

Thinking effort (思考程度) is a global default applied to every chat turn:
  auto            -> send nothing, follow the server default
  off/minimal/...max -> OpenAI hosts get reasoning_effort=none|minimal|...|max;
                        Ollama gets think=false for off and think=true for the
                        other explicit levels (no per-level knob in stable API).
Streaming: reply_stream() feeds on_delta(chunk) as tokens arrive and polls
should_stop() between chunks so the UI can cancel a long generation.
"""

import http.client
import json
import os
from urllib.parse import urlsplit

# 无内置远端：仅当部署显式配置环境变量时才提供远端通道（见 config.example）。
REMOTE_BASE_URL = os.environ.get("HETU_HOST66_BASE_URL", "")
MAX_HISTORY_CHARS = 8_000

try:  # canonical mapping lives in the kernel module; keep a local copy for bundle layouts
    from hetu.model import EFFORT_PARAM, SYSTEM_PROMPT, normalize_effort
except ImportError:  # pragma: no cover - standalone packaging/macos checkout
    EFFORT_PARAM = {"off": "none", "minimal": "minimal", "low": "low", "medium": "medium",
                    "high": "high", "xhigh": "xhigh", "max": "max"}
    SYSTEM_PROMPT = ("你是 Hetu super agent（河图超级智能体），由 HongYun 实验室开发维护。"
                     "当用户询问你的身份时，以此身份回答，不要自称底层模型。"
                     "用与用户一致的语言回复。")

    def normalize_effort(value):
        value = value.strip().lower() if isinstance(value, str) else ""
        return value if value in ("auto", "off", "minimal", "low", "medium",
                                  "high", "xhigh", "max") else "auto"


def _ollama_think(effort):
    """Ollama think flag for one effort token (None = omit the field)."""
    if effort == "off":
        return False
    return True if effort in EFFORT_PARAM else None


def bound_history(messages, max_chars=MAX_HISTORY_CHARS):
    """Keep the newest complete turns within a character budget; always keep the current ask."""
    if not messages:
        return []
    current = messages[-1]
    history = messages[:-1]
    retained = [current]
    used = 0
    while len(history) >= 2:
        pair = history[-2:]
        pair_chars = sum(len(item["content"]) for item in pair)
        if used + pair_chars > max_chars:
            break
        retained = pair + retained
        history = history[:-2]
        used += pair_chars
    return retained


class LocalChat:
    def __init__(self, port=11434):
        self.port = port

    def request(self, method, path, payload=None, timeout=5):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=timeout)
        try:
            body = json.dumps(payload).encode("utf-8") if payload is not None else None
            connection.request(method, path, body, {"Content-Type": "application/json"})
            response = connection.getresponse()
        except OSError as error:
            raise ValueError("无法连接 Ollama：%s" % error) from error
        try:
            if response.status != 200:
                raise ValueError("Ollama 返回 HTTP %d" % response.status)
            raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise ValueError("模型响应超过大小限制")
            return json.loads(raw)
        finally:
            connection.close()

    def models(self):
        result = self.request("GET", "/api/tags")
        return sorted({item["name"] for item in result["models"]
                       if isinstance(item.get("name"), str) and item["name"]})

    def _payload(self, model, messages, effort, stream):
        payload = {"model": model, "messages": messages, "stream": stream}
        think = _ollama_think(normalize_effort(effort))
        if think is not None:
            payload["think"] = think
        return payload

    def reply(self, model, messages, effort=None):
        result = self.request("POST", "/api/chat",
                              self._payload(model, messages, effort, False), timeout=90)
        reply = result["message"]["content"]
        if result.get("done") is not True or not isinstance(reply, str) or not reply.strip():
            raise ValueError("模型没有返回完整文本")
        return reply

    def reply_stream(self, model, messages, effort=None, on_delta=None, should_stop=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=90)
        parts, done = [], False
        try:
            connection.request("POST", "/api/chat",
                               json.dumps(self._payload(model, messages, effort, True)),
                               {"Content-Type": "application/json"})
            try:
                response = connection.getresponse()
            except OSError as error:
                raise ValueError("无法连接 Ollama：%s" % error) from error
            if response.status != 200:
                raise ValueError("Ollama 返回 HTTP %d" % response.status)
            for raw in response:
                if should_stop is not None and should_stop():
                    break
                line = raw.strip()
                if not line:
                    continue
                event = json.loads(line)
                chunk = (event.get("message") or {}).get("content")
                if isinstance(chunk, str) and chunk:
                    parts.append(chunk)
                    if on_delta is not None:
                        on_delta(chunk)
                if event.get("done") is True:
                    done = True
                    break
        finally:
            connection.close()
        text = "".join(parts)
        if not done and not text:
            raise ValueError("模型没有返回完整文本")
        return text


class OpenAIChat:
    """OpenAI-compatible transport for a configured remote host (/v1 endpoints)."""

    def __init__(self, base_url=None, api_key=None):
        base_url = base_url or REMOTE_BASE_URL
        if not base_url:
            raise ValueError("未配置模型服务地址：请设置 HETU_HOST66_BASE_URL 或在接入设置中添加")
        parts = urlsplit(base_url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ValueError("模型服务地址无效：%s" % base_url)
        self.scheme = parts.scheme
        self.host = parts.hostname
        self.port = parts.port or (443 if parts.scheme == "https" else 80)
        self.prefix = parts.path.rstrip("/")
        self.api_key = api_key or ""

    def request(self, method, path, payload=None, timeout=5):
        factory = (http.client.HTTPSConnection if self.scheme == "https"
                   else http.client.HTTPConnection)
        connection = factory(self.host, self.port, timeout=timeout)
        try:
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = "Bearer " + self.api_key
            body = json.dumps(payload).encode("utf-8") if payload is not None else None
            connection.request(method, path, body, headers)
            response = connection.getresponse()
        except OSError as error:
            raise ValueError("无法连接模型服务：%s" % error) from error
        try:
            if response.status != 200:
                raise ValueError("模型服务返回 HTTP %d" % response.status)
            raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise ValueError("模型响应超过大小限制")
            return json.loads(raw)
        finally:
            connection.close()

    def models(self):
        result = self.request("GET", self.prefix + "/models")
        return sorted({item["id"] for item in result["data"]
                       if isinstance(item.get("id"), str) and item["id"]})

    def _payload(self, model, messages, effort, stream):
        payload = {"model": model, "messages": messages, "stream": stream}
        token = EFFORT_PARAM.get(normalize_effort(effort))
        if token:
            payload["reasoning_effort"] = token
        return payload

    def reply(self, model, messages, effort=None):
        result = self.request("POST", self.prefix + "/chat/completions",
                              self._payload(model, messages, effort, False), timeout=120)
        choices = result.get("choices") or []
        reply = choices[0].get("message", {}).get("content") if choices else None
        if not isinstance(reply, str) or not reply.strip():
            raise ValueError("模型没有返回完整文本")
        return reply

    def reply_stream(self, model, messages, effort=None, on_delta=None, should_stop=None):
        """Consume an SSE /chat/completions stream; returns the accumulated text."""
        factory = (http.client.HTTPSConnection if self.scheme == "https"
                   else http.client.HTTPConnection)
        connection = factory(self.host, self.port, timeout=120)
        parts, done = [], False
        try:
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = "Bearer " + self.api_key
            connection.request("POST", self.prefix + "/chat/completions",
                               json.dumps(self._payload(model, messages, effort, True)),
                               headers)
            try:
                response = connection.getresponse()
            except OSError as error:
                raise ValueError("无法连接模型服务：%s" % error) from error
            if response.status != 200:
                raise ValueError("模型服务返回 HTTP %d" % response.status)
            for raw in response:
                if should_stop is not None and should_stop():
                    break
                line = raw.strip()
                if not line.startswith(b"data:"):
                    continue
                data = line[len(b"data:"):].strip()
                if data == b"[DONE]":
                    done = True
                    break
                try:
                    event = json.loads(data)
                except ValueError:
                    continue
                choices = event.get("choices") or []
                if not choices:
                    continue
                if choices[0].get("finish_reason"):
                    done = True
                chunk = (choices[0].get("delta") or {}).get("content")
                if isinstance(chunk, str) and chunk:
                    parts.append(chunk)
                    if on_delta is not None:
                        on_delta(chunk)
        finally:
            connection.close()
        text = "".join(parts)
        if not done and not text:
            raise ValueError("模型没有返回完整文本")
        return text
