"""动作策略门: glob 规则 + 优先级, 默认拒绝。

fail-closed 三则:
  1. 无匹配规则 -> DENY (否决 ARTEX「规则未匹配即放行」)
  2. 规则求值/读库异常 -> DENY (否决「LLM/求值失败默认 allow」)
  3. 审计写不进证据链 -> DENY (无审计不执行; 决策必须可追溯)
高风险(risk=high)即使命中 ALLOW 也只给 REQUIRE_APPROVAL——自动放行高风险被结构性禁止,
审批走既有 HITL 通道(runtime 将 REQUIRE_APPROVAL 并入 high-risk PAUSED 路径)。"""
from __future__ import annotations

import fnmatch
import time
from dataclasses import dataclass
from typing import Optional

from ..db import connect
from .posture import ACTIVE, FROZEN, SecurityPosture

ALLOW = "ALLOW"
DENY = "DENY"
REQUIRE_APPROVAL = "REQUIRE_APPROVAL"


@dataclass
class Decision:
    state: str
    rule: Optional[int]      # 命中的 rule_id(默认拒绝/异常时为 None)
    reason: str
    ts: float


class ActionPolicy:
    def __init__(self, db_path: str, posture: Optional[SecurityPosture] = None,
                 chain=None):
        self.db_path = db_path
        self.posture = posture or SecurityPosture(db_path, chain=None)
        self.chain = chain
        con = connect(db_path)
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS security_rules(
              rule_id INTEGER PRIMARY KEY AUTOINCREMENT,
              action_glob TEXT NOT NULL, target_glob TEXT NOT NULL,
              decision TEXT NOT NULL CHECK(decision IN ('ALLOW','DENY','REQUIRE_APPROVAL')),
              priority INTEGER NOT NULL DEFAULT 100, note TEXT);
            """
        )
        con.commit()
        con.close()

    # ---- 规则管理 ----
    def add_rule(self, action_glob: str, target_glob: str, decision: str,
                 priority: int = 100, note: str = "") -> int:
        if decision not in (ALLOW, DENY, REQUIRE_APPROVAL):
            raise ValueError("bad decision: %s" % decision)
        con = connect(self.db_path)
        try:
            cur = con.execute(
                "INSERT INTO security_rules(action_glob,target_glob,decision,priority,note)"
                " VALUES(?,?,?,?,?)", (action_glob, target_glob, decision, priority, note))
            con.commit()
            rid = cur.lastrowid
        finally:
            con.close()
        if rid is None:
            raise RuntimeError("rule insert returned no id")
        if self.chain:
            self.chain.append("security", "policy.rule_added",
                              {"rule_id": rid, "action": action_glob,
                               "target": target_glob, "decision": decision, "note": note})
        return rid

    def remove_rule(self, rule_id: int) -> None:
        con = connect(self.db_path)
        try:
            con.execute("DELETE FROM security_rules WHERE rule_id=?", (rule_id,))
            con.commit()
        finally:
            con.close()
        if self.chain:
            self.chain.append("security", "policy.rule_removed", {"rule_id": rule_id})

    # ---- 决策 ----
    def decide(self, action: str, target: str = "", risk: str = "normal") -> Decision:
        rule_id: Optional[int] = None
        try:
            state, rule_id, reason = self._match(action, target, risk)
        except Exception as e:
            state, rule_id, reason = DENY, None, "policy-error-default-deny: %s" % e
        decision = Decision(state, rule_id, reason, time.time())
        self._audit(action, target, risk, decision)  # 审计失败在其中转 DENY 语义由调用方保证
        return decision

    def _match(self, action: str, target: str, risk: str):
        posture = self.posture.get()  # 读失败已按 FROZEN 返回
        con = connect(self.db_path)
        try:
            rows = con.execute(
                "SELECT rule_id,action_glob,target_glob,decision,priority"
                " FROM security_rules ORDER BY priority ASC, rule_id ASC").fetchall()
        finally:
            con.close()
        hit = None
        for r in rows:
            if fnmatch.fnmatch(action, r["action_glob"]) and \
               fnmatch.fnmatch(target, r["target_glob"]):
                hit = r
                break
        if posture == FROZEN:
            # 冻结区: 仅显式 ALLOW 且 normal 风险可存活, 其余一律 DENY。
            if hit is not None and hit["decision"] == ALLOW and risk != "high":
                return ALLOW, hit["rule_id"], "frozen-explicit-allow"
            return DENY, None, "frozen-default-deny"
        if hit is None:
            return DENY, None, "no-rule-default-deny"
        if hit["decision"] == ALLOW and risk == "high":
            return REQUIRE_APPROVAL, hit["rule_id"], "high-risk-approval-required"
        return hit["decision"], hit["rule_id"], "rule:%s" % hit["decision"]

    def _audit(self, action: str, target: str, risk: str, d: Decision) -> None:
        if self.chain is None:
            return
        try:
            self.chain.append("security", "policy.decision",
                              {"action": action, "target": target, "risk": risk,
                               "state": d.state, "rule": d.rule, "reason": d.reason})
        except Exception:
            # 无审计不执行: 审计不可写时把决策强制降级为 DENY。
            d.state, d.rule = DENY, None
            d.reason = "audit-unavailable-default-deny"
