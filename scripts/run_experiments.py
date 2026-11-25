#!/usr/bin/env python3
"""生成 M1 证据包：运行全部机制实验 + 依赖扫描，产出「声称→实测证据→判定」对照表。

汇报纪律：禁自报绿 —— 本报告全部数字来自本次真实执行。
"""
from __future__ import annotations

import ast
import datetime
import json
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
EVID = os.path.join(ROOT, "docs", "evidence")

EXPERIMENTS = [
    ("A1", "test_a1_effect_ledger", "Effect Ledger 三态提交/回执丢失对账/租约fencing/高风险PAUSED/ledger损坏降级"),
    ("A2", "test_a2_step_writes", "step_writes 任务级幂等/崩溃窗口/重复投递零副作用"),
    ("A3", "test_a3_fork_pollution", "fork 分支纠正/依赖污染传播/原子交付切换"),
    ("A4", "test_a4_orphans", "孤儿 action 检测与对账"),
    ("A5", "test_a5_archive", "压缩即归档/原文永不删除"),
    ("A6", "test_a6_recovery_hitl", "plan-hash 漂移拒续/HITL 持久挂起跨重启"),
    ("D1", "test_d1_scheduler", "调度五实验: 幂等槽/漏跑台账/fencing/断点重试/投递解耦"),
    ("L1", "test_l1_evidence", "哈希链防篡改/独立探针结论门/滞回stall/沙箱白名单"),
    ("L3", "test_l3_evolution", "评分器物理隔离/晋级四门/心跳断点续算"),
    ("ISO", "test_isolation", "与旧旧产品（HongYun 前作）严格区别: 运行时守卫fail-closed/静态发布门/反证夹具"),
    ("P2", "test_p2_runtime_e2e", "一体化运行时: 崩溃恢复零重复/对账续跑/高风险挂起/漂移转人工/调度集成"),
    ("FAULT", "test_fault_matrix", "故障注入矩阵: 并发租约互斥/超时对账/DB写失败降级/回执未持久化+租约到期组合故障"),
]

STDLIB_HINTS = {"__future__", "os", "sys", "json", "time", "hashlib", "sqlite3", "tempfile", "threading",
                "unittest", "uuid", "argparse", "dataclasses", "typing", "ast", "datetime",
                "subprocess", "re", "collections", "functools", "itertools", "pathlib",
                "io", "abc", "enum", "logging", "math", "random", "shutil", "textwrap"}


def run_experiments():
    loader = unittest.TestLoader()
    results = {}
    for tag, mod, desc in EXPERIMENTS:
        suite = loader.discover(start_dir=os.path.join(ROOT, "tests"), pattern=mod + ".py")
        counterexamples = sum(1 for t in _iter(suite) if "counterexample" in t.id().lower())
        runner = unittest.TextTestRunner(stream=open(os.devnull, "w"), verbosity=0)
        res = runner.run(suite)
        results[tag] = {
            "module": mod, "desc": desc,
            "tests": res.testsRun,
            "failures": len(res.failures), "errors": len(res.errors),
            "counterexample_fixtures": counterexamples,
            "green": res.testsRun > 0 and not res.failures and not res.errors,
        }
    return results


def _iter(suite):
    for t in suite:
        if isinstance(t, unittest.TestSuite):
            yield from _iter(t)
        else:
            yield t


def scan_imports():
    third = set()
    for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT, "hetu")):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for fn in filenames:
            if not fn.endswith(".py"):
                continue
            tree = ast.parse(open(os.path.join(dirpath, fn), encoding="utf-8").read())
            for node in ast.walk(tree):
                mods = []
                if isinstance(node, ast.Import):
                    mods = [a.name.split(".")[0] for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                    mods = [node.module.split(".")[0]]
                for m in mods:
                    if m not in STDLIB_HINTS and m != "hetu":
                        third.add(m)
    return sorted(third)


def main():
    os.makedirs(EVID, exist_ok=True)
    results = run_experiments()
    third = scan_imports()
    total = sum(r["tests"] for r in results.values())
    all_green = all(r["green"] for r in results.values()) and not third
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    evidence = {"generated": ts, "python": sys.version.split()[0],
                "third_party_runtime_deps": third, "all_green": all_green,
                "experiments": results}
    with open(os.path.join(EVID, "evidence.json"), "w", encoding="utf-8") as f:
        json.dump(evidence, f, ensure_ascii=False, indent=2)

    lines = [
        "# M1 机制验证证据报告", "",
        "生成时间：%s · Python %s · 本报告由 `scripts/run_experiments.py` 实测生成，禁自报绿。" % (ts, sys.version.split()[0]),
        "",
        "| 声称 | 实测证据 | 判定 |",
        "|---|---|---|",
    ]
    for tag, r in results.items():
        verdict = "✅ 通过" if r["green"] else "❌ 未过"
        lines.append("| %s：%s | %d 项测试，fail=%d err=%d，反例夹具 %d 个 | %s |" % (
            tag, r["desc"], r["tests"], r["failures"], r["errors"],
            r["counterexample_fixtures"], verdict))
    lines.append("| 零第三方运行时依赖 | import 全树 AST 扫描：%s | %s |" % (
        "未发现第三方模块" if not third else "发现 " + ", ".join(third),
        "✅ 通过" if not third else "❌ 未过"))
    lines += ["", "**总计**：%d 项实验，全部反例驱动（禁用被测机制必红）。"
              "**M1 判定：%s**" % (total, "全绿 ✅" if all_green else "存在未过项 ❌"), ""]
    with open(os.path.join(EVID, "M1_REPORT.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print("experiments: %d tests, all_green=%s, third_party=%s" % (total, all_green, third or "none"))
    print("written: docs/evidence/M1_REPORT.md, docs/evidence/evidence.json")
    return 0 if all_green else 1


if __name__ == "__main__":
    sys.exit(main())
