"""L1 · 哈希链证据账本: 每条证据含前链哈希, 篡改可检测。"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Optional

from ..db import connect

GENESIS = "0" * 64


def _row_hash(seq: int, ts: float, actor: str, event: str, detail: str, prev: str) -> str:
    h = hashlib.sha256()
    h.update(("%d|%.6f|%s|%s|%s|%s" % (seq, ts, actor, event, detail, prev)).encode())
    return h.hexdigest()


class EvidenceChain:
    def __init__(self, db_path: str):
        self.db_path = db_path
        con = connect(db_path)
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS evidence_chain(
              seq INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, actor TEXT NOT NULL,
              event TEXT NOT NULL, detail TEXT NOT NULL, prev_hash TEXT NOT NULL, hash TEXT NOT NULL);
            """
        )
        con.commit()
        con.close()

    def append(self, actor: str, event: str, detail: Optional[dict[str, Any]] = None) -> int:
        con = connect(self.db_path)
        try:
            # BEGIN IMMEDIATE: 取 prev_hash + 插入 + 回填哈希在同一写事务内完成,
            # 并发 append 被写锁串行化, 杜绝 prev_hash 竞态断链(深度检测 P1)。
            con.execute("BEGIN IMMEDIATE")
            try:
                last = con.execute(
                    "SELECT seq,hash FROM evidence_chain ORDER BY seq DESC LIMIT 1").fetchone()
                prev = last["hash"] if last else GENESIS
                ts = time.time()
                d = json.dumps(detail or {}, sort_keys=True, ensure_ascii=False, default=str)
                cur = con.execute(
                    "INSERT INTO evidence_chain(ts,actor,event,detail,prev_hash,hash)"
                    " VALUES(?,?,?,?,?,?)", (ts, actor, event, d, prev, ""))
                seq = cur.lastrowid
                h = _row_hash(seq, ts, actor, event, d, prev)
                con.execute("UPDATE evidence_chain SET hash=? WHERE seq=?", (h, seq))
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise
            return seq
        finally:
            con.close()

    def verify(self) -> tuple[bool, Optional[int]]:
        """返回 (完整?, 首个断点 seq)。篡改任意字段都会在此暴露。"""
        con = connect(self.db_path)
        try:
            rows = con.execute("SELECT * FROM evidence_chain ORDER BY seq").fetchall()
            prev = GENESIS
            for r in rows:
                if r["prev_hash"] != prev or r["hash"] != _row_hash(
                        r["seq"], r["ts"], r["actor"], r["event"], r["detail"], prev):
                    return False, r["seq"]
                prev = r["hash"]
            return True, None
        finally:
            con.close()

    def entries(self) -> list[dict]:
        con = connect(self.db_path)
        try:
            return [dict(r) for r in con.execute(
                "SELECT * FROM evidence_chain ORDER BY seq").fetchall()]
        finally:
            con.close()
