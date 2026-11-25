# Security Policy

## 当前版本安全姿态（v0.1.0，Phase 1）

- **无网络服务面**：内核为库+CLI，不监听端口，不外发 telemetry（红线）。
- **反序列化白名单**：外部输入仅接受 JSON 安全类型，魔法键（`__reduce__` 等）拒绝
  （`hetu/kernel/sandbox.py`）。
- **评分器物理隔离**：演化体无写路径，篡改可检测（清单哈希）。
- **高风险动作默认转人工**（PAUSED + HITL 持久挂起）。
- **ActionPolicy 策略门为 opt-in（0.3.x）**：`TaskRunner(policy=None)` 默认不启用策略门
  （构造时发显式告警）；启用后 fail-closed（无规则/求值异常/审计失败一律 DENY）。
  默认启用（随发行版提供默认规则集）计划于 v0.4。
- 已知边界：单机 SQLite，无多租户/权限体系（欠账清单，勿在共享环境暴露内核库文件）；
  `ScorerVault.score` 会 exec 受清单哈希保护的评分器代码——评分器文件本身即信任边界，
  安装评分器须监督者 admin token。

## 报告漏洞

在公开 issue 之前，安全漏洞请先通过 private security advisory 报告维护者
（HongYun.dev）。我们承诺 5 个工作日内响应。
