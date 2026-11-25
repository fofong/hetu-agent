"""Kernel-side OpenAI-compatible model client (stdlib only).

No remote endpoint is built in: a deployment must configure one explicitly
(see config.example). Environment:

  HETU_MODEL_BASE_URL  OpenAI-compatible base URL ending at /v1 (required)
  HETU_MODEL_NAME      default model id on that host (optional)
  HETU_MODEL_API_KEY   default empty (LAN hosts often have no auth)
  HETU_MODEL_EFFORT    global default thinking effort: auto|off|minimal|low|
                       medium|high|xhigh|max (default auto omits the parameter)
"""

import http.client
import json
import os
from urllib.parse import urlsplit

DEFAULT_BASE_URL = ""
DEFAULT_MODEL = ""
MAX_REPLY_CHARS = 50_000

# 全局默认思考程度: auto 不下发参数(跟随服务默认), 其余映射为 OpenAI 兼容的
# reasoning_effort 取值。档位参照前作（none/minimal/low/medium/high/xhigh/max）；
# llama.cpp 实测支持 minimal|low|medium|high|xhigh|max|none，ultra 被拒故不收。
EFFORTS = ("auto", "off", "minimal", "low", "medium", "high", "xhigh", "max")
DEFAULT_EFFORT = "auto"
EFFORT_PARAM = {"off": "none", "minimal": "minimal", "low": "low", "medium": "medium",
                "high": "high", "xhigh": "xhigh", "max": "max"}

# 桌面/内核对话统一身份：模型默认会自称基座模型，必须显式声明产品身份。
SYSTEM_PROMPT = ("你是 Hetu super agent（河图超级智能体），由 HongYun 实验室开发维护。"
                 "当用户询问你的身份时，以此身份回答，不要自称底层模型。"
                 "用与用户一致的语言回复。")


def normalize_effort(value):
    """Coerce any input to a known effort token; unknown values fall back to auto."""
    value = value.strip().lower() if isinstance(value, str) else ""
    return value if value in EFFORTS else DEFAULT_EFFORT


class ModelError(RuntimeError):
    pass


def config():
    return {
        "base_url": os.environ.get("HETU_MODEL_BASE_URL", DEFAULT_BASE_URL),
        "model": os.environ.get("HETU_MODEL_NAME", DEFAULT_MODEL),
        "api_key": os.environ.get("HETU_MODEL_API_KEY", ""),
        "effort": normalize_effort(os.environ.get("HETU_MODEL_EFFORT", DEFAULT_EFFORT)),
    }


class ModelClient:
    def __init__(self, base_url=None, api_key=None, timeout=90):
        cfg = config()
        base_url = base_url or cfg["base_url"]
        if not base_url:
            raise ModelError("未配置模型服务地址：请设置 HETU_MODEL_BASE_URL（见 config.example）")
        parts = urlsplit(base_url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ModelError("模型服务地址无效：%s" % base_url)
        self.scheme = parts.scheme
        self.host = parts.hostname
        self.port = parts.port or (443 if parts.scheme == "https" else 80)
        self.prefix = parts.path.rstrip("/")
        self.api_key = api_key if api_key is not None else cfg["api_key"]
        self.timeout = timeout

    def _request(self, method, path, payload=None, timeout=None):
        factory = (http.client.HTTPSConnection if self.scheme == "https"
                   else http.client.HTTPConnection)
        connection = factory(self.host, self.port, timeout=timeout or self.timeout)
        try:
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = "Bearer " + self.api_key
            body = json.dumps(payload).encode("utf-8") if payload is not None else None
            connection.request(method, path, body, headers)
            response = connection.getresponse()
            if response.status != 200:
                raise ModelError("模型服务返回 HTTP %d" % response.status)
            raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise ModelError("模型响应超过大小限制")
            return json.loads(raw)
        except (OSError, ValueError) as error:
            raise ModelError("模型服务不可达：%s" % error) from error
        finally:
            connection.close()

    def discover(self):
        result = self._request("GET", self.prefix + "/models", timeout=8)
        return sorted({item["id"] for item in result.get("data", [])
                       if isinstance(item.get("id"), str) and item["id"]})

    def reply(self, messages, model=None, effort=None):
        cfg = config()
        if not messages or messages[0].get("role") != "system":
            messages = [{"role": "system", "content": SYSTEM_PROMPT}] + list(messages)
        payload = {
            "model": model or cfg["model"],
            "messages": messages,
            "stream": False,
        }
        token = EFFORT_PARAM.get(effort or cfg["effort"])
        if token:
            payload["reasoning_effort"] = token
        result = self._request("POST", self.prefix + "/chat/completions", payload)
        choices = result.get("choices") or []
        text = choices[0].get("message", {}).get("content") if choices else None
        if not isinstance(text, str) or not text.strip():
            raise ModelError("模型没有返回完整文本")
        if len(text) > MAX_REPLY_CHARS:
            raise ModelError("模型回复超过 %d 字符" % MAX_REPLY_CHARS)
        return text


def status():
    cfg = config()
    out = {"base_url": cfg["base_url"], "model": cfg["model"],
           "effort": cfg["effort"], "reachable": False, "models": []}
    if not cfg["base_url"]:
        out["error"] = "未配置模型服务地址（HETU_MODEL_BASE_URL）"
        return out
    try:
        out["models"] = ModelClient().discover()
        out["reachable"] = True
        out["has_default"] = cfg["model"] in out["models"]
    except ModelError as error:
        out["error"] = str(error)
    return out
