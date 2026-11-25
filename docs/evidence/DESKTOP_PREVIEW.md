# Hetu Agent macOS 桌面预览验证

前作移植版由 `bash packaging/macos/build_macos_app.sh <app>` 构建。包内 `hasu_port/LICENSE` 和 `NOTICE` 均经 `cmp` 验证与仓库记录一致。应用的 `--smoke` 验证了直接移植的搜索排序、标签关闭手势和缩略图，以及面板尺寸重载。输出为 `GUI-SMOKE-OK`。实机打开布局编辑器，看到三个预设和尺寸滑块。

单行顶栏版验证覆盖布局预设、镜像、重载恢复、重置和设置搜索定位。新版验证另外覆盖 Hetu 文字字标、模型枚举、两轮上下文、失败时保留输入及会话重载。原生窗口的无模型状态、模型设置入口和离线草稿按钮已实机查看。

2026-11-18 · 包版本 0.3.2 · 本地工作树构建

| 声称 | 实测证据 | 判定 |
| --- | --- | --- |
| macOS 会话界面能使用并保存草稿 | `HetuAgent --smoke` 新建项目、提交目标草稿、验证搜索空结果、开启摘要、重新加载原生页面并重新打开草稿 | `GUI projects, session search, reload and settings OK` |
| 桌面分区和设置已接线 | 实机对照前作 主窗口和设置浮层；原生冒烟新开标签、切换并恢复未保存目标，搜索设置，展开证据栏和诊断栏，核对两处收到真实运行结果 | `GUI tab isolation, settings search and workspace panes OK` |
| 会话和项目行可直接操作 | 原生冒烟将会话移出并移回项目、改名后重新加载，检查未保存标签的取消关闭和明确丢弃；另实机查看了紧凑布局与标题栏 | `GUI session move, project rename and unsaved close protection OK` |
| 原生桥接能传回真实结果 | `--smoke` 逐个点击自检、机制测试、M2 自基线、隔离检查；证据页逐项收到非空输出和退出码 0；检查 M2 同时写出 JSON 和 Markdown | `GUI-SMOKE-OK` |
| 机制测试与隔离检查通过 | `/usr/bin/python3 -m unittest discover -s tests`：70 项通过；`/usr/bin/python3 scripts/isolation_check.py`：C1–C4 通过 | `OK` |
| 构建不依赖旧应用 | `bash packaging/macos/build_macos_app.sh` 指向新的 `.app` 输出路径，嵌入启动器内核自检成功 | `verdict: OK` |

本轮的参考输入和界面边界见 [DESIGN.md](../../DESIGN.md)。本记录只覆盖本机桌面预览；不代表 M2 跨产品对照、签名公证或生产就绪。仓库没有 `.ai_runtime/scripts/harness_gate.py`，该门未验证。

模型冒烟使用本机回环 HTTP 夹具，真实 Ollama 进程没有在本机端口监听。当前包位于 `build/hetu-adapted-20261118-162457/Hetu Agent.app`。打包后检查 `Contents/Resources/branding` 不存在，常规启动显示自有字标。

## 0.3.5 全量回归与本机安装

2026-11-18 · 工作树版本 0.3.5

| 声称 | 实测证据 | 判定 |
| --- | --- | --- |
| 推理强度与聊天上下文 | `python3 -m unittest tests.test_model tests.test_local_chat tests.test_model_providers -v`；OpenAI 兼容档位逐项检查 `none/minimal/low/medium/high/xhigh/max`，Ollama 检查 `off` 与各级 `think=true` 映射，并验证最近完整轮次预算与当前提问保留 | `41 tests OK` |
| 实际推理端点 | 配置的远端端点以 `effort="xhigh"` 执行“只回复：OK”往返 | 返回 `OK` |
| 全项目回归 | `python3 -m unittest discover -s tests -t . -v`，包含可达配置端点的默认模型实连及记忆云桥假 CLI | `124 tests OK` |
| 桌面工作流与字体 | 新构建 `.app` 执行 `--smoke`，验证布局、会话、隔离测试、运行时 HITL、Enter 发送、`xhigh` 传播、流式回复、失败恢复、提供方管理、记忆云面板和隔离状态夹具；实际窗口复核字体层级 | `GUI-SMOKE-OK` |
| 洁净室发布扫描 | `python3 scripts/similarity_scan.py` | `AUTOSCAN_PASS`，25 个 Hetu 文件，最高 Jaccard 0.0255 |
| Python wheel 安装 | 构建 `hetu_agent-0.3.5-py3-none-any.whl`，安装到隔离目录并运行 `python -m hetu status` | `verdict: OK` |
| 本机安装 | 安装至 `~/Applications/Hetu Agent.app`；包版本为 `0.3.5`，关键模型、聊天、GUI 和 `memory_cloud.py` 文件与通过冒烟的构建一致；内核 `status` 自检通过；保留旧包备份 | 安装文件核对通过 |
| 强制 harness | `python3 .ai_runtime/scripts/harness_gate.py` | 未运行：仓库缺少该脚本；不能记为通过 |

本次 GUI 冒烟从构建目录通过，记忆面板使用假状态，不触发真实云同步。曾有一次安装路径上的 GUI 冒烟因诊断证据页检查失败而自动回滚；原因未确认，因此不记为通过。最终安装包通过版本、关键文件一致性和内核 `status` 核验。安装时旧版窗口仍在运行，其进程保留在备份包中；新版本已位于标准安装路径，将在下次启动时生效。此记录是本机预览构建，不代表签名、公证或公开发布。
