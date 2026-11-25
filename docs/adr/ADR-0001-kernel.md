# ADR-0001 · Hetu 内核架构决策（初版，Phase 2 详细设计呈审件）

状态：**Accepted（2026-11-18，负责人指示"继续"，按最稳方案以本文为准开工 Phase 2）** · 日期：2026-11-18

## Phase 2 范围裁决（未决问题之最稳抉择，2026-11-18）

1. ADR-0001 原样批准，不扩权：机制清单以冻结规格为准，超出另立项。
2. Phase 2 先交付一体化运行时（`hetu/runtime.py`：恢复点+step_writes+ledger+HITL+
   heartbeat 组装 + L2 run_due），**旧产品行为基线对照（M2）推迟到基准集定义后**——
   对照需要可比较任务集与影子运行窗口，仓促对照=假通过风险，故拆为独立里程碑。
3. 隔离守卫接线在 `db.connect()`（每次连接强制），fail-closed；宿主旧产品环境变量
   不算违规，只约束 Hetu 自身落盘与配置。
4. 未完成态（PAUSED/UNCERTAIN/崩溃）一律以异常表达、不写 step 行，保证重放幂等。

## 决策

1. **单一 SQLite 库为执行侧真相源**。表：effect_ledger、step_writes、artifacts、
   delivery_refs、evidence_chain、interrupts、recovery_points、heartbeats、jobs、
   job_slots、missed_ledger、deliveries、archives。业务事实在 control-plane（Avatar）
   侧，执行轨迹在 Hetu 侧，互不冒充（公理5）。
2. **写路径纪律**：意图先落盘再执行外部效果（outbox）；checkpoint 在效果回执之后；
   WAL + synchronous=FULL 保证单机崩溃一致性；跨机时以租约+fencing token 取代假设。
3. **三态提交**：CONFIRMED / UNCERTAIN（对账前禁 acquire）/ PAUSED（高风险转人工）。
   UNCERTAIN 永不视为失败盲目重试。
4. **Ledger 降级语义**：ledger 损坏时普通操作 fail-open+本地告警、高风险 fail-closed。
   接受理由：可用性优先于普通操作强一致，风险敞口由高风险分级收窄。
5. **产物不可变 + 逻辑 fork**：纠错产生新分支产物，污染 BFS 失效化下游，交付引用
   delivery_refs 单行原子切换。不做文件系统/外部世界回滚。
6. **演化隔离**：评分器物理隔离（目录+sha256 清单），演化体仅持只读视图；晋级四门
   （完整性/可复现/优于父代/外部签名）。Hetu 永不修改自身验收器。
7. **零第三方运行时依赖**：Python stdlib + SQLite。接口层（控制台/A2A/IM）为独立
   进程，经 CLI/文件契约与内核交互，UI 永不触执行逻辑。

## 后果

- 正面：可审计、可恢复、可停演化；发布面极小，供应链风险≈0。
- 代价：无图引擎表达力、无分布式调度（欠账清单已列）；SQLite 写吞吐上限（单机场景可接受）。
