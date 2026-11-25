# 相似性扫描报告

- 方法：token(\w+) 5-gram Jaccard, aggregate scores only (no upstream content)
- Hetu 文件数：29 · 上游根：upstream-1(3074 files); upstream-2(6000 files)
- 全文件对 max Jaccard：**0.0460**（阈值 0.25）
- 判定：**AUTOSCAN_PASS**（自动文本筛查结论，非法律认证）
- 局限：不能识别语义等价实现、非代码资产来源、研发过程污染

## 每文件最高相似度

| Hetu 文件 | max Jaccard |
|---|---|
| hetu/evidence/probes.py | 0.0460 |
| hetu/kernel/heartbeat.py | 0.0219 |
| hetu/security/verifier.py | 0.0164 |
| hetu/kernel/sandbox.py | 0.0155 |
| hetu/cli.py | 0.0135 |
| hetu/kernel/archive.py | 0.0119 |
| hetu/kernel/recovery.py | 0.0108 |
| hetu/kernel/hitl.py | 0.0103 |
| hetu/kernel/step_writes.py | 0.0100 |
| hetu/guard.py | 0.0096 |
| hetu/security/posture.py | 0.0093 |
| hetu/db.py | 0.0087 |
| hetu/evidence/chain.py | 0.0084 |
| hetu/evidence/stall.py | 0.0078 |
| hetu/security/policy.py | 0.0078 |
| hetu/runtime.py | 0.0074 |
| hetu/kernel/effect_ledger.py | 0.0065 |
| hetu/taskctl.py | 0.0064 |
| hetu/kernel/fork.py | 0.0064 |
| hetu/evolution/evolve.py | 0.0058 |
| hetu/sched/scheduler.py | 0.0054 |
| hetu/model.py | 0.0053 |
| hetu/__init__.py | 0.0000 |
| hetu/__main__.py | 0.0000 |
| hetu/evidence/__init__.py | 0.0000 |
| hetu/security/__init__.py | 0.0000 |
| hetu/sched/__init__.py | 0.0000 |
| hetu/evolution/__init__.py | 0.0000 |
| hetu/kernel/__init__.py | 0.0000 |
