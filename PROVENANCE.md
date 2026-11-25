# PROVENANCE — 来源与独立性记录

2026-11-18 桌面适配补充。早期桌面预览使用过 前作 `f8bcc5e5a6` 的 HongYun 共用图片，SHA-256 为 `cbcd8c242b7ad17b8740e47a0f1f97c06d5b8a82d5ee175c334867a5f09f4385`。当前构建使用 Hetu 字标。设置搜索排序、标签手势与布局缩略图直接改编自同一前作提交，由 [桌面移植目录](packaging/macos/hasu_port/SOURCE.md) 记录上游文件并随包保留原 LICENSE 和 NOTICE。早期洁净室记录与扫描结论覆盖原实现批次。

本文件只记录**来源证据**，不宣称版权。

## 实现来源

- Hetu Agent 内核由 HongYun 应用实验室于 2026-11 发起。macOS 桌面包含有来源声明的上游移植。
- 初始实现（v0.1.0，2026-11-18）由 编码代理依据
  `docs/FUNCTIONAL_SPEC.md` v0.1 编写；实现过程未读取旧产品任何源码文件
  （访问日志见 `docs/CLEANROOM_POLICY.md`）。
- 设计输入仅为：功能需求描述、公开论文/文档解读（arXiv:2610.15150 解读、六框架
  公开源码研究的机制结论层转述）、合法观察的输入输出行为。机制蓝本（LangGraph
  任务级幂等、OpenHands 事件溯源、Temporal 恢复语义、MAF 恢复点签名）只取概念，
  未引入任何其代码或依赖。

## 依赖清单

- 内核运行时：Python 标准库与 SQLite。桌面依赖系统 WebKit 和宿主 PyObjC。可选本机模型连接使用 Ollama HTTP 接口，应用包不分发 Ollama 或模型。
- 开发/测试：unittest（stdlib）。**第三方开发依赖：无。**

## 独立性检查记录

| 日期 | 检查 | 结果 |
|---|---|---|
| 2026-11-18 | 依赖扫描（import 全树枚举） | 仅 stdlib（见 docs/evidence/） |
| 2026-11-18 | 上游源码访问日志 | 零访问 |
| 2026-11-18 | 隔离门活体测试：克隆入旧产品树内运行 | 被守卫拒绝（fail-closed 生效）；中立目录复验 58 项全绿 |
| 2026-11-18 | token 5-gram 相似性扫描 vs 上游产品源码（9074 文件） | max Jaccard 0.0255 < 0.25，**AUTOSCAN_PASS**（自动文本筛查结论，不构成法律上独立创作认证；docs/evidence/similarity/） |
