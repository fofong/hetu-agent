#!/usr/bin/env python3
"""CLA 签署通道核心逻辑（零第三方依赖，CI 与本地共用，可单测）。

流程（无外部 bot，全部在本仓库内闭环）：
1. 贡献者在自己的 PR 下评论签署语句（英文或中文，见 PHRASES）。
2. 本脚本校验「评论者 == PR 作者 且 语句精确匹配」→ 追加签名到 docs/cla-signatures.json。
3. PR 状态检查 `cla`：作者已签名 / 维护方本人 / 机器人账号 → success，否则 failure。

汇报纪律：判定只依据文件与输入，不猜测。
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys

# 精确签署语句（规范化后比较：去空白、去常见句读、小写）
PHRASES = (
    "ihavereadthecladocumentandiherebysignthecla",
    "我已阅读cla文档（docs/cla.md）并确认签署cla",
)



def normalize(text: str) -> str:
    # 去全部空白 + 小写；只去首尾句读（保留 docs/CLA.md 中的点）
    t = "".join(text.split()).lower()
    return t.strip("。.！!～~")


def is_signature_comment(body: str) -> bool:
    return normalize(body) in PHRASES


def load_signatures(path: str) -> dict:
    if not os.path.exists(path):
        return {"version": 1, "signatures": []}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or not isinstance(data.get("signatures"), list):
        raise ValueError("cla-signatures.json 结构非法：需要 {version, signatures[]}")
    return data


def signed_logins(data: dict) -> set:
    return {e.get("login") for e in data["signatures"] if isinstance(e, dict)}


def check(login: str, data: dict, owner: str) -> tuple:
    """返回 (passed: bool, reason: str)。"""
    if not login:
        return False, "无法确定 PR 作者"
    if owner and login == owner:
        return True, "维护方本人，豁免签署"
    if login.endswith("[bot]"):
        return True, "机器人账号，豁免签署"
    if login in signed_logins(data):
        return True, "已签署 CLA（见 docs/cla-signatures.json）"
    return False, "尚未签署 CLA：请在 PR 下评论签署语句（见 CONTRIBUTING.md）"


def add_signature(path: str, login: str, user_id, comment_url: str) -> dict:
    """幂等追加签名。返回 {action: added|exists, login}。"""
    data = load_signatures(path)
    if login in signed_logins(data):
        return {"action": "exists", "login": login}
    data["signatures"].append({
        "login": login,
        "user_id": user_id,
        "date": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "comment_url": comment_url,
    })
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return {"action": "added", "login": login}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("check", help="PR 状态判定")
    c.add_argument("--login", required=True)
    c.add_argument("--signatures", required=True)
    c.add_argument("--owner", default="")

    p = sub.add_parser("parse", help="校验评论是否为有效签署")
    p.add_argument("--body-file", required=True)
    p.add_argument("--login", required=True, help="评论者")
    p.add_argument("--pr-author", required=True)

    a = sub.add_parser("add", help="追加签名（幂等）")
    a.add_argument("--signatures", required=True)
    a.add_argument("--login", required=True)
    a.add_argument("--user-id", default=None)
    a.add_argument("--comment-url", default="")

    ns = ap.parse_args()
    if ns.cmd == "check":
        ok, reason = check(ns.login, load_signatures(ns.signatures), ns.owner)
        print(reason)
        return 0 if ok else 1
    if ns.cmd == "parse":
        with open(ns.body_file, encoding="utf-8") as f:
            body = f.read()
        if ns.login != ns.pr_author:
            print("评论者不是 PR 作者，忽略")
            return 1
        if not is_signature_comment(body):
            print("非签署语句，忽略")
            return 1
        print("有效签署评论")
        return 0
    if ns.cmd == "add":
        print(json.dumps(add_signature(ns.signatures, ns.login, ns.user_id, ns.comment_url)))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
