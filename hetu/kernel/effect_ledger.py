"""L0 · Durable Effect Ledger —— Hetu 之「因」的核心。

每个外部副作用 = 意图持久化 -> 执行(租约+fencing token) -> 独立核验三态提交:
  CONFIRMED  外部效果已核验
  UNCERTAIN  外部可能已发生(如回执丢失), 先对账, 禁盲重放
  PAUSED     高风险动作转人工(HITL)
Ledger 自身故障降级语义: 仅显式声明 reversible 的纯记录/可逆操作 fail-open+告警;
不可逆外部副作用(默认)与高风险一律 fail-closed。孤儿 EXECUTING(租约过期)必须先对账,
禁止盲接管(防"外部已成功+回执未持久化"组合下的重复副作用)。
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

from ..db import connect
from ..evidence.chain import EvidenceChain

CONFIRMED = "CONFIRMED"
UNCERTAIN = "UNCERTAIN"
PAUSED = "PAUSED"
FAILED = "FAILED"
INTENT = "INTENT"
EXECUTING = "EXECUTING"


class LedgerCorrupted(Exception):
    pass


class LeaseHeld(Exception):
    pass


class NotReconciled(Exception):
    pass


class AlreadyConfirmed(Exception):
    """效果已 CONFIRMED: 重放必须读回执, 严禁再次执行(深度检测 P3)。"""


class HighRiskPaused(Exception):
    pass


class ReceiptLost(Exception):
    """外部执行成功但回执丢失 —— A1 关键反例夹具。"""


class AlertLog:
    """fail-open 告警落盘(单机文件, 不外发)。"""

    def __init__(self, path: str):
        self.path = path

    def alert(self, msg: str) -> None:
        with open(self.path, "a", encoding="utf-8") as f:
            f.write("%.6f %s\n" % (time.time(), msg))


def _payload_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()


class EffectLedger:
    def __init__(self, db_path: str, alerts_path: Optional[str] = None,
                 chain: Optional[EvidenceChain] = None):
        self.db_path = db_path
        self.chain = chain
        self.alerts = AlertLog(alerts_path or (db_path + ".alerts.log"))
        self.fail_open_alerts: list[str] = []
        self._init()

    def _init(self) -> None:
        con = connect(self.db_path)
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS fence_seq(v INTEGER PRIMARY KEY CHECK(v=0), seq INTEGER NOT NULL);
            INSERT OR IGNORE INTO fence_seq VALUES (0,0);
            CREATE TABLE IF NOT EXISTS effect_ledger(
              idem_key TEXT PRIMARY KEY, action TEXT NOT NULL, payload_hash TEXT NOT NULL,
              risk TEXT NOT NULL DEFAULT 'normal', state TEXT NOT NULL,
              fencing_token INTEGER NOT NULL DEFAULT 0, lease_owner TEXT, lease_expires REAL,
              attempts INTEGER NOT NULL DEFAULT 0, receipt TEXT,
              intent_ts REAL, commit_ts REAL);
            """
        )
        con.commit()
        con.close()

    # ---- ledger 自身故障注入钩子(测试用) ----
    def _con(self) -> sqlite3.Connection:
        return connect(self.db_path)

    def corrupt(self) -> None:
        """模拟 ledger 盘损坏: 用垃圾覆盖文件头。"""
        with open(self.db_path, "r+b") as f:
            head = f.read(64)
            f.seek(0)
            f.write(b"\x00" * len(head))

    def _guarded(self, fn: Callable, fail_closed: bool):
        try:
            return fn()
        except sqlite3.DatabaseError as e:
            msg = "effect-ledger corrupted, fail-%s: %s" % (
                "closed" if fail_closed else "open", e)
            self.alerts.alert(msg)
            self.fail_open_alerts.append(msg)
            if fail_closed:
                raise LedgerCorrupted(msg) from e
            return None  # fail-open 仅限显式声明可逆的操作; 调用方按 None 绕过 ledger

    # ---- 三态提交主流程 ----
    def intent(self, action: str, payload: Any, idem_key: str, risk: str = "normal",
               reversible: bool = False) -> str:
        """reversible=False(默认): 视为不可逆外部副作用, ledger 写失败时 fail-closed。
        仅显式 reversible=True(纯记录/可逆操作)才允许 fail-open。"""
        fail_closed = (risk == "high") or (not reversible)
        def _do():
            con = self._con()
            try:
                con.execute("BEGIN IMMEDIATE")  # 查-插原子, 并发 intent 不竞态
                try:
                    row = con.execute(
                        "SELECT state FROM effect_ledger WHERE idem_key=?",
                        (idem_key,)).fetchone()
                    if row:
                        con.execute("COMMIT")
                        return row["state"]  # 幂等: 重复 intent 不重复登记
                    state = PAUSED if risk == "high" else INTENT
                    con.execute(
                        "INSERT INTO effect_ledger(idem_key,action,payload_hash,risk,state,intent_ts)"
                        " VALUES(?,?,?,?,?,?)",
                        (idem_key, action, _payload_hash(payload), risk, state, time.time()))
                    con.execute("COMMIT")
                except Exception:
                    con.execute("ROLLBACK")
                    raise
                if self.chain:
                    self.chain.append("kernel", "effect.intent",
                                      {"idem_key": idem_key, "action": action, "risk": risk})
                return state
            finally:
                con.close()
        out = self._guarded(_do, fail_closed)
        return out if out is not None else "BYPASSED_FAILOPEN"

    def acquire(self, idem_key: str, owner: str, lease_ttl: float = 30.0) -> int:
        """租约 + fencing token: 并发执行者只有一个能拿到递增 token。

        BEGIN IMMEDIATE: 读状态-检查-置 EXECUTING 必须原子。否则两执行者都读到
        INTENT 后先后覆写 token, 双双通过 fencing 校验导致重复执行(M2 并发双跑
        偶发 DONE+DONE 的根因)。
        """
        con = self._con()
        try:
            con.execute("BEGIN IMMEDIATE")
            try:
                now = time.time()
                row = con.execute(
                    "SELECT state,lease_expires FROM effect_ledger WHERE idem_key=?",
                    (idem_key,)).fetchone()
                if row is None:
                    raise KeyError(idem_key)
                if row["state"] == PAUSED:
                    raise HighRiskPaused(idem_key)
                if row["state"] == CONFIRMED:
                    raise AlreadyConfirmed(
                        "%s already CONFIRMED; replay must read the receipt, not re-execute"
                        % idem_key)
                if row["state"] == UNCERTAIN:
                    raise NotReconciled(idem_key)  # UNCERTAIN 禁盲重放
                if row["state"] == EXECUTING:
                    if not row["lease_expires"] or row["lease_expires"] > now:
                        raise LeaseHeld(idem_key)
                    # 孤儿(执行者疑似死亡): 禁盲接管, 必须先经探针对账
                    raise NotReconciled(idem_key)
                con.execute("UPDATE fence_seq SET seq=seq+1 WHERE v=0")
                token = con.execute("SELECT seq FROM fence_seq WHERE v=0").fetchone()["seq"]
                con.execute(
                    "UPDATE effect_ledger SET state=?, fencing_token=?, lease_owner=?,"
                    " lease_expires=?, attempts=attempts+1 WHERE idem_key=?",
                    (EXECUTING, token, owner, now + lease_ttl, idem_key))
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise
            return token
        finally:
            con.close()

    def execute(self, idem_key: str, owner: str, token: int,
                effect: Callable[[], Any]) -> str:
        """执行外部副作用。effect 返回回执; 抛 ReceiptLost 表示外部可能已成功。"""
        con = self._con()
        try:
            row = con.execute(
                "SELECT fencing_token,state FROM effect_ledger WHERE idem_key=?",
                (idem_key,)).fetchone()
            if row["fencing_token"] != token:
                raise LeaseHeld("stale fencing token %s for %s" % (token, idem_key))
            try:
                receipt = effect()
            except ReceiptLost:
                con.execute("UPDATE effect_ledger SET state=? WHERE idem_key=?",
                            (UNCERTAIN, idem_key))
                con.commit()
                if self.chain:
                    self.chain.append("kernel", "effect.uncertain", {"idem_key": idem_key})
                return UNCERTAIN
            con.execute(
                "UPDATE effect_ledger SET state=?, receipt=?, commit_ts=?, lease_expires=NULL"
                " WHERE idem_key=?",
                (CONFIRMED, json.dumps(receipt, default=str), time.time(), idem_key))
            con.commit()
            if self.chain:
                self.chain.append("kernel", "effect.confirmed", {"idem_key": idem_key})
            return CONFIRMED
        finally:
            con.close()

    def reconcile(self, idem_key: str, probe: Callable[[], Optional[Any]]) -> str:
        """UNCERTAIN/孤儿 EXECUTING 对账: 独立探针查外部真实状态, 只有确认未发生才允许重放。"""
        con = self._con()
        try:
            row = con.execute(
                "SELECT state,lease_expires FROM effect_ledger WHERE idem_key=?", (idem_key,)).fetchone()
            if row["state"] not in (UNCERTAIN, EXECUTING):
                return row["state"]
            if row["state"] == EXECUTING and row["lease_expires"] \
                    and row["lease_expires"] > time.time():
                raise LeaseHeld(idem_key)  # 执行者仍活跃, 不得抢先对账
            found = probe()
            if found is not None:
                con.execute(
                    "UPDATE effect_ledger SET state=?, receipt=?, commit_ts=? WHERE idem_key=?",
                    (CONFIRMED, json.dumps(found, default=str), time.time(), idem_key))
                con.commit()
                if self.chain:
                    self.chain.append("kernel", "effect.reconciled",
                                      {"idem_key": idem_key, "outcome": "confirmed"})
                return CONFIRMED
            # 外部确认未发生 -> 回到 INTENT 允许受控重放(仍需重新 acquire)
            con.execute("UPDATE effect_ledger SET state=?, lease_owner=NULL,"
                        " lease_expires=NULL WHERE idem_key=?", (INTENT, idem_key))
            con.commit()
            if self.chain:
                self.chain.append("kernel", "effect.reconciled",
                                  {"idem_key": idem_key, "outcome": "absent_replay_allowed"})
            return INTENT
        finally:
            con.close()

    def release_high_risk(self, idem_key: str) -> None:
        """人工放行 PAUSED 高风险动作。"""
        con = self._con()
        try:
            con.execute("UPDATE effect_ledger SET state=? WHERE idem_key=? AND state=?",
                        (INTENT, idem_key, PAUSED))
            con.commit()
        finally:
            con.close()

    def state(self, idem_key: str) -> Optional[str]:
        con = self._con()
        try:
            r = con.execute("SELECT state FROM effect_ledger WHERE idem_key=?",
                            (idem_key,)).fetchone()
            return r["state"] if r else None
        finally:
            con.close()

    def orphans(self, stale_seconds: float = 60.0) -> list[dict]:
        """孤儿 action: 意图已持久化但执行者消失(租约过期仍 EXECUTING)。"""
        con = self._con()
        try:
            rows = con.execute(
                "SELECT idem_key,action,fencing_token FROM effect_ledger"
                " WHERE state=? AND (lease_expires IS NULL OR lease_expires < ?)",
                (EXECUTING, time.time() - 0)).fetchall()
            return [dict(r) for r in rows]
        finally:
            con.close()
