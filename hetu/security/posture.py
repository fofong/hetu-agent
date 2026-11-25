"""安全态势: ACTIVE / FROZEN 单行持久态。FROZEN = 冻结区语义——
高风险与无显式允许的动作全部 DENY, 演化类动作由调用方按 get() 自行保守。
读取失败(库损坏/表缺失)一律按 FROZEN 处理: 态势不可知 = 冻结, 不静默放行。"""
from __future__ import annotations

import time
from typing import Optional

from ..db import connect

ACTIVE = "ACTIVE"
FROZEN = "FROZEN"


class SecurityPosture:
    def __init__(self, db_path: str, chain=None):
        self.db_path = db_path
        self.chain = chain
        con = connect(db_path)
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS security_posture(
              id INTEGER PRIMARY KEY CHECK(id=1), mode TEXT NOT NULL,
              reason TEXT, ts REAL NOT NULL);
            """
        )
        con.execute("INSERT OR IGNORE INTO security_posture(id,mode,reason,ts)"
                    " VALUES(1,?,?,?)", (ACTIVE, "init", time.time()))
        con.commit()
        con.close()

    def get(self) -> str:
        try:
            con = connect(self.db_path)
            try:
                row = con.execute(
                    "SELECT mode FROM security_posture WHERE id=1").fetchone()
                mode = row["mode"] if row else FROZEN
                return mode if mode in (ACTIVE, FROZEN) else FROZEN
            finally:
                con.close()
        except Exception:
            return FROZEN  # fail-closed: 态势读不到 = 冻结

    def freeze(self, reason: str, operator: str = "system") -> str:
        self._set(FROZEN, reason, operator)
        return FROZEN

    def resume(self, reason: str, operator: str) -> str:
        # 解冻必须有明确操作人——匿名解冻本身就是门禁违规。
        if not operator or not str(operator).strip():
            raise ValueError("resume requires a named operator")
        self._set(ACTIVE, reason, operator)
        return ACTIVE

    def _set(self, mode: str, reason: str, operator: str) -> None:
        con = connect(self.db_path)
        try:
            con.execute("INSERT INTO security_posture(id,mode,reason,ts) VALUES(1,?,?,?)"
                        " ON CONFLICT(id) DO UPDATE SET mode=excluded.mode,"
                        " reason=excluded.reason, ts=excluded.ts",
                        (mode, reason, time.time()))
            con.commit()
        finally:
            con.close()
        if self.chain:
            self.chain.append("security", "posture.%s" % mode.lower(),
                              {"reason": reason, "operator": operator})

    def audit(self) -> Optional[dict]:
        con = connect(self.db_path)
        try:
            row = con.execute("SELECT * FROM security_posture WHERE id=1").fetchone()
            return dict(row) if row else None
        finally:
            con.close()
