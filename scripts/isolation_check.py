#!/usr/bin/env python3
"""发布门检查: Hetu 代码与旧 旧产品（HongYun 前作） 的严格区别(机器执行, 不靠自觉)。

检查项:
  C1 代码零引用: hetu/ scripts/ tests/ 内不得出现旧产品树路径片段或旧产品环境变量。
  C2 命名自指: 包名/发行名/CLI 必须是 hetu/hetu-agent, 不得以前作自称。
  C3 运行时守卫在位: hetu/db.py 必须调用 guard.assert_isolated。
  C4 包位置: hetu 包本体不得位于旧产品树内。
docs/ 允许在「禁令/三线关系」语境中提到 旧产品（HongYun 前作）(人工评审), 代码零容忍。
"""
from __future__ import annotations

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

CODE_DIRS = ("hetu", "scripts", "tests")
# 拼接构造, 防止扫描器自身明文携带禁词
FORBIDDEN_CODE_TOKENS = [
    "." + "hermes", "hasu-" + "agent", "hasu-" + "home", "hasu" + "agent",
    "hermes-" + "runtime", "HERMES_" + "HOME", "HASU_" + "HOME", "hermes_" + "agent",
]
SELF_NAME_PATTERNS = [
    (r"(?i)\bname\s*=\s*[\"']hermes", "pyproject 发行名不得为 hermes*"),
    (r"(?i)\bname\s*=\s*[\"']hasu", "pyproject 发行名不得为 hasu*"),
]


def scan_code():
    violations = []
    for d in CODE_DIRS:
        for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT, d)):
            dirnames[:] = [x for x in dirnames if x != "__pycache__"]
            for fn in filenames:
                if not fn.endswith((".py", ".toml", ".cfg", ".txt")):
                    continue
                p = os.path.join(dirpath, fn)
                text = open(p, encoding="utf-8").read()
                low = text.lower()
                for tok in FORBIDDEN_CODE_TOKENS:
                    if tok.lower() in low:
                        violations.append("%s: 禁词 %r" % (os.path.relpath(p, ROOT), tok))
    return violations


def scan_self_name():
    violations = []
    py = os.path.join(ROOT, "pyproject.toml")
    text = open(py, encoding="utf-8").read()
    for pat, why in SELF_NAME_PATTERNS:
        if re.search(pat, text):
            violations.append("pyproject.toml: %s" % why)
    init = open(os.path.join(ROOT, "hetu", "__init__.py"), encoding="utf-8").read()
    if re.search(r"(?i)\b(hermes|hasu)\s+agent", init):
        violations.append("hetu/__init__.py: 包自指不得使用旧产品名")
    return violations


def scan_guard_wired():
    db = open(os.path.join(ROOT, "hetu", "db.py"), encoding="utf-8").read()
    if "assert_isolated" not in db:
        return ["hetu/db.py: 运行时隔离守卫未接线"]
    return []


def scan_package_location():
    import hetu
    p = os.path.abspath(hetu.__file__).lower()
    for frag in ("." + "hermes", "hasu-" + "agent", "hasu-" + "home",
                 "hasu" + "agent", "hermes-" + "runtime"):
        if frag in p:
            return ["hetu 包位于旧产品树内: %s" % hetu.__file__]
    return []


def main() -> int:
    results = {
        "C1 代码零引用旧产品树": scan_code(),
        "C2 命名自指为 Hetu": scan_self_name(),
        "C3 运行时守卫在位": scan_guard_wired(),
        "C4 包位置独立": scan_package_location(),
    }
    bad = any(v for v in results.values())
    for k, v in results.items():
        print("%-24s %s" % (k, "✅" if not v else "❌ " + "; ".join(v)))
    print("isolation-check verdict:", "FAILED" if bad else "OK")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
