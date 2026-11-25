"""L0 · step_writes 任务级幂等: 确定性 task_id, 先写后 checkpoint。

与 Effect Ledger 组合后覆盖「外部成功但 checkpoint 前崩溃」窗口:
重放时 ledger 已 CONFIRMED -> 跳过外部效果, 直接补记 step。
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Callable

from ..db import connect


def deterministic_task_id(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8"))
        h.update(b"\x1f")
    return h.hexdigest()[:32]


class StepWrites:
    def __init__(self, db_path: str):
        self.db_path = db_path
        con = connect(db_path)
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS step_writes(
              step_key TEXT PRIMARY KEY, task_id TEXT NOT NULL, step_id TEXT NOT NULL,
              result TEXT NOT NULL, result_hash TEXT NOT NULL, created_ts REAL NOT NULL);
            """
        )
        con.commit()
        con.close()

    def get(self, task_id: str, step_id: str):
        con = connect(self.db_path)
        try:
            r = con.execute("SELECT result FROM step_writes WHERE step_key=?",
                            (f"{task_id}:{step_id}",)).fetchone()
            return json.loads(r["result"]) if r else None
        finally:
            con.close()

    def run(self, task_id: str, step_id: str, effect: Callable[[], Any],
            crash_after_effect_before_write: bool = False) -> Any:
        """幂等执行一步。已存在则直接返回既有结果(零副作用重放)。"""
        key = f"{task_id}:{step_id}"
        cached = self.get(task_id, step_id)
        if cached is not None:
            return cached
        result = effect()
        if crash_after_effect_before_write:
            raise CrashInjected("simulated crash after external effect, before step write")
        con = connect(self.db_path)
        try:
            con.execute(
                "INSERT OR IGNORE INTO step_writes(step_key,task_id,step_id,result,result_hash,created_ts)"
                " VALUES(?,?,?,?,?,?)",
                (key, task_id, step_id, json.dumps(result, default=str),
                 hashlib.sha256(json.dumps(result, default=str).encode()).hexdigest(),
                 time.time()))
            con.commit()
        finally:
            con.close()
        return result


class CrashInjected(Exception):
    pass
