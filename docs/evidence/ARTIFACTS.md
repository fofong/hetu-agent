# 发布产物登记（ARTIFACTS）

## v0.3.5（2026-11-24 预构建，正式发布时须对 squash commit 重建并更新本表）

| 产物 | sha256 | 大小 |
|---|---|---|
| hetu_agent-0.3.5-py3-none-any.whl | `817aca890df5fe622d34530ec06e10f9bc0dbbf123ddf0e8a4d87184fb40b985` | 48K |
| hetu_agent-0.3.5.tar.gz | `ea046b44fb04fe32dc4500a90459b151d034dad3d6d65d41fe702371a1edf08a` | 60K |

- 构建源：干净 `git worktree` @ `94efc71`（非工作目录），`uv build`。
- 构建前门禁：干净 checkout 全量测试 124/124 OK（1 skip=活体模型测试按设计跳过）。
- 安装验证：全新 venv `uv pip install` wheel → `python -m hetu status` verdict OK，`third_party_deps 0`，import 版本一致。
- macOS app 产物：发布时按 RELEASE_PLAN.md 第 4 步构建 + `--smoke` 冒烟后登记。
