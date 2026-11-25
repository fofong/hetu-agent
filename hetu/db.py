"""SQLite 连接基座: WAL + busy_timeout, 单一真相源(单库文件)。"""
from __future__ import annotations

import sqlite3

from .guard import assert_isolated


def connect(path: str) -> sqlite3.Connection:
    assert_isolated(path)  # 与旧 旧产品（HongYun 前作） 树严格隔离: 违反即拒绝, 不静默
    con = sqlite3.connect(path, timeout=10.0, isolation_level=None)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=FULL")
    except sqlite3.DatabaseError:
        # 损坏库上 PRAGMA 也可能失败, 交由上层 _guarded 处理
        pass
    con.execute("PRAGMA busy_timeout=10000")
    con.execute("PRAGMA foreign_keys=ON")
    return con
