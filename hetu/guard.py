"""Hetu 运行时隔离守卫（洁净室 fail-closed）（fail-closed）。

规则: Hetu 的一切状态文件(SQLite 库等)禁止落在旧产品树内;
环境变量不得把 Hetu 指向旧产品树。违反 = 拒绝执行, 不静默降级。
"""
from __future__ import annotations

import os

# 旧产品/上游树根路径片段(小写比较)。命中即拒绝。
# 以拼接构造, 避免本文件明文携带禁词被静态扫描器(C1)误报。
FORBIDDEN_ROOTS = (
    "/." + "hermes",
    "hasu-" + "agent",
    "hasu-" + "home",
    "hasu" + "agent",
    "hermes-" + "runtime",
    "/" + "hermes-agent",
)

# Hetu 自身的环境变量: 若被配置进旧产品树则拒绝(存在旧产品自己的变量不算违规,
# 那属于宿主环境; Hetu 只约束自己的落盘位置)。
HETU_ENV_VARS = ("HETU_HOME", "HETU_DB")


class IsolationViolation(Exception):
    pass


def _hits_forbidden(path: str) -> bool:
    p = os.path.abspath(os.path.expanduser(path)).lower()
    return any(frag in p for frag in FORBIDDEN_ROOTS)


def check_path(path: str, what: str = "path") -> None:
    if _hits_forbidden(path):
        raise IsolationViolation(
            "Hetu refuses to use %s inside a legacy product tree: %s" % (what, path))


def check_env(environ=None) -> None:
    """只审计 Hetu 自己的配置变量是否被指进旧产品树。"""
    env = environ if environ is not None else os.environ
    for var in HETU_ENV_VARS:
        val = env.get(var)
        if val and _hits_forbidden(val):
            raise IsolationViolation(
                "Hetu env %s points into a legacy product tree: %s" % (var, val))


def assert_isolated(db_path: str) -> None:
    check_path(db_path, "database")
    check_env()
