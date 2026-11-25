"""L0 · heartbeat 断点续算: 心跳+检查点持久化, 崩溃后从最后检查点继续。"""
from __future__ import annotations

import json
import time
from typing import Any, Optional

from ..db import connect


class Heartbeat:
    def __init__(self, db_path: str):
        self.db_path = db_path
        con = connect(db_path)
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS heartbeats(
              task_id TEXT PRIMARY KEY, last_beat REAL NOT NULL, checkpoint TEXT NOT NULL);
            """
        )
        con.commit()
        con.close()

    def beat(self, task_id: str, checkpoint: Any) -> None:
        con = connect(self.db_path)
        try:
            con.execute(
                "INSERT INTO heartbeats(task_id,last_beat,checkpoint) VALUES(?,?,?)"
                " ON CONFLICT(task_id) DO UPDATE SET last_beat=excluded.last_beat,"
                " checkpoint=excluded.checkpoint",
                (task_id, time.time(), json.dumps(checkpoint, default=str)))
            con.commit()
        finally:
            con.close()

    def resume(self, task_id: str) -> Optional[Any]:
        con = connect(self.db_path)
        try:
            r = con.execute("SELECT checkpoint FROM heartbeats WHERE task_id=?",
                            (task_id,)).fetchone()
            return json.loads(r["checkpoint"]) if r else None
        finally:
            con.close()

    def stale(self, task_id: str, ttl: float) -> bool:
        con = connect(self.db_path)
        try:
            r = con.execute("SELECT last_beat FROM heartbeats WHERE task_id=?",
                            (task_id,)).fetchone()
            return r is None or (time.time() - r["last_beat"]) > ttl
        finally:
            con.close()
