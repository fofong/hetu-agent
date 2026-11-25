"""L0 · 压缩即归档: 追加归档, 原文永不删除。工作集通过归档标记视图缩小。"""
from __future__ import annotations

import json
import time

from ..db import connect


class Archiver:
    def __init__(self, db_path: str):
        self.db_path = db_path
        con = connect(db_path)
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS archives(
              seq INTEGER PRIMARY KEY AUTOINCREMENT, source_table TEXT NOT NULL,
              source_id TEXT NOT NULL, payload TEXT NOT NULL, archived_ts REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS working_set(
              item_id TEXT PRIMARY KEY, payload TEXT NOT NULL, created_ts REAL NOT NULL,
              archived INTEGER NOT NULL DEFAULT 0);
            """
        )
        con.commit()
        con.close()

    def add(self, item_id: str, payload) -> None:
        con = connect(self.db_path)
        try:
            con.execute("INSERT INTO working_set(item_id,payload,created_ts) VALUES(?,?,?)",
                        (item_id, json.dumps(payload, default=str), time.time()))
            con.commit()
        finally:
            con.close()

    def compact(self, item_ids: list[str], destructive: bool = False) -> int:
        """归档一批条目。destructive=True 是反例实现(删除原文), 仅用于反例夹具。"""
        con = connect(self.db_path)
        n = 0
        try:
            con.execute("BEGIN")
            for iid in item_ids:
                r = con.execute("SELECT payload FROM working_set WHERE item_id=?",
                                (iid,)).fetchone()
                if not r:
                    continue
                con.execute(
                    "INSERT INTO archives(source_table,source_id,payload,archived_ts)"
                    " VALUES('working_set',?,?,?)", (iid, r["payload"], time.time()))
                if destructive:
                    con.execute("DELETE FROM working_set WHERE item_id=?", (iid,))
                else:
                    con.execute("UPDATE working_set SET archived=1 WHERE item_id=?", (iid,))
                n += 1
            con.commit()
            return n
        finally:
            con.close()

    def original_exists(self, item_id: str) -> bool:
        con = connect(self.db_path)
        try:
            return con.execute("SELECT 1 FROM working_set WHERE item_id=?",
                               (item_id,)).fetchone() is not None
        finally:
            con.close()

    def archived(self, item_id: str) -> bool:
        con = connect(self.db_path)
        try:
            return con.execute("SELECT 1 FROM archives WHERE source_id=?",
                               (item_id,)).fetchone() is not None
        finally:
            con.close()

    def working_count(self) -> int:
        con = connect(self.db_path)
        try:
            return con.execute("SELECT COUNT(*) c FROM working_set WHERE archived=0").fetchone()["c"]
        finally:
            con.close()
