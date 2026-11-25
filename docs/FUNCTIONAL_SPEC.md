# Hetu Agent 功能规格书 v0.1（Phase 0 冻结件）

> 规范来源：使用需求、公开功能描述与合法观察到的输入输出行为。
> 旧产品源码**不是**本规格书的输入，任何实现人员/编码 Agent 不得读取其源码。

## 0. 范围与栈

- 目标：可恢复自主执行 + 机制层自进化的通用智能体执行内核。
- 栈：Python ≥3.10 标准库 + SQLite。零第三方运行时依赖。单机起步。
- 非目标（欠账清单，另立项）：规划错误语义识别、saga 补偿 DSL、多租户权限、
  跨机分布式调度、亚分钟调度精度、mid-inference 拦截。

## 1. 五条设计公理（不可妥协）

1. **因果执行**：外部副作用 = 意图持久化 → 执行（租约+fencing）→ 三态提交
   （CONFIRMED / UNCERTAIN 先对账禁盲重放 / PAUSED 高风险转人工）。
2. **证据优先**：自报绿≠实际绿；LLM 自评只作触发器；进化体永不修改评分器/验收器/
   测试标准/最终保护机制。
3. **成果保护**：纠错≠回滚；保留未受污染成果；失效化全部下游；产物不可变；
   验收后原子切换交付引用。
4. **演化可停**：演化只在隔离实验树；晋级须外部监督者独立验收；机制独立 flag 可回滚。
5. **单一真相源**：调度、事实、证据各一源；不建第二调度器/记忆双源/checkpointer 双状态。

## 2. 分层功能需求

### L0 因果执行内核
- FR-L0-1 Effect Ledger：`intent/acquire/execute/reconcile`；幂等键去重；租约+fencing
  token 严格递增；UNCERTAIN 禁 acquire 直至对账；高风险 intent 直接 PAUSED。
- FR-L0-2 Ledger 自身故障降级：按副作用性质而非任务风险标签——仅显式声明可逆
  （reversible）的纯记录操作 fail-open+本地告警；不可逆外部副作用（默认）与高风险
  fail-closed。
- FR-L0-2b 孤儿执行禁止盲接管：EXECUTING 且租约过期者，acquire 一律拒绝
  （NotReconciled），必须先经独立探针对账；租约仍活跃时禁止抢先对账。
  已知边界：租约 TTL 必须大于效果最长执行时间，否则故障检测失真。
- FR-L0-3 step_writes：确定性 task_id；先写后 checkpoint；重放零副作用；
  与 ledger 组合覆盖「外部成功但 checkpoint 前崩溃」窗口。
- FR-L0-4 fork 分支纠正：产物记录 input_hash/output_hash/dependency_ids/effect_refs/
  validator_version；污染 BFS 传播失效化下游；原产物不可变；delivery_ref 原子切换。
- FR-L0-5 压缩即归档：追加归档，原文永不删除，工作集以归档标记缩小。
- FR-L0-6 plan-hash 恢复点：漂移拒续并自动开 HITL interrupt。
- FR-L0-7 HITL 持久挂起：interrupt 落盘、跨进程重启存活、interrupt_id 定向放行。
- FR-L0-8 heartbeat：检查点持久化，断点续算。
- FR-L0-9 反序列化白名单：仅 JSON 安全类型；魔法键拒绝。

### L1 证据与观察层
- FR-L1-1 哈希链证据账本：prev_hash 链接，任意篡改可定位首个断点。
- FR-L1-2 独立探针结论门：自评与探针冲突以探针为准；无探针不给结论。
- FR-L1-3 滞回 stall 计数：连续 N 拍无进展才触发，仅触发 replan，不裁决失败。
- FR-L1-4 孤儿 action 对账：租约过期的 EXECUTING 可枚举、可探针定案。

### L2 调度基座
- FR-L2-1 幂等槽：唯一键 (job_id, scheduled_instant, trigger_type)，重复投递不产生第二份工作。
- FR-L2-2 漏跑台账 + 补跑策略：coalesce / per-run / skip+alert，漏跑全部落台账。
- FR-L2-3 重入 fencing：租约内唯一持有者；token 递增；僵尸完成写入被拒。
- FR-L2-4 断点重试：FAILED 槽保留在台账可重试，attempts 计数。
- FR-L2-5 投递执行解耦：投递独立记账可 ack，执行不依赖投递回执。

### L3 演化层（脚手架，Phase 3 填充算法）
- FR-L3-1 评分器物理隔离：文件+sha256 清单；演化体只读视图；篡改可检测。
- FR-L3-2 隔离实验树：mutation_type ∈ {tools, skills, logic}，prompt-only 拒绝。
- FR-L3-3 晋级门：评分器完整 + 可复现 + 指标优于父代 + 外部监督者签名，四门齐过。

### L4 接口层
- macOS 桌面预览提供本地目标草稿和项目组织。工作台通过固定命令运行内核自检、机制测试、M2 自基线与隔离检查，展示日志和实际退出码。诊断使用本地夹具；UI 不接管内核执行逻辑和生产状态。
- 桌面可显式向本机模型发送文本，保存成功回复和会话历史。模型连接、草稿和诊断各自显示真实状态。对话可读取最近 15 轮作为上下文，历史仍在本机完整保存至工作区大小上限。
- 工具执行、A2A、IM 和 Avatar 对接保留为后续范围。演化晋级由外部监督者验收。

## 3. 验收门槛（冻结）

- M0 规范冻结：本文 + CLEANROOM_POLICY + RIGHTS_CHAIN 呈审。
- M1 机制全绿：A1~A6 + D1 反例驱动全绿（含回执丢失夹具、ledger 损坏夹具）。
- M2 内核对照：同任务集 Hetu vs 旧产品 行为一致率达标，崩溃恢复副作用零重复。
- M3 演化验证：隔离树结构变异可复现提升且评分器零篡改。
- M4 切换评审：全部门槛 + 影子运行 48h 对账（误拦率 <1%）。
- 汇报纪律：一律「声称→实测证据→判定」对照表，禁自报绿。
