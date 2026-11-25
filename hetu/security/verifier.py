"""主张核验器(证据优先) —— 机制借鉴 ARTEX hunting/verify.go 的证据核验思想
(仅设计借鉴, AGPL 源码零复制): 引证必须真实存在、在授权范围内、字段齐备;
观察到可疑 != 证明成立; 数据不足只能 INCONCLUSIVE, 不得升格为结论。

三态语义:
  VERIFIED      全部引证真实、在窗口内、字段齐备、已考虑替代解释
  REJECTED      引证不实(引用不存在的证据)或超出授权时间窗——虚假引证是硬失败
  INCONCLUSIVE  无引证/字段不足/未考虑替代解释/核验器自身异常——永不因错误给 VERIFIED
"""
from __future__ import annotations

import json
from typing import Any

from ..db import connect

VERIFIED = "VERIFIED"
REJECTED = "REJECTED"
INCONCLUSIVE = "INCONCLUSIVE"


class ClaimVerifier:
    def __init__(self, db_path: str):
        self.db_path = db_path

    def verify(self, claim: dict) -> tuple[str, list]:
        """claim 字段:
          citations: [evidence_chain.seq, ...]   必填
          required_fields: [str]                 每条引证 detail 必须含这些键
          window: [start_ts, end_ts]             引证 ts 必须落在窗口内
          alternative_explanations: [str]        至少一条替代解释, 空=数据不足
        """
        reasons: list[str] = []
        try:
            citations = claim.get("citations") or []
            if not citations:
                return INCONCLUSIVE, ["no-citations"]
            con = connect(self.db_path)
            try:
                for seq in citations:
                    row = con.execute(
                        "SELECT ts, detail FROM evidence_chain WHERE seq=?",
                        (seq,)).fetchone()
                    if row is None:
                        return REJECTED, ["citation-missing: seq=%s" % seq]
                    ts = row["ts"]
                    win = claim.get("window")
                    if win and not (win[0] <= ts <= win[1]):
                        return REJECTED, ["citation-out-of-window: seq=%s" % seq]
                    for field in claim.get("required_fields") or []:
                        try:
                            detail = json.loads(row["detail"])
                        except (TypeError, ValueError):
                            detail = {}
                        if field not in detail:
                            reasons.append("missing-field: seq=%s field=%s" % (seq, field))
            finally:
                con.close()
            if reasons:
                return INCONCLUSIVE, reasons
            if not claim.get("alternative_explanations"):
                return INCONCLUSIVE, ["alternative-explanations-not-considered"]
            return VERIFIED, ["all-citations-verified"]
        except Exception as e:
            # fail-closed: 核验器自身故障绝不给 VERIFIED, 也不给 REJECTED(避免误伤),
            # 只给 INCONCLUSIVE 交人工——与 ledger 的 UNCERTAIN 先对账同构。
            return INCONCLUSIVE, ["verifier-error: %s" % e]
