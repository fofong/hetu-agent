#!/usr/bin/env python3
"""M2 Hetu 侧自基线: 基准任务集 × 故障注入, 度量副作用重复率/恢复正确性。

说明: 备忘录 M2 = Hetu vs 旧产品 同任务集行为一致率。旧产品侧对照需基准集评审后
另行执行(跨产品对照不在本仓自动化范围); 本脚本先固化 Hetu 侧基线数字。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from hetu.runtime import Step, TaskRunner  # noqa: E402


def run_scenario(name, fault, repeat=5):
    """每场景: 3 步任务(fetch→charge→notify), 副作用台账核对。"""
    dup_total = 0
    statuses = []
    for i in range(repeat):
        tmp = tempfile.mkdtemp()
        db = os.path.join(tmp, "m2.db")
        side = []
        probes = {"charge": lambda: None}

        def mk(tag):
            def f():
                side.append(tag)
                return tag
            return f

        steps = [Step("s1", "fetch", mk("fetch")),
                 Step("s2", "charge", mk("charge")),
                 Step("s3", "notify", mk("notify"))]
        # 租约语义边界: TTL 必须大于效果最长执行时间, 否则故障检测器"说谎"。
        # timeout 场景执行者确已停止 → ttl=0 模拟即刻死亡; 并发场景执行者仍活 → 真实 TTL。
        lease = 0 if fault == "timeout_charge" else 30.0
        runner = TaskRunner(db, probes=probes, lease_ttl=lease)
        if fault == "none":
            r = runner.run_task("t", ["fetch", "charge", "notify"], steps)
        elif fault == "crash_at_charge":
            try:
                runner.run_task("t", ["fetch", "charge", "notify"], steps,
                                crash_at_step="s2")
            except Exception:
                pass
            r = runner.run_task("t", ["fetch", "charge", "notify"], steps)
        elif fault == "duplicate_delivery":
            runner.run_task("t", ["fetch", "charge", "notify"], steps)
            r = runner.run_task("t", ["fetch", "charge", "notify"], steps)
        elif fault == "timeout_charge":
            def boom():
                raise TimeoutError("t/o")
            bad = [Step("s1", "fetch", mk("fetch")),
                   Step("s2", "charge", boom),
                   Step("s3", "notify", mk("notify"))]
            runner.run_task("t", ["fetch", "charge", "notify"], bad)
            runner.ledger.reconcile("t:s2", lambda: None)
            r = runner.run_task("t", ["fetch", "charge", "notify"], steps)
        elif fault == "concurrent":
            out = []
            ts = [threading.Thread(target=lambda n=n: out.append(
                runner.run_task("t", ["fetch", "charge", "notify"], steps)["status"]))
                for n in range(2)]
            [t.start() for t in ts]
            [t.join() for t in ts]
            r = {"status": "+".join(sorted(out))}
        # 副作用重复率: charge 应恰好 1 次(crash/timeout 场景含受控重放仍为 1)
        dup_total += max(0, side.count("charge") - 1) + max(0, side.count("fetch") - 1)
        statuses.append(r["status"])
    return {"scenario": name, "fault": fault, "repeat": repeat,
            "duplicate_side_effects": dup_total,
            "final_statuses": sorted(set(statuses))}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default=os.path.join(ROOT, "docs", "evidence"))
    outdir = parser.parse_args().output_dir
    t0 = time.time()
    scenarios = [
        ("正常执行", "none"), ("崩溃于副作用后", "crash_at_charge"),
        ("重复投递", "duplicate_delivery"), ("网络超时+对账", "timeout_charge"),
        ("并发双跑", "concurrent"),
    ]
    results = [run_scenario(n, f) for n, f in scenarios]
    total_dup = sum(r["duplicate_side_effects"] for r in results)
    report = {"generated": time.strftime("%Y-%m-%d %H:%M:%S"),
              "note": "Hetu 侧自基线; 旧产品侧对照待基准集评审后另行执行",
              "total_duplicate_side_effects": total_dup,
              "scenarios": results, "elapsed_sec": round(time.time() - t0, 1)}
    os.makedirs(outdir, exist_ok=True)  # 打包环境(如 .app 内)无 docs 树时自建
    with open(os.path.join(outdir, "m2_baseline.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    lines = ["# M2 Hetu 侧自基线报告", "",
             "> %s" % report["note"], "",
             "| 场景 | 故障 | 重复副作用 | 终态 |", "|---|---|---|---|"]
    for r in results:
        lines.append("| %s | %s | %d | %s |" % (r["scenario"], r["fault"],
                     r["duplicate_side_effects"], ", ".join(r["final_statuses"])))
    lines += ["", "**总重复副作用数：%d（目标 0）**" % total_dup]
    with open(os.path.join(outdir, "M2_SELF_BASELINE.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("m2: scenarios=%d duplicate_side_effects=%d -> %s"
          % (len(results), total_dup, "PASS" if total_dup == 0 else "FAIL"))
    return 0 if total_dup == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
