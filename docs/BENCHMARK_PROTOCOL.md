# M2 同梯队横向对比基准协议（预注册）

> 门禁第 8 维依据。**本文件先于任何对比实验提交入库，即预注册**：指标、任务集、判定标准在见到任何结果之前冻结。结果不符合预期也如实上报，不许选数据。

## 对手集（同领域、同成熟度，不挑弱鸡）

| 对手 | 选型理由 |
|---|---|
| LangGraph | 主流 agent 编排框架，自带 checkpoint/持久化，是 Hetu「可恢复执行」宣称的最强同类 |
| Letta（memGPT） | agent 状态持久化方向的代表实现 |
| AutoGen（Microsoft） | 多 agent 框架头部项目，成熟度对照 |

Temporal 类 durable execution 引擎作为**语义参照**（非对手：非 agent 框架），用于说明 Effect Ledger 语义的落点。

## 被测宣称 → 可证伪指标

| 宣称 | 指标 | 测量方法 |
|---|---|---|
| C1 崩溃安全幂等 | 崩溃于副作用后恢复的**重复外部副作用次数**（目标 0） | 统一效果桩（charge/notify 写外部账本文件），注入 `crash_after_effect`，重启续跑，数重复 |
| C2 回执丢失对账 | 回执丢失时行为：对账（reconcile）/ 盲重放 / 报错停摆，三态归类 | 注入「效果成功+回执未落盘+租约过期」 |
| C3 高风险转人工持久性 | PAUSED/HITL 挂起跨进程重启是否存活 | 挂起后 kill -9，重启探测状态 |
| C4 依赖与足迹 | 运行时第三方依赖数、安装体积、冷启动时间 | 干净 venv 实测（Hetu 预期：0 依赖） |
| C5 可复现验证 | 第三方仅凭仓库+stdlib 能否复跑机制实验 | `python3 -m unittest discover -s tests -t .` 全新机器 |

## 任务集（各框架等价实现）

同一业务脚本（fetch→charge→notify，charge 高风险）在四个实现上各写一遍，故障注入矩阵统一：none / crash_after_effect / lost_receipt / duplicate_delivery / concurrent_double_run。

## 公平性规则

- 同机、同一 Python、各框架用**官方文档推荐的最佳持久化配置**（如 LangGraph SqliteSaver），不许给对手配残腿。
- 每个数据点 ≥5 次重复，记录全部原始结果（含不利结果）到 `docs/evidence/m2_peer/`。
- 对手版本、配置全文、实验脚本一并入库，第三方可复验。

## 通过判据（发布门）

至少一个指标上 Hetu **可复现、可引用**地占优（预期落点：C1/C2 语义完备性 + C4 零依赖足迹）；若全部指标无可靠优势 → 按门禁转向（换叙事或补机制），不发布。

## 状态

- [ ] 对手框架安装与等价任务实现
- [ ] 故障注入矩阵实测（含 Hetu 侧 m2_harness 复跑）
- [ ] 结果报告 `docs/evidence/m2_peer/PEER_REPORT.md`（全量如实）
