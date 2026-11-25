"""L3 · 演化层脚手架(隔离实验树 + 评分器物理隔离 + 晋级门)。

公理2/4: 进化体永不修改评分器/验收器/测试标准/最终保护机制;
演化只在隔离实验树进行, 晋级须外部监督者(Avatar)独立验收签名。
本模块是 Phase 3 的机制脚手架, 真实演化算法在 Phase 3 填充。
"""
from __future__ import annotations

import hashlib
import os
import time
from typing import Any, Optional

from ..db import connect

MUTATION_TYPES = ("tools", "skills", "logic")


class ScorerTamper(Exception):
    pass


class PromotionGateFailed(Exception):
    pass


class ScorerVault:
    """评分器物理隔离: 文件+清单哈希; 演化体只拿到 EvolverView(无写权)。"""

    def __init__(self, vault_dir: str, admin_token: Optional[str] = None):
        self.vault_dir = vault_dir
        self.admin_token = admin_token
        os.makedirs(vault_dir, exist_ok=True)

    def _manifest_path(self) -> str:
        return os.path.join(self.vault_dir, "MANIFEST.sha256")

    def install_scorer(self, name: str, code: str, token: str) -> None:
        if not self.admin_token or token != self.admin_token:
            raise ScorerTamper("scorer install requires supervisor admin token")
        path = os.path.join(self.vault_dir, name + ".py")
        with open(path, "w", encoding="utf-8") as f:
            f.write(code)
        self._update_manifest(name + ".py", code)

    def _update_manifest(self, name: str, code: str) -> None:
        lines = {}
        mp = self._manifest_path()
        if os.path.exists(mp):
            with open(mp, encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        h, n = line.split()
                        lines[n] = h
        lines[name] = hashlib.sha256(code.encode()).hexdigest()
        with open(mp, "w", encoding="utf-8") as f:
            for n, h in sorted(lines.items()):
                f.write("%s %s\n" % (h, n))

    def verify_integrity(self) -> bool:
        mp = self._manifest_path()
        if not os.path.exists(mp):
            return True
        with open(mp, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                h, n = line.split()
                path = os.path.join(self.vault_dir, n)
                if not os.path.exists(path):
                    return False
                with open(path, encoding="utf-8") as g:
                    if hashlib.sha256(g.read().encode()).hexdigest() != h:
                        return False
        return True

    def score(self, name: str, sample: Any) -> float:
        # 每次评分前强制完整性校验: 篡改在评分时刻即暴露, 而不是拖到晋级门(P2)。
        if not self.verify_integrity():
            raise ScorerTamper("scorer vault integrity check failed; refusing to score")
        path = os.path.join(self.vault_dir, name + ".py")
        ns: dict = {}
        with open(path, encoding="utf-8") as f:
            exec(compile(f.read(), path, "exec"), ns)  # 评分器代码受清单哈希保护
        return float(ns["score"](sample))

    def as_evolver(self) -> "EvolverView":
        return EvolverView(self)


class EvolverView:
    """演化体唯一可见的评分器视图: 只能读分, 物理上无写路径。"""

    def __init__(self, vault: ScorerVault):
        self._vault = vault

    def score(self, name: str, sample: Any) -> float:
        return self._vault.score(name, sample)


class ExperimentTree:
    def __init__(self, db_path: str, supervisor_secret: Optional[str] = None,
                 vault: Optional[ScorerVault] = None):
        self.db_path = db_path
        self.supervisor_secret = supervisor_secret
        self.vault = vault
        con = connect(db_path)
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS experiments(
              experiment_id TEXT PRIMARY KEY, parent_id TEXT, mutation_type TEXT NOT NULL,
              metrics TEXT, reproducible INTEGER NOT NULL DEFAULT 0,
              status TEXT NOT NULL DEFAULT 'CANDIDATE', created_ts REAL NOT NULL,
              promoted_ts REAL);
            """
        )
        con.commit()
        con.close()

    def spawn(self, parent_id: Optional[str], mutation_type: str) -> str:
        if mutation_type not in MUTATION_TYPES:
            raise ValueError("mutation_type must be one of %s (prompt-only 不许)" % (MUTATION_TYPES,))
        eid = "exp-%s-%d" % (mutation_type, int(time.time() * 1000) % 10**9)
        con = connect(self.db_path)
        try:
            con.execute(
                "INSERT INTO experiments(experiment_id,parent_id,mutation_type,created_ts)"
                " VALUES(?,?,?,?)", (eid, parent_id, mutation_type, time.time()))
            con.commit()
            return eid
        finally:
            con.close()

    def record_result(self, experiment_id: str, metrics: dict, reproducible: bool) -> None:
        import json
        con = connect(self.db_path)
        try:
            con.execute("UPDATE experiments SET metrics=?, reproducible=? WHERE experiment_id=?",
                        (json.dumps(metrics), 1 if reproducible else 0, experiment_id))
            con.commit()
        finally:
            con.close()

    def _get(self, eid: str) -> dict:
        con = connect(self.db_path)
        try:
            return dict(con.execute("SELECT * FROM experiments WHERE experiment_id=?",
                                    (eid,)).fetchone())
        finally:
            con.close()

    def promote(self, experiment_id: str, supervisor_signature: str,
                objective: str = "score") -> None:
        """晋级门: 评分器完整 + 可复现 + 目标指标优于父代 + 外部监督者签名。"""
        import json
        if self.vault and not self.vault.verify_integrity():
            raise PromotionGateFailed("scorer integrity check failed")
        if not self.supervisor_secret or supervisor_signature != self.supervisor_secret:
            raise PromotionGateFailed("missing/invalid external supervisor signature")
        exp = self._get(experiment_id)
        if not exp["reproducible"]:
            raise PromotionGateFailed("result not reproducible")
        metrics = json.loads(exp["metrics"] or "{}")
        parent = self._get(exp["parent_id"]) if exp["parent_id"] else None
        if parent:
            pm = json.loads(parent["metrics"] or "{}")
            if metrics.get(objective, 0) <= pm.get(objective, 0):
                raise PromotionGateFailed("no reproducible improvement over parent")
        con = connect(self.db_path)
        try:
            con.execute("UPDATE experiments SET status='PROMOTED', promoted_ts=?"
                        " WHERE experiment_id=?", (time.time(), experiment_id))
            con.commit()
        finally:
            con.close()
