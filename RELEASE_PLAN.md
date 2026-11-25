# 发布预案（Release Plan）

> 门禁第 5 维（发布后问题预案）+ 第 9 维（最终门禁）操作依据。总原则：稳字第一，发布只从干净 checkout 出。

## 版本与弃用策略

- 版本号遵循 SemVer；`0.x` 阶段视为不稳定契约：minor 位（0.3→0.4）允许破坏性变更，patch 位只做修复。
- SQLite 模式在 0.x 内**只前滚不回滚**（表结构幂等 CREATE，但数据不回退）：任何升级前用户须备份 `hetu.db`；此约束写入 README 升级节。
- 弃用策略：`0.x` 不承诺长期支持线；`1.0` 起保留最近两个 minor 的安全修复。

## 发布流程（每次发布严格执行）

1. **干净 checkout**：`git worktree add <中立路径> <发布commit>`（禁止从工作目录/部署目录打包；路径不得含旧产品树片段）。
2. **对发布 commit 复跑门禁**（旧树扫描不作数）：
   ```bash
   env -u HETU_HOME -u HETU_DB python3 -m unittest discover -s tests -t .   # 必须全绿
   python3 scripts/isolation_check.py        # C1–C4 全过
   python3 scripts/similarity_scan.py        # AUTOSCAN_PASS
   git grep -InE "(ghp_|AKIA|xoxb-|BEGIN .*PRIVATE KEY|sk-[A-Za-z0-9]{20,}|/Users/)" $(git rev-parse HEAD)  # 零命中
   ```
3. **首次发布专用——squash 初始提交**：开发历史含本机绝对路径（docs/evidence 旧版报告），首发以单提交树发布：
   ```bash
   git checkout --orphan release/v0.3.5 && git add -A && git commit -m "Hetu Agent v0.3.5 (initial public release)"
   ```
   发布仓只含 squash 后的历史；开发历史留在本地仓留底，不推公网。
4. **产物构建与登记**：从 squash 树构建 wheel + sdist（`uv build`），macOS app 走 `packaging/macos/build_macos_app.sh` + `--smoke` 冒烟；全部产物 sha256 登记入 `docs/evidence/ARTIFACTS.md` 与 GitHub Release 说明。
5. **tag + push**：`v0.3.5` 附 changelog（CHANGELOG.md 对应节）+ 已知问题清单 + 本预案链接。

## 回滚方案

- 上一版 tag 与全部产物（wheel/sdist/DMG + sha256）永久保留在 GitHub Releases；回滚 = 引导用户降级安装上一版产物。
- 数据兼容：0.x 回滚需用户恢复升级前 `hetu.db` 备份（README 升级节明示）；内核不做自动降级迁移。
- 发布后 48h 内发现 P0（数据损坏/安全）：撤回 Release（标记 withdrawn + 置顶公告），修复走热修版（patch 位）。

## 热修复与安全响应

- 维护者：HongYun.dev。安全漏洞按 SECURITY.md 承诺 5 个工作日内响应（private security advisory，先于公开 issue）。
- 热修流程：fix 分支 → 全量门禁（同上第 2 步）→ patch tag → Release；不允许跳过门禁直推 main。

## Issue 分诊节奏

- 每周一次（与实验室周评同日）：新 issue 分级 P0/P1/P2；P0（安全/数据丢失）48h 内响应。
- 已知问题清单随发布公开（CHANGELOG 对应节 + README「已知边界」，单机 SQLite 无多租户等边界见 SECURITY.md）。
