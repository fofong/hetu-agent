"""L0 · 反序列化白名单沙箱: 只允许 JSON 安全类型, 拒绝魔法键与越权类型。"""
from __future__ import annotations

import json
from typing import Any

ALLOWED_TYPES = (dict, list, str, int, float, bool, type(None))
FORBIDDEN_KEYS = {"__reduce__", "__reduce_ex__", "__class__", "__subclasses__",
                  "__globals__", "__builtins__", "__mro__", "__code__"}


class UnsafePayload(Exception):
    pass


def _check(obj: Any, path: str = "$") -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if not isinstance(k, str):
                raise UnsafePayload("non-str key at %s" % path)
            if k in FORBIDDEN_KEYS or (k.startswith("__") and k.endswith("__")):
                raise UnsafePayload("forbidden key %r at %s" % (k, path))
            _check(v, path + "." + k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _check(v, "%s[%d]" % (path, i))
    elif not isinstance(obj, ALLOWED_TYPES):
        raise UnsafePayload("type %s not whitelisted at %s" % (type(obj).__name__, path))


def safe_loads(text: str) -> Any:
    obj = json.loads(text)
    _check(obj)
    return obj


def validate(obj: Any) -> Any:
    _check(obj)
    return obj
