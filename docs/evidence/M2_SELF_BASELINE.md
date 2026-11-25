# M2 Hetu 侧自基线报告

> Hetu 侧自基线; 旧产品侧对照待基准集评审后另行执行

| 场景 | 故障 | 重复副作用 | 终态 |
|---|---|---|---|
| 正常执行 | none | 0 | DONE |
| 崩溃于副作用后 | crash_at_charge | 0 | DONE |
| 重复投递 | duplicate_delivery | 0 | DONE |
| 网络超时+对账 | timeout_charge | 0 | DONE |
| 并发双跑 | concurrent | 0 | DONE+DONE, DONE+INTERRUPTED, DONE+RECONCILE |

**总重复副作用数：0（目标 0）**
