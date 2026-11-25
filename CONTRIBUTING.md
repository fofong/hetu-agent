# Contributing to Hetu Agent

欢迎贡献。参与即视为接受本文件与 `docs/CLEANROOM_POLICY.md` 全部纪律。

## 硬性纪律

1. **洁净室**：禁止在本仓库开发期间读取旧产品源码树；禁止把任何上游代码、
   测试或其翻译/改写带入本仓库。
2. **红线**（README「红线」清单）任何一条被触碰的 PR 直接关闭。
3. **反例驱动**：新增机制必须附带实验 + 反例夹具（禁用被测机制必红）。只验本地状态
   不验外部回执的测试不算数（禁止假通过）。
4. **汇报纪律**：PR 描述一律「声称 → 实测证据 → 判定」，禁自报绿。
5. **架构偏离**：先改 `docs/FUNCTIONAL_SPEC.md` / ADR，再改代码。

## CLA（权利链）

贡献通过 **MIT + 非独占 CLA** 路线管理：你保留版权，签署 CLA 授予项目方不可撤销的
使用/修改/分发/约定再许可授权与专利授权（详见 `docs/CLA.md`、`docs/RIGHTS_CHAIN.md`）。

**签署流程（首个 PR 时，30 秒）**：在你的 PR 下评论一句签署语句即可，CI 的 `cla`
状态检查会自动记录签名（`docs/cla-signatures.json`，公开可审计）并通过：

- 英文：`I have read the CLA Document and I hereby sign the CLA.`
- 中文：`我已阅读 CLA 文档（docs/CLA.md）并确认签署 CLA`

签名以 GitHub 账号为准，一人一次，后续 PR 免签。维护方账号与机器人豁免。

## 开发

```bash
python3 -m unittest discover -s tests -v   # 全部实验须绿
python3 scripts/run_experiments.py         # 重新生成证据包
```

- Python ≥3.10，零第三方依赖（运行时与测试都是）。新增依赖须先过权利链与许可证审核。
- 提交信息：`feat|fix|docs|spec|evidence(scope): summary`。
