"""L2 · Durable 调度基座: 幂等槽 / 漏跑台账 / 重入 fencing / 断点重试 / 投递执行解耦。

单一真相源: 调度状态只在本库, 不建第二调度器。单机起步,
跨机时 claim 即租约+fencing token。调度精度为秒级(欠账清单: 亚分钟精度不做)。
"""
from __future__ import annotations

import sqlite3
import time
import uuid
from typing import Callable, Optional

from ..db import connect

POLICIES = ("coalesce", "per-run", "skip+alert")


class LeaseHeld(Exception):
    pass


class DurableScheduler:
    def __init__(self, db_path: str, alerts_path: Optional[str] = None):
        self.db_path = db_path
        self.alerts_path = alerts_path or (db_path + ".scheduler.alerts.log")
        con = connect(db_path)
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS jobs(
              job_id TEXT PRIMARY KEY, interval_sec REAL NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
              policy TEXT NOT NULL DEFAULT 'coalesce', last_fire REAL);
            CREATE TABLE IF NOT EXISTS job_slots(
              job_id TEXT NOT NULL, scheduled_instant REAL NOT NULL, trigger_type TEXT NOT NULL,
              state TEXT NOT NULL DEFAULT 'PENDING', fencing_token INTEGER NOT NULL DEFAULT 0,
              lease_owner TEXT, lease_expires REAL, attempts INTEGER NOT NULL DEFAULT 0,
              last_error TEXT, updated_ts REAL NOT NULL,
              PRIMARY KEY(job_id, scheduled_instant, trigger_type));
            CREATE TABLE IF NOT EXISTS fence_seq2(v INTEGER PRIMARY KEY CHECK(v=0), seq INTEGER NOT NULL);
            INSERT OR IGNORE INTO fence_seq2 VALUES (0,0);
            CREATE TABLE IF NOT EXISTS missed_ledger(
              id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL,
              scheduled_instant REAL NOT NULL, policy TEXT NOT NULL, handled INTEGER NOT NULL DEFAULT 0,
              created_ts REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS deliveries(
              delivery_id TEXT PRIMARY KEY, job_id TEXT NOT NULL, scheduled_instant REAL NOT NULL,
              trigger_type TEXT NOT NULL, delivered_ts REAL NOT NULL, acked INTEGER NOT NULL DEFAULT 0);
            """
        )
        con.commit()
        con.close()

    def _alert(self, msg: str) -> None:
        with open(self.alerts_path, "a", encoding="utf-8") as f:
            f.write("%.6f %s\n" % (time.time(), msg))

    # ---- 任务登记 ----
    def add_job(self, job_id: str, interval_sec: float, policy: str = "coalesce") -> None:
        if policy not in POLICIES:
            raise ValueError("policy must be one of %s" % (POLICIES,))
        con = connect(self.db_path)
        try:
            con.execute(
                "INSERT INTO jobs(job_id,interval_sec,policy) VALUES(?,?,?)"
                " ON CONFLICT(job_id) DO UPDATE SET interval_sec=excluded.interval_sec,"
                " policy=excluded.policy", (job_id, interval_sec, policy))
            con.commit()
        finally:
            con.close()

    def _job(self, job_id: str) -> dict:
        con = connect(self.db_path)
        try:
            r = con.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            if r is None:
                raise KeyError(job_id)
            return dict(r)
        finally:
            con.close()

    # ---- 幂等槽: 重复投递不产生第二份工作 ----
    def fire(self, job_id: str, scheduled_instant: float,
             trigger_type: str = "schedule") -> str:
        con = connect(self.db_path)
        try:
            try:
                con.execute(
                    "INSERT INTO job_slots(job_id,scheduled_instant,trigger_type,updated_ts)"
                    " VALUES(?,?,?,?)", (job_id, scheduled_instant, trigger_type, time.time()))
                con.commit()
                return "created"
            except sqlite3.IntegrityError:
                return "duplicate"
        finally:
            con.close()

    # ---- 漏跑台账 + 补跑策略 ----
    def catch_up(self, job_id: str, now: float) -> dict:
        job = self._job(job_id)
        last = job["last_fire"]
        if last is None:
            job_c = connect(self.db_path)
            job_c.execute("UPDATE jobs SET last_fire=? WHERE job_id=?", (now, job_id))
            job_c.commit()
            job_c.close()
            return {"created": 0, "missed": 0, "policy": job["policy"]}
        missed = []
        t = last + job["interval_sec"]
        while t <= now + 1e-9:
            missed.append(t)
            t += job["interval_sec"]
        if not missed:
            return {"created": 0, "missed": 0, "policy": job["policy"]}
        con = connect(self.db_path)
        created = 0
        try:
            policy = job["policy"]
            if policy == "coalesce":
                con.execute(
                    "INSERT OR IGNORE INTO job_slots(job_id,scheduled_instant,trigger_type,updated_ts)"
                    " VALUES(?,?,?,?)", (job_id, missed[-1], "coalesced", time.time()))
                created = 1
                for m in missed[:-1]:
                    con.execute(
                        "INSERT INTO missed_ledger(job_id,scheduled_instant,policy,handled,created_ts)"
                        " VALUES(?,?,?,1,?)", (job_id, m, policy, time.time()))
            elif policy == "per-run":
                for m in missed:
                    cur = con.execute(
                        "INSERT OR IGNORE INTO job_slots(job_id,scheduled_instant,trigger_type,updated_ts)"
                        " VALUES(?,?,?,?)", (job_id, m, "catchup", time.time()))
                    created += cur.rowcount
            else:  # skip+alert
                for m in missed:
                    con.execute(
                        "INSERT INTO missed_ledger(job_id,scheduled_instant,policy,handled,created_ts)"
                        " VALUES(?,?,?,1,?)", (job_id, m, policy, time.time()))
                self._alert("job %s skipped %d missed instants" % (job_id, len(missed)))
            con.execute("UPDATE jobs SET last_fire=? WHERE job_id=?", (missed[-1], job_id))
            con.commit()
            return {"created": created, "missed": len(missed), "policy": policy}
        finally:
            con.close()

    def missed_rows(self, job_id: Optional[str] = None) -> list[dict]:
        con = connect(self.db_path)
        try:
            if job_id:
                return [dict(r) for r in con.execute(
                    "SELECT * FROM missed_ledger WHERE job_id=? ORDER BY scheduled_instant",
                    (job_id,)).fetchall()]
            return [dict(r) for r in con.execute(
                "SELECT * FROM missed_ledger ORDER BY scheduled_instant").fetchall()]
        finally:
            con.close()

    # ---- 投递与执行解耦: 投递只记账, 执行方独立认领 ----
    def deliver(self, job_id: str, scheduled_instant: float,
                trigger_type: str = "schedule") -> str:
        did = uuid.uuid4().hex
        con = connect(self.db_path)
        try:
            con.execute(
                "INSERT INTO deliveries(delivery_id,job_id,scheduled_instant,trigger_type,delivered_ts)"
                " VALUES(?,?,?,?,?)", (did, job_id, scheduled_instant, trigger_type, time.time()))
            con.commit()
            return did
        finally:
            con.close()

    def ack(self, delivery_id: str) -> None:
        con = connect(self.db_path)
        try:
            con.execute("UPDATE deliveries SET acked=1 WHERE delivery_id=?", (delivery_id,))
            con.commit()
        finally:
            con.close()

    def unacked_deliveries(self) -> list[dict]:
        con = connect(self.db_path)
        try:
            return [dict(r) for r in con.execute(
                "SELECT * FROM deliveries WHERE acked=0").fetchall()]
        finally:
            con.close()

    # ---- 重入 fencing + 断点重试 ----
    def claim(self, job_id: str, scheduled_instant: float, trigger_type: str,
              owner: str, lease_ttl: float = 30.0) -> int:
        con = connect(self.db_path)
        try:
            # 读状态-检查-置 RUNNING 原子化(与 effect_ledger.acquire 同一课):
            # 否则两认领者都读到 PENDING, 双双拿到 token 重复执行。
            con.execute("BEGIN IMMEDIATE")
            try:
                now = time.time()
                r = con.execute(
                    "SELECT state,lease_expires FROM job_slots WHERE job_id=? AND scheduled_instant=?"
                    " AND trigger_type=?", (job_id, scheduled_instant, trigger_type)).fetchone()
                if r is None:
                    raise KeyError("no slot")
                if r["state"] == "RUNNING" and r["lease_expires"] and r["lease_expires"] > now:
                    raise LeaseHeld("slot held by live owner")
                con.execute("UPDATE fence_seq2 SET seq=seq+1 WHERE v=0")
                token = con.execute("SELECT seq FROM fence_seq2 WHERE v=0").fetchone()["seq"]
                con.execute(
                    "UPDATE job_slots SET state='RUNNING', fencing_token=?, lease_owner=?,"
                    " lease_expires=?, attempts=attempts+1, updated_ts=? WHERE job_id=?"
                    " AND scheduled_instant=? AND trigger_type=?",
                    (token, owner, now + lease_ttl, now, job_id, scheduled_instant, trigger_type))
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise
            return token
        finally:
            con.close()

    def run_slot(self, job_id: str, scheduled_instant: float, trigger_type: str,
                 owner: str, fn: Callable[[], None],
                 crash_after_effect: bool = False, lease_ttl: float = 30.0) -> str:
        token = self.claim(job_id, scheduled_instant, trigger_type, owner,
                           lease_ttl=lease_ttl)
        try:
            fn()
        except Exception as e:
            con = connect(self.db_path)
            try:
                con.execute(
                    "UPDATE job_slots SET state='FAILED', last_error=?, updated_ts=?,"
                    " lease_expires=NULL WHERE job_id=? AND scheduled_instant=?"
                    " AND trigger_type=? AND fencing_token=?",
                    (str(e), time.time(), job_id, scheduled_instant, trigger_type, token))
                con.commit()
            finally:
                con.close()
            return "FAILED"
        if crash_after_effect:
            raise RuntimeError("simulated crash after effect, before slot completion")
        con = connect(self.db_path)
        try:
            con.execute(
                "UPDATE job_slots SET state='DONE', updated_ts=?, lease_expires=NULL"
                " WHERE job_id=? AND scheduled_instant=? AND trigger_type=?"
                " AND fencing_token=?",
                (time.time(), job_id, scheduled_instant, trigger_type, token))
            con.commit()
            return "DONE"
        finally:
            con.close()

    def slot(self, job_id: str, scheduled_instant: float, trigger_type: str) -> dict:
        con = connect(self.db_path)
        try:
            return dict(con.execute(
                "SELECT * FROM job_slots WHERE job_id=? AND scheduled_instant=?"
                " AND trigger_type=?", (job_id, scheduled_instant, trigger_type)).fetchone())
        finally:
            con.close()

    def pending_slots(self) -> list[dict]:
        con = connect(self.db_path)
        try:
            return [dict(r) for r in con.execute(
                "SELECT * FROM job_slots WHERE state IN ('PENDING','FAILED')"
                " ORDER BY scheduled_instant").fetchall()]
        finally:
            con.close()
