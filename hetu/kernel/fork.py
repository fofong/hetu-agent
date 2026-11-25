"""L0 · fork 式分支纠正 + 依赖污染传播。

公理3: 纠错≠回滚。fork 是逻辑分支, 不是文件系统/外部世界回滚。
产物不可变(append-only), 污染传播失效化全部下游, 未受污染成果保留,
验收后原子切换交付引用(delivery pointer)。
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Optional

from ..db import connect

ACTIVE = "ACTIVE"
INVALIDATED = "INVALIDATED"
SUPERSEDED = "SUPERSEDED"


def _sha(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False,
                                      default=str).encode()).hexdigest()


class ArtifactLedger:
    def __init__(self, db_path: str):
        self.db_path = db_path
        con = connect(db_path)
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS artifacts(
              artifact_id TEXT PRIMARY KEY, branch TEXT NOT NULL DEFAULT 'main',
              content TEXT NOT NULL, content_hash TEXT NOT NULL, input_hash TEXT,
              dependency_ids TEXT NOT NULL DEFAULT '[]', effect_refs TEXT NOT NULL DEFAULT '[]',
              validator_version TEXT NOT NULL, status TEXT NOT NULL, created_ts REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS delivery_refs(
              name TEXT PRIMARY KEY, artifact_id TEXT NOT NULL, switched_ts REAL NOT NULL);
            """
        )
        con.commit()
        con.close()

    def record(self, artifact_id: str, content: Any, *, input_hash: str = "",
               dependency_ids: Optional[list[str]] = None,
               effect_refs: Optional[list[str]] = None,
               validator_version: str = "v1", branch: str = "main") -> None:
        con = connect(self.db_path)
        try:
            con.execute(
                "INSERT INTO artifacts(artifact_id,branch,content,content_hash,input_hash,"
                "dependency_ids,effect_refs,validator_version,status,created_ts)"
                " VALUES(?,?,?,?,?,?,?,?,?,?)",
                (artifact_id, branch, json.dumps(content, default=str), _sha(content),
                 input_hash, json.dumps(dependency_ids or []),
                 json.dumps(effect_refs or []), validator_version, ACTIVE, time.time()))
            con.commit()
        finally:
            con.close()

    def _all(self) -> list[dict]:
        con = connect(self.db_path)
        try:
            return [dict(r) for r in con.execute(
                "SELECT * FROM artifacts ORDER BY created_ts").fetchall()]
        finally:
            con.close()

    def status(self, artifact_id: str) -> str:
        con = connect(self.db_path)
        try:
            r = con.execute("SELECT status FROM artifacts WHERE artifact_id=?",
                            (artifact_id,)).fetchone()
            return r["status"] if r else "MISSING"
        finally:
            con.close()

    def invalidate(self, artifact_id: str, propagate: bool = True) -> list[str]:
        """污染传播: BFS 全部下游依赖, 返回被失效集合。propagate=False 为反例(禁用机制)。"""
        rows = self._all()
        deps = {r["artifact_id"]: json.loads(r["dependency_ids"]) for r in rows}
        tainted = {artifact_id}
        if propagate:
            frontier = [artifact_id]
            while frontier:
                cur = frontier.pop()
                for aid, ds in deps.items():
                    if cur in ds and aid not in tainted:
                        tainted.add(aid)
                        frontier.append(aid)
        con = connect(self.db_path)
        try:
            con.execute("BEGIN")
            for aid in tainted:
                con.execute("UPDATE artifacts SET status=? WHERE artifact_id=?",
                            (INVALIDATED, aid))
            con.commit()
        finally:
            con.close()
        return sorted(tainted)

    def fork_correction(self, base_id: str, new_id: str, new_content: Any,
                        validator_version: str = "v2") -> None:
        """在分支上产出修正版产物(逻辑分支, 原产物行永不修改内容)。"""
        base = next((r for r in self._all() if r["artifact_id"] == base_id), None)
        if base is None:
            raise KeyError(base_id)
        self.record(new_id, new_content, input_hash=base["input_hash"],
                    dependency_ids=[], effect_refs=json.loads(base["effect_refs"]),
                    validator_version=validator_version, branch=f"fix-{new_id}")

    def accept(self, delivery: str, artifact_id: str) -> None:
        """验收通过 -> 原子切换交付引用(单行更新)。"""
        if self.status(artifact_id) != ACTIVE:
            raise ValueError("cannot deliver non-ACTIVE artifact %s" % artifact_id)
        con = connect(self.db_path)
        try:
            con.execute(
                "INSERT INTO delivery_refs(name,artifact_id,switched_ts) VALUES(?,?,?)"
                " ON CONFLICT(name) DO UPDATE SET artifact_id=excluded.artifact_id,"
                " switched_ts=excluded.switched_ts",
                (delivery, artifact_id, time.time()))
            con.commit()
        finally:
            con.close()

    def delivered(self, delivery: str) -> Optional[str]:
        con = connect(self.db_path)
        try:
            r = con.execute("SELECT artifact_id FROM delivery_refs WHERE name=?",
                            (delivery,)).fetchone()
            return r["artifact_id"] if r else None
        finally:
            con.close()
