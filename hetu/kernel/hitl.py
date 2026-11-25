"""L0 · HITL 持久挂起: interrupt 落盘, 进程重启不丢, interrupt_id 定向放行。"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any, Optional

from ..db import connect

PENDING = "PENDING"
RELEASED = "RELEASED"
REJECTED = "REJECTED"


class Interrupts:
    def __init__(self, db_path: str):
        self.db_path = db_path
        con = connect(db_path)
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS interrupts(
              interrupt_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, kind TEXT NOT NULL,
              payload TEXT NOT NULL, state TEXT NOT NULL, created_ts REAL NOT NULL,
              resolved_ts REAL, resolver TEXT);
            """
        )
        con.commit()
        con.close()

    def raise_interrupt(self, task_id: str, kind: str, payload: Any) -> str:
        iid = uuid.uuid4().hex
        con = connect(self.db_path)
        try:
            con.execute(
                "INSERT INTO interrupts(interrupt_id,task_id,kind,payload,state,created_ts)"
                " VALUES(?,?,?,?,?,?)",
                (iid, task_id, kind, json.dumps(payload, default=str), PENDING, time.time()))
            con.commit()
            return iid
        finally:
            con.close()

    def release(self, interrupt_id: str, resolver: str, approve: bool = True) -> None:
        con = connect(self.db_path)
        try:
            con.execute(
                "UPDATE interrupts SET state=?, resolved_ts=?, resolver=? WHERE interrupt_id=? AND state=?",
                (RELEASED if approve else REJECTED, time.time(), resolver,
                 interrupt_id, PENDING))
            con.commit()
        finally:
            con.close()

    def state(self, interrupt_id: str) -> Optional[str]:
        con = connect(self.db_path)
        try:
            r = con.execute("SELECT state FROM interrupts WHERE interrupt_id=?",
                            (interrupt_id,)).fetchone()
            return r["state"] if r else None
        finally:
            con.close()

    def pending(self) -> list[dict]:
        con = connect(self.db_path)
        try:
            return [dict(r) for r in con.execute(
                "SELECT * FROM interrupts WHERE state=? ORDER BY created_ts",
                (PENDING,)).fetchall()]
        finally:
            con.close()
