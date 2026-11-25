"""L0 · plan-hash 恢复点校验: 计划漂移拒续, 转人工。"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Optional

from ..db import connect


class PlanDrift(Exception):
    pass


def plan_hash(plan: Any) -> str:
    return hashlib.sha256(json.dumps(plan, sort_keys=True, ensure_ascii=False,
                                      default=str).encode()).hexdigest()


class RecoveryPoints:
    def __init__(self, db_path: str):
        self.db_path = db_path
        con = connect(db_path)
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS recovery_points(
              task_id TEXT PRIMARY KEY, plan_hash TEXT NOT NULL, state TEXT NOT NULL,
              created_ts REAL NOT NULL);
            """
        )
        con.commit()
        con.close()

    def save(self, task_id: str, plan: Any, state: Any) -> str:
        h = plan_hash(plan)
        con = connect(self.db_path)
        try:
            con.execute(
                "INSERT INTO recovery_points(task_id,plan_hash,state,created_ts) VALUES(?,?,?,?)"
                " ON CONFLICT(task_id) DO UPDATE SET plan_hash=excluded.plan_hash,"
                " state=excluded.state, created_ts=excluded.created_ts",
                (task_id, h, json.dumps(state, default=str), time.time()))
            con.commit()
            return h
        finally:
            con.close()

    def resume(self, task_id: str, plan: Any, enforce: bool = True) -> Any:
        """恢复执行前校验 plan-hash。enforce=False 为反例(禁用校验)。漂移 -> 拒续转人工。"""
        con = connect(self.db_path)
        try:
            r = con.execute("SELECT plan_hash,state FROM recovery_points WHERE task_id=?",
                            (task_id,)).fetchone()
            if r is None:
                raise KeyError(task_id)
            if enforce and r["plan_hash"] != plan_hash(plan):
                raise PlanDrift("plan drifted for task %s: refuse to resume, escalate" % task_id)
            return json.loads(r["state"])
        finally:
            con.close()
