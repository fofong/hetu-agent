# Hetu Agent

**通用 Super Agent · 因果执行内核 × 多目标机制演化 · 洁净室独立实现**

Hetu（हेतु，梵文「因」）：每个动作可溯其因——每个外部副作用有持久化意图、幂等键与
可核验回执；每个结论有独立证据链。河图（Hétú）：演化不是随机扰动，而是 Tools/Skills/Logic
在可验证结构上的组合演化。

> 状态：**Phase 0 + Phase 1 完成，Phase 2 一体化运行时落地**（规范冻结、机制实验全绿、
> 可恢复任务执行器端到端验证）。旧产品行为基线对照（M2）为独立里程碑，待基准集定义。
> 本项目为独立洁净室实现，不复制任何上游代码（见 `PROVENANCE.md`、`docs/CLEANROOM_POLICY.md`），
> 并有**机器强制的洁净室隔离机制**（见 `docs/CLEANROOM_POLICY.md`）。

## 特性

- 🧾 **Durable Effect Ledger**：意图持久化 → 执行（租约+fencing）→ 三态提交
  （CONFIRMED / UNCERTAIN 先对账禁盲重放 / PAUSED 高风险转人工）
- 🔁 **step_writes 任务级幂等**：确定性 task_id，先写后 checkpoint，崩溃重放零重复
- 🌳 **fork 式分支纠正**：依赖污染传播失效化下游，未受污染成果保留，原子切换交付引用
- 📜 **哈希链证据账本**：自报绿≠实际绿，结论必须过独立探针
- ⏰ **Durable 调度基座**：幂等槽 / 漏跑台账（coalesce·per-run·skip+alert）/ 重入 fencing /
  断点重试 / 投递执行解耦
- 🧬 **演化层脚手架**：评分器物理隔离（进化体永不修改评分器）、隔离实验树、外部晋级门
- 🗄️ **压缩即归档**：追加归档，原文永不删除
- 🪶 **零第三方运行时依赖**：Python ≥3.9 stdlib + SQLite

## 快速开始

```bash
python3 -m unittest discover -s tests -v   # 运行全部机制实验（含反例夹具）
python3 -m hetu status                     # 内核自检
python3 scripts/run_experiments.py         # 生成 M1 证据包 docs/evidence/
python3 scripts/isolation_check.py         # 洁净室隔离发布门
python3 scripts/similarity_scan.py         # 发布前相似性扫描(对照上游, 输出聚合分数)
python3 scripts/m2_harness.py              # M2 Hetu 侧自基线(故障注入×副作用计量)
```

运行时用法（可恢复任务执行器）：

```python
from hetu.runtime import Step, TaskRunner

runner = TaskRunner("/var/lib/hetu/hetu.db", probes={"charge": query_bank_api})
out = runner.run_task("task-1", plan=["fetch", "charge", "notify"], steps=[
    Step("s1", "fetch", fetch_effect),
    Step("s2", "charge", charge_effect),                       # 回执丢失→对账, 不盲重放
    Step("s3", "notify", notify_effect, risk="high"),          # 高风险→PAUSED 转人工
])  # 崩溃后重跑同一调用: 已完成步骤零重复, 断点续算
```

## macOS 桌面预览

桌面提供多标签会话、项目分组、全文搜索、置顶和摘要。模型来源有两个：本机 Ollama（端口 `11434`）与用户配置的 OpenAI 兼容服务（仓库不内置任何远端端点，通过「设置 → 模型」接入项或环境变量 `HETU_HOST66_BASE_URL` / `HETU_HOST66_API_KEY` 配置，见 `config.example`）。在「设置 → 模型」刷新列表、选择默认模型，并设置全局推理强度 `auto/off/minimal/low/medium/high/xhigh/max`；输入栏可为当前会话选择模型。聊天支持流式输出、停止、失败保留与恢复。记忆设置展示 MemoraX 本机记忆源，并可由用户手动开启 iCloud Drive / Google Drive 只追加同步（默认关闭）。任一模型来源可用即可对话；全部不可用时仍可保存草稿。右栏显示运行证据，底栏显示诊断输出。工具调用与任务交付仍待接入。参见 [桌面设计](DESIGN.md)。

在已安装 Xcode 的 macOS 上，用 PNG 图标构建至一个尚不存在的路径：

```bash
HETU_ICON=/absolute/path/icon.png bash packaging/macos/build_macos_app.sh "$PWD/build/Hetu Agent.app"
"$PWD/build/Hetu Agent.app/Contents/MacOS/HetuAgent" --smoke
open "$PWD/build/Hetu Agent.app"
```

冒烟检查会验证布局、草稿、项目和诊断，并通过回环 HTTP 夹具验证 Ollama 两轮模型会话、OpenAI 兼容通道一轮会话及重载。日常数据位于 `~/Library/Application Support/Hetu Agent/`，其中 `Workspace.json` 保存消息、草稿和项目，`Evidence/` 保存 M2 报告。预览依赖宿主 Xcode 的 Python 与 PyObjC。

## 架构（五层）

```
L4 接口层     CLI · macOS 桌面工作台预览（本地验证与证据）· A2A/IM 预留
L3 演化层     隔离实验树 · 评分器物理隔离 · 晋级门（外部监督者签名）
L2 调度基座   幂等槽 · 漏跑台账 · fencing · 断点重试 · 投递解耦
L1 证据层     哈希链账本 · 独立探针 · 滞回 stall · 孤儿对账
L0 因果内核   Effect Ledger · step_writes · fork 污染传播 · 归档 · 恢复点 · HITL
```

## 文档

- `docs/CLEANROOM_POLICY.md` — 洁净室开发纪律与隔离守卫说明
- `docs/CLA.md` — 贡献者许可协议 v2.1（MIT + 非独占；签署通道：PR 内评论一句，见 CONTRIBUTING.md）
- `docs/FUNCTIONAL_SPEC.md` — 功能规格书（Phase 0 冻结件）
- `docs/CLEANROOM_POLICY.md` — 洁净室六步纪律与访问日志
- `docs/RIGHTS_CHAIN.md` — 权利链协议（MIT + 非独占 CLA）
- `docs/adr/ADR-0001-kernel.md` — 内核架构决策
- `docs/evidence/M1_REPORT.md` — 「声称→实测证据→判定」对照表
- `PROVENANCE.md` — 来源与独立性证据

## 红线（不可妥协）

不搬图引擎 · 不建 Temporal server · 不建第二调度器 · 不做记忆双源 · LLM 自评不作结论 ·
不引 AutoGen 依赖 · telemetry 不外发 · 进化体不得修改评分器与保护机制 · 禁止假通过 ·
不做免审批动态委派 · 压缩永不删除原文

## License

MIT © 2026 HongYun.dev — see [LICENSE](LICENSE) and [NOTICE](NOTICE).
