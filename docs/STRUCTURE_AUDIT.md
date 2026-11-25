# Hetu Agent 结构与模块深度审计报告

日期: 2026-11-18 · 版本: v0.3.2 · 方法: 机器检测 + 逐模块代码审查 + 探针先证红后修复(反例驱动)

## 一、整体结构检测(通过)

| 检测项 | 方法 | 结果 |
|---|---|---|
| 分层依赖方向 | AST 解析包内 import 构建依赖图 | 无低层依赖高层违规(kernel/evidence/sched/evolution → db/guard 单向) |
| 循环依赖 | 依赖图双向边检测 | 无环 |
| 第三方运行时依赖 | AST import 扫描 | 0(stdlib + SQLite only) |
| 规模合理性 | wc -l | 包内约 1.4k 行 / 测试约 1.7k 行, 测试比 >1, 无巨型模块 |
| 单一真相源 | 人工审查 | 调度状态仅在 scheduler 库; 效果状态仅在 effect_ledger; 无第二调度器 |
| 落盘守卫 | db.connect 每次连接强制 guard | 无法绕过(4 项隔离实验) |

结论: **结构合理**。分层为 db/guard(基座) → kernel/evidence/sched/evolution(机制) → runtime(编排) → cli(接口), 依赖严格单向; runtime 是唯一编排点, 接口层不触执行逻辑。

## 二、逐模块论证与验证

| 模块 | 关键不变量 | 覆盖测试 | 判定 |
|---|---|---|---|
| db.py | WAL+synchronous=FULL; 每连接过守卫 | 全部测试间接覆盖 | ✅ |
| guard.py | fail-closed; 只约束 HETU_*; 禁词拼接自扫描不携带明文 | test_isolation ×4 | ✅ |
| effect_ledger.py | 三态提交; fencing 拒僵尸; 孤儿禁盲接管; reversible 决定降级; **CONFIRMED 禁重执行(P3 修复)** | A1×8 + FAULT×12 | ✅ 修复后 |
| step_writes.py | 未完成态不写行 → 重放幂等 | P2 e2e | ✅ |
| chain.py | 哈希链篡改可检测; **并发 append 不断链(P1 修复: BEGIN IMMEDIATE)** | A2 + 新并发回归 | ✅ 修复后 |
| probes.py | 探针结论权威, self_report 不作数 | 组合故障×3 | ✅ |
| stall.py | 迟滞防抖 | D1 | ✅ |
| fork.py | 工件不可变(主键拒覆盖); 污染 BFS 传播; 晋级需 ACTIVE | D1×多项 | ✅ |
| archive.py | 压缩只标记, 原文永不删除 | D1 | ✅ |
| recovery.py | plan_hash 漂移即升级, 不静默续跑 | D1 | ✅ 注1 |
| hitl.py | 挂起落盘重启不丢; 仅 PENDING 可放行(幂等) | D1 | ✅ |
| heartbeat.py | 检查点持久化, stale 判定 | D1 | ✅ |
| sandbox.py | JSON 白名单 + 全 dunder 键拒绝 | A6 | ✅ |
| scheduler.py | 幂等槽; 漏跑台账三策略; 槽级 fencing; 投递执行解耦 | L1×5 + FAULT | ✅ 注2 |
| evolve.py | 评分器物理隔离; **评分时刻即校验(P2 修复)**; 晋级四门 | L3×5 + 新回归 | ✅ 修复后 |
| runtime.py | 孤儿/UNCERTAIN 同路对账; 无探针转 RECONCILE 不盲重放 | P2 e2e×7 | ✅ |
| cli.py | 自检只读冒烟, 不触业务 | 打包冒烟 | ✅ |

## 三、深度检测抓出的缺陷(全部先证红→修复→回归固化)

1. **P1 证据链并发断链**: append 的"读 prev_hash→插入→回填哈希"非原子, 8 线程并发在 seq 6 断链。修复: BEGIN IMMEDIATE 单写事务。
2. **P2 评分器篡改评分时刻无感**: 篡改 vault 文件后 EvolverView.score 照常返回篡改值, 完整性只在晋级门暴露。修复: score() 前置 verify_integrity, 违规抛 ScorerTamper。
3. **P3 CONFIRMED 效果可重复执行**: acquire 未拦 CONFIRMED 态, 直接 ledger 用户可二次执行外部副作用。修复: 抛 AlreadyConfirmed(重放必须读回执)。runtime 因先行检查未受影响, 属 API 层缺口。
4. 次要: scheduler.fire 以字符串匹配 UNIQUE 判重 → 改捕 sqlite3.IntegrityError。

注1: recovery.save 允许覆写 plan_hash, 强制点在 resume——调用纪律: save 仅用于任务建档。
注2: 调度槽租约过期允许接管(至少一次触发语义), exactly-once 由效果账本层负责——分层职责, 已在 FUNCTIONAL_SPEC 界定。

## 四、验证记录

- 探针三缺陷证红输出: P1 break at seq 6 / P2 score=999.0 放行 / P3 重复副作用 1 次
- 修复后: **70/70 全绿**(新增 tests/test_deep_audit.py ×3), M2 自基线 dup=0, isolation-check OK
- 回归测试永久固化于 tests/test_deep_audit.py
