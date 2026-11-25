"""大模型接入管理: provider registry for the desktop composer.

A provider = one model service endpoint the chat can call:
  kind "openai"  -> OpenAI-compatible host (base_url ends at /v1)
  kind "ollama"  -> local Ollama daemon (127.0.0.1:<port>)

Persisted as JSON (Providers.json) next to Workspace.json. The api_key lives
only on disk in this file; every view handed to the webview is masked.
Stdlib only, importable by tests without pyobjc.
"""

import json
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

VERSION = 1
KINDS = {"ollama": "Ollama", "openai": "OpenAI 兼容"}
MAX_PROVIDERS = 16
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
MASK_PREFIX = "••••"


def defaults():
    """Built-in registry used when Providers.json is absent or unreadable.

    Only loopback Ollama is built in. A remote OpenAI-compatible host is
    offered solely when the deployment sets HETU_HOST66_BASE_URL; nothing
    internal is hardcoded (see config.example).
    """
    providers = [
        {"id": "ollama", "name": "本机 Ollama", "kind": "ollama",
         "base_url": "http://127.0.0.1:11434", "api_key": "", "enabled": True},
    ]
    default = "ollama"
    remote_url = os.environ.get("HETU_HOST66_BASE_URL", "")
    if remote_url:
        providers.append(
            {"id": "remote", "name": "局域网 OpenAI 兼容", "kind": "openai",
             "base_url": remote_url,
             "api_key": os.environ.get("HETU_HOST66_API_KEY", ""), "enabled": True})
        default = "remote"
    return {"version": VERSION, "default": default, "providers": providers}


def validate(config):
    """Raise ValueError on anything the engine must not persist."""
    if not isinstance(config, dict) or not isinstance(config.get("providers"), list):
        raise ValueError("接入配置格式不正确")
    providers = config["providers"]
    if not 1 <= len(providers) <= MAX_PROVIDERS:
        raise ValueError("接入数量需在 1~%d 个之间" % MAX_PROVIDERS)
    seen = set()
    for item in providers:
        if not isinstance(item, dict):
            raise ValueError("接入条目格式不正确")
        pid = item.get("id")
        if not isinstance(pid, str) or not ID_RE.match(pid):
            raise ValueError("接入 ID 需为小写字母开头的字母数字下划线短横线组合")
        if pid in seen:
            raise ValueError("接入 ID 重复：%s" % pid)
        seen.add(pid)
        name = item.get("name")
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 40:
            raise ValueError("接入名称需为 1~40 字符")
        if item.get("kind") not in KINDS:
            raise ValueError("类型仅支持 Ollama 或 OpenAI 兼容")
        base = item.get("base_url")
        parts = urlsplit(base) if isinstance(base, str) else None
        if parts is None or parts.scheme not in ("http", "https") or not parts.netloc:
            raise ValueError("服务地址需为 http(s) URL")
        key = item.get("api_key", "")
        if not isinstance(key, str) or len(key) > 512:
            raise ValueError("API Key 超长")
        if not isinstance(item.get("enabled"), bool):
            raise ValueError("启用状态格式不正确")
    default = config.get("default")
    if default is not None and default not in seen:
        raise ValueError("默认接入不存在")
    return config


def mask(config):
    """Copy safe to hand to the webview: api_key replaced by a placeholder."""
    out = json.loads(json.dumps(config))
    for item in out.get("providers", []):
        key = item.get("api_key") or ""
        item["api_key"] = "" if not key else MASK_PREFIX + key[-4:]
    return out


def merge_keys(incoming, current):
    """A masked api_key in an edit keeps the stored key; blank clears it."""
    old = {item["id"]: item for item in current.get("providers", [])
           if isinstance(item, dict) and isinstance(item.get("id"), str)}
    out = json.loads(json.dumps(incoming))
    for item in out.get("providers", []):
        if not isinstance(item, dict):
            continue
        key = item.get("api_key") or ""
        if key.startswith(MASK_PREFIX):
            item["api_key"] = old.get(item.get("id"), {}).get("api_key", "")
        else:
            item["api_key"] = key
    return out


def load(path):
    """Read the registry; returns (config, error). Missing file -> defaults."""
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return defaults(), None
    except (OSError, ValueError) as failure:
        return defaults(), "无法读取接入配置，已使用默认值：%s" % failure
    try:
        return validate(raw), None
    except ValueError as failure:
        return defaults(), "接入配置无效，已使用默认值：%s" % failure


def save(path, config):
    """Atomic write: temp file in the same directory, then replace."""
    validate(config)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(config, ensure_ascii=False, indent=2)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False, mode="w",
                                     encoding="utf-8") as stream:
        scratch = Path(stream.name)
        stream.write(payload)
    try:
        scratch.replace(path)
    except OSError:
        scratch.unlink(missing_ok=True)
        raise


def client_for(config_item):
    """Build the transport for one provider entry (validated entry assumed)."""
    from local_chat import LocalChat, OpenAIChat
    if config_item["kind"] == "ollama":
        port = urlsplit(config_item["base_url"]).port or 11434
        return LocalChat(port)
    return OpenAIChat(config_item["base_url"], config_item.get("api_key", ""))
