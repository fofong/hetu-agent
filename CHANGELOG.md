# Changelog

## [0.3.5] - 2026-11-18
### 隐私整改：移除全部内置内部端点（发布阻断项清零）
- `hetu/model.py`、`local_chat.py`、`model_providers.py`、`gui.html` 不再内置任何远端端点或内部模型名；远端一律经 `HETU_MODEL_BASE_URL` / `HETU_HOST66_*` 环境变量或接入设置显式配置（见新增 `config.example`），未配置时 fail-closed 并给出明确提示。
- 活体模型测试改为「环境提供 `HETU_MODEL_BASE_URL` 才运行」；文档与证据中的内部主机名、内网 IP、本机绝对路径全部泛化（`<UPSTREAM_A/B>` 占位）。
- 测试密封：`tests/__init__.py` 在导入时清除 Hetu 自有环境变量的宿主污染（HETU_HOME/HETU_DB/HETU_MODEL_*/HETU_HOST66_*），pytest 与 unittest 两种 runner 在任何宿主环境下结果一致（124 项）。
### 桌面字体、上下文与记忆接入收尾
- 桌面字体指定 macOS 与中文系统字体回退，改善辅助文字字号、行高和排版层级。
- 对话上下文保留最近完整轮次，并限制历史消息为 8,000 字符；当前提问始终保留。
- 完成 MemoraX 本地记忆与 iCloud Drive / Google Drive 开关面板；同步工具未安装、不可用或云端未就绪时提供状态提示。云开关默认关闭，冒烟使用隔离状态夹具。
- 增补全部推理强度档位、历史预算、桌面交互、记忆云桥和本机安装回归证据；未包含外部公开发布或签名公证。

## [0.3.4] - 2026-11-18
### 身份系统提示词 + 思考程度档位对齐前作
- 对话统一注入身份系统提示词（`hetu/model.py SYSTEM_PROMPT`）：助手自称 **Hetu super agent（河图超级智能体），由 HongYun 实验室开发维护**，不再暴露基座模型身份；内核 `model.reply()` 与桌面引擎 `request_reply` 双路径注入，调用方自带 system 时不重复注入；实测「你是谁」返回正确身份。
- 思考程度档位参照前作扩展：`auto/off/minimal/low/medium/high/xhigh/max`（前作的 ultra 被 llama.cpp 服务端拒绝，实测仅支持 minimal|low|medium|high|xhigh|max|none，故不收）；GUI 设置下拉、taskctl `--effort`、传输层映射同步。
- 测试：身份注入/不覆盖断言（stub sys=1/sys=0）、xhigh/max 档位注入；GUI 冒烟对话阶段新增 xhigh 端到端传播（远端回显 `eff=xhigh`）与身份系统提示词到达断言（夹具回显 `sys=1`）。全量 114/114。

## [0.3.3] - 2026-11-18
### 全局默认思考程度（effort）与对话细节打磨
- 内核 `hetu/model.py` 新增全局默认思考程度：`HETU_MODEL_EFFORT`（auto/off/low/medium/high，默认 auto=不下发参数）；`reply()` 按 OpenAI 兼容 `reasoning_effort`（off→none，llama.cpp 实测支持）注入；`taskctl model-ask --effort` 同步支持。
- 桌面传输层 `local_chat.py` 重写为流式：`reply_stream()` 支持 SSE（OpenAI 兼容）与 NDJSON（Ollama）增量解析、`on_delta` 增量回调、`should_stop` 协作式停止；Ollama 无分级旋钮，off→`think=false`、其余→`think=true`；连接失败统一包装为中文 ValueError。
- GUI 桥：逐 token delta 在 drain 时聚合为 `reply-delta` 批次下发（避免高频 JS 调用）；新增 `chatStop` 停止操作；chat 请求严格校验（角色交替/条数/长度）并归一 effort。
- 前端：Enter 发送 / Shift+Enter 换行（IME 合成安全）；流式增量渲染；生成中可停止（保留已生成文本）；设置页新增"默认思考程度"全局下拉；回复 Markdown 渲染（纯 DOM 构造，无 innerHTML）；消息一键复制；会话重命名。
- 测试：新增 `tests/test_local_chat.py`（effort 映射、SSE/NDJSON 流式、中途停止、错误包装）；`test_model.py` 增 effort 注入/env 用例；`test_taskctl.py` 增 `--effort` 取值校验；GUI 冒烟对话阶段升级为 Enter 发送 + effort 端到端传播（think=True / reasoning_effort=none 回显断言）+ 流式 + Markdown 渲染 + 停止/失败恢复。全量 112/112。
### 桌面接入 OpenAI 兼容主机大模型
- `local_chat.py` 新增 `OpenAIChat` 传输层（OpenAI 兼容 `/v1/models` + `/v1/chat/completions`，stdlib 实现，支持 Bearer 鉴权与 https）；端点由 `HETU_HOST66_BASE_URL` / `HETU_HOST66_API_KEY` 或接入设置配置，仓库不内置远端默认值。
- 桌面引擎双模型源：Ollama 与远端 OpenAI 兼容源并列刷新、合并去重，按模型名路由到来源；单源故障降级为 warning，双源全挂才报 error。
- 设置页新增远端 OpenAI 兼容接入条目；状态栏与提示文案改为通用"模型服务"。
- 冒烟夹具新增 `/v1` 端点；GUI 冒烟覆盖远端模型发现、远端一轮对话与重载恢复。

## [0.3.2] - 2026-11-18
### 结构与逐模块深度审计
- 修复 P1: 证据链并发 append 断链(chain.append 改 BEGIN IMMEDIATE 单写事务)
- 修复 P2: 评分器篡改在评分时刻无感(ScorerVault.score 前置完整性校验)
- 修复 P3: CONFIRMED 效果可被重复执行(acquire 抛 AlreadyConfirmed, 重放必须读回执)
- scheduler.fire 判重改捕 sqlite3.IntegrityError(不再字符串匹配)
- 新增 tests/test_deep_audit.py 三项回归; 全量 70/70; 审计报告 docs/STRUCTURE_AUDIT.md

## [0.3.1] - 2026-11-18

按验收评审收紧可靠性语义（三处结论界定全部采纳）：

- **组合故障补验（评审风险#1）**：新增实验"外部副作用成功 + 回执未持久化 + 租约
  到期 + 任务恢复"。证实并修复真实缺口：`acquire()` 原允许盲接管租约过期的
  EXECUTING，现一律 `NotReconciled`（必须先探针对账）；runtime 对孤儿 EXECUTING
  与 UNCERTAIN 同路对账，无探针转 RECONCILE，绝不盲重放。`reconcile()` 拒绝在
  租约仍活跃时抢先对账。已知边界如实记录：租约 TTL 必须大于效果最长执行时间，
  否则故障检测器失真（fencing 可拒僵尸账本写入，但无法撤销已落地外部效果）。
- **fail-open 收紧（评审风险#2）**：降级不再按任务风险标签，改按副作用性质——
  仅显式 `reversible=True`（纯记录/可逆）允许 fail-open+告警；不可逆外部副作用
  （默认）与高风险一律 fail-closed。
- **相似性结论界定（评审风险#3）**：判定改为 `AUTOSCAN_PASS`，明确为自动文本
  筛查结论，不构成法律上独立创作认证（PROVENANCE/报告同步）。
- 实验 63→67 全绿；M2 自基线重跑重复副作用 0。

## v0.3.0 — 2026-11-18

发布前债务清偿 + 故障注入矩阵补全：

- **相似性扫描发布门** `scripts/similarity_scan.py`：token 5-gram Jaccard 对照上游
  产品源码（9074 文件），全文件对 max Jaccard **0.0255**（阈值 0.25），判定
  INDEPENDENT，报告存 `docs/evidence/similarity/`。只输出聚合分数，不读回上游内容。
- **故障注入矩阵补全** `tests/test_fault_matrix.py`（备忘录 §5 六项全覆盖）：
  并发执行租约互斥（副作用恰好一次）、网络超时滞留 EXECUTING→对账→受控重放、
  DB 写失败普通降级 fail-open 带告警/高风险 fail-closed。实验 58→63。
- **M2 Hetu 侧自基线** `scripts/m2_harness.py`：5 故障场景 × 5 重复，
  总重复副作用 **0**（`docs/evidence/M2_SELF_BASELINE.md`）。旧产品侧对照待基准集评审。
- **CLA 草案** `docs/CLA.md`（MIT + 非独占 CLA，贡献者保留版权；待法务定稿与签署通道）。
- 打包验证：sdist + wheel 构建、干净 venv 安装冒烟通过。

## v0.2.0 — 2026-11-18

严格区别机制（机器强制）+ Phase 2 一体化运行时：

- **与旧产品树严格区别**：运行时隔离守卫（`hetu/guard.py` 接线 `db.connect`，
  落盘/配置命中旧产品树 fail-closed）、静态发布门 `scripts/isolation_check.py`
  （代码零引用/命名自指/守卫在位/包位置）、`docs/CLEANROOM_POLICY.md`（洁净室纪律）、
  反证实验 `tests/test_isolation.py`。守卫语义修正一处：宿主旧产品环境变量不算违规，
  只约束 Hetu 自身（消除开发机误报）。
- **Phase 2 一体化运行时** `hetu/runtime.py`：TaskRunner（plan-hash 恢复点 +
  step_writes×Effect Ledger + HITL + heartbeat）与 L2 `run_due`；端到端实验含
  崩溃恢复副作用零重复、回执丢失对账续跑、高风险 PAUSED→放行、计划漂移转人工。
- ADR-0001 批准（Accepted）+ Phase 2 范围裁决（M2 对照拆独立里程碑）。
- CI workflow（3.9/3.12/3.13 矩阵，含隔离门与证据再生成）。实验总数 47 → 58。

## v0.1.0 — 2026-11-18

Phase 0 + Phase 1（独立根目录立项）：

- 立项深度论证（法律/技术/经济 + 红线自检）、功能规格书 v0.1 冻结、洁净室纪律、
  权利链协议（MIT + 非独占 CLA）、ADR-0001 初版。
- L0 因果执行内核：Durable Effect Ledger（三态提交/租约+fencing/对账/损坏降级）、
  step_writes 任务级幂等、fork 污染传播+原子交付切换、压缩即归档、plan-hash 恢复点、
  HITL 持久挂起、heartbeat 断点续算、反序列化白名单。
- L1 证据层：哈希链账本、独立探针结论门、滞回 stall、孤儿对账。
- L2 调度基座：幂等槽、漏跑台账三策略、重入 fencing、断点重试、投递执行解耦。
- L3 演化层脚手架：评分器物理隔离、隔离实验树、晋级四门。
- 实验套件 A1~A6 + D1：47 项，全部含反例夹具（禁用机制必红），全绿。
- 开源发布件：MIT LICENSE、NOTICE、PROVENANCE、CONTRIBUTING、SECURITY、pyproject。
