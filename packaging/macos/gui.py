"""Hetu desktop workspace using WKWebView and the Xcode Python bridge."""

import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading

import objc
from AppKit import (NSAppearance, NSAppearanceNameDarkAqua,
                    NSApplication, NSApplicationActivationPolicyRegular,
                    NSColor, NSMakeRect, NSMakeSize, NSWindow,
                    NSWindowStyleMaskClosable, NSWindowStyleMaskMiniaturizable,
                    NSWindowStyleMaskResizable, NSWindowStyleMaskTitled,
                    NSWindowStyleMaskFullSizeContentView, NSWindowTitleHidden)
from Foundation import NSObject, NSTimer
import model_providers
import memory_cloud

objc.loadBundle("WebKit", bundle_path="/System/Library/Frameworks/WebKit.framework",
                module_globals=globals())
objc.registerMetaDataForSelector(b"WKWebView", b"evaluateJavaScript:completionHandler:", {
    "arguments": {3: {"callable": {"retval": {"type": b"v"}, "arguments": {
        0: {"type": b"^v"}, 1: {"type": b"@"}, 2: {"type": b"@"},
    }}}},
})

RES = Path(__file__).resolve().parent
SRC = RES / "src"
DATA = Path.home() / "Library" / "Application Support" / "Hetu Agent" / "Evidence"
sys.path.insert(0, str(SRC))
from hetu import __version__ as VERSION
import local_chat

JOBS = {
    "selfcheck": ["-m", "hetu", "status"],
    "tests": ["-m", "unittest", "discover", "-s", str(SRC / "tests")],
    "m2": [str(SRC / "scripts" / "m2_harness.py")],
    "isolation": [str(SRC / "scripts" / "isolation_check.py")],
}

TASKCTL_CMDS = {"run", "status", "tasks", "interrupts", "release", "evidence",
                "jobs", "add-job", "fire", "run-due", "model-status", "model-ask"}


class Engine(NSObject):
    def configure_data_(self, webview, data):
        self.webview = webview
        self.data = data
        self.events = queue.Queue()
        self.active = None
        self.last_result = None
        self.providers_path = None   # set in main() before first use
        self.provider_cfg = model_providers.defaults()
        self.provider_error = None
        self.provider_clients = {}
        self.rebuild_provider_clients()
        self.models = []
        self.model_sources = {}
        self.chat_pending = False
        self.chat_stop = False
        self.model_pending = False

    def tick_(self, _timer):
        batch = []
        for _ in range(256):
            try:
                kind, job, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "line":
                if not batch or batch[-1][0] != "lines":
                    batch.append(("lines", job, []))
                batch[-1][2].append(value)
            elif kind == "delta":
                if not batch or batch[-1][0] != "reply-delta":
                    batch.append(("reply-delta", None, []))
                batch[-1][2].append(value)
            elif kind == "done":
                batch.append((kind, job, value))
                self.last_result = (job, value)
                self.active = None
            elif kind == "taskctl":
                batch.append(("taskctl", job, value))
            elif kind in ("models", "reply"):
                if kind == "models":
                    self.models = value.get("models", [])
                    self.model_pending = False
                else:
                    self.chat_pending = False
                batch.append((kind, job, value))
            elif kind in ("providers", "provider-test", "memcloud"):
                batch.append((kind, job, value))
        if batch:
            self.webview.evaluateJavaScript_completionHandler_(
                "window.HetuAPI.receive(%s)" % json.dumps(batch), self.delivered_error_)

    def delivered_error_(self, _value, error):
        if error:
            print("GUI bridge: %s" % error.userInfo(), file=sys.stderr, flush=True)

    @objc.python_method
    def load_providers(self):
        self.provider_cfg, self.provider_error = model_providers.load(self.providers_path)
        self.rebuild_provider_clients()

    @objc.python_method
    def rebuild_provider_clients(self):
        self.provider_clients = {
            item["id"]: model_providers.client_for(item)
            for item in self.provider_cfg["providers"] if item["enabled"]}

    @objc.python_method
    def providers_view(self):
        view = {"config": model_providers.mask(self.provider_cfg),
                "kinds": model_providers.KINDS}
        if self.provider_error:
            view["error"] = self.provider_error
        return view

    @objc.python_method
    def request_providers(self, _request):
        self.events.put(("providers", None, self.providers_view()))

    @objc.python_method
    def request_providers_save(self, request):
        try:
            merged = model_providers.merge_keys(request.get("value"), self.provider_cfg)
            model_providers.validate(merged)
            model_providers.save(self.providers_path, merged)
        except (OSError, ValueError, AttributeError) as failure:
            self.events.put(("providers", None, {"error": "接入保存失败：%s" % failure}))
            return
        self.provider_cfg = merged
        self.provider_error = None
        self.rebuild_provider_clients()
        self.events.put(("providers", None, self.providers_view()))
        self.model_pending = False
        self.refresh_models()

    @objc.python_method
    def request_mem_status(self, _request):
        def worker():
            try:
                payload = memory_cloud.status()
            except Exception as failure:  # 兜底: worker 死亡会让界面永久停在忙碌态
                payload = {"error": "记忆状态查询异常：%s" % failure}
            self.events.put(("memcloud", None, payload))
        threading.Thread(target=worker, daemon=True).start()

    @objc.python_method
    def request_mem_toggle(self, request):
        provider = request.get("provider")
        enabled = request.get("on")
        if provider not in memory_cloud.PROVIDERS or not isinstance(enabled, bool):
            self.events.put(("memcloud", None, {"error": "云端开关请求无效。"}))
            return
        def worker():
            try:
                payload = memory_cloud.set_enabled(provider, enabled)
            except Exception as failure:
                payload = {"error": "云端开关切换异常：%s" % failure}
            self.events.put(("memcloud", None, payload))
        threading.Thread(target=worker, daemon=True).start()

    @objc.python_method
    def request_mem_sync(self, request):
        provider = request.get("provider")
        if provider is not None and provider not in memory_cloud.PROVIDERS:
            self.events.put(("memcloud", None, {"error": "云同步请求无效。"}))
            return
        def worker():
            try:
                payload = memory_cloud.sync(provider)
            except Exception as failure:
                payload = {"error": "云同步执行异常：%s" % failure}
            self.events.put(("memcloud", None, payload))
        threading.Thread(target=worker, daemon=True).start()

    @objc.python_method
    def request_provider_test(self, request):
        draft = request.get("draft")
        pid = request.get("id")
        if isinstance(draft, dict):
            item = {"id": pid or "draft", "name": draft.get("name") or "草稿",
                    "kind": draft.get("kind"), "base_url": draft.get("base_url"),
                    "api_key": draft.get("api_key") or "", "enabled": True}
            key = item["api_key"]
            if key.startswith(model_providers.MASK_PREFIX):
                stored = next((p for p in self.provider_cfg["providers"]
                               if p["id"] == pid), None)
                item["api_key"] = stored["api_key"] if stored else ""
        else:
            item = next((p for p in self.provider_cfg["providers"] if p["id"] == pid), None)
        if item is None:
            self.events.put(("provider-test", pid, {"error": "接入不存在。"}))
            return
        try:
            model_providers.validate({"version": model_providers.VERSION, "default": None,
                                      "providers": [dict(item, id=item["id"] or "draft")]})
        except ValueError as failure:
            self.events.put(("provider-test", pid, {"error": str(failure)}))
            return

        def worker():
            try:
                names = model_providers.client_for(item).models()
                result = {"ok": True, "count": len(names), "models": names[:20]}
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
                result = {"error": "无法连接：%s" % error}
            self.events.put(("provider-test", pid, result))

        threading.Thread(target=worker, daemon=True).start()

    @objc.python_method
    def refresh_models(self):
        if self.model_pending:
            return
        self.model_pending = True

        def worker():
            models, sources, errors, statuses = [], {}, [], []
            enabled = [item for item in self.provider_cfg["providers"] if item["enabled"]]
            for item in enabled:
                provider = self.provider_clients.get(item["id"])
                if provider is None:
                    errors.append("%s：配置无效" % item["name"])
                    statuses.append({"id": item["id"], "ok": False, "error": "配置无效"})
                    continue
                try:
                    names = provider.models()
                except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
                    errors.append("%s：%s" % (item["name"], error))
                    statuses.append({"id": item["id"], "ok": False, "error": str(error)})
                    continue
                for name in names:
                    if name not in sources:
                        sources[name] = provider
                        models.append(name)
                statuses.append({"id": item["id"], "ok": True, "count": len(names)})
            self.model_sources = sources
            result: dict = {"models": models, "providers": statuses}
            if errors and len(errors) == len(enabled):
                result["error"] = "无法连接模型服务：" + "；".join(errors)
            elif errors:
                result["warning"] = "部分模型源不可用：" + "；".join(errors)
            self.events.put(("models", None, result))

        threading.Thread(target=worker, daemon=True).start()

    @objc.python_method
    def request_reply(self, request):
        if self.chat_pending:
            return
        model = request.get("model")
        messages = request.get("messages")
        effort = local_chat.normalize_effort(request.get("effort"))
        provider = self.model_sources.get(model)
        if (provider is None or not isinstance(messages, list)
                or not 1 <= len(messages) <= 31 or len(messages) % 2 != 1
                or any(not isinstance(item, dict)
                       or item.get("role") != ("user" if index % 2 == 0 else "assistant")
                       or not isinstance(item.get("content"), str)
                       or not 1 <= len(item["content"]) <= 50_000
                       for index, item in enumerate(messages))):
            self.events.put(("reply", None, {"error": "请刷新模型列表并检查消息长度。"}))
            return
        messages = local_chat.bound_history(messages)
        self.chat_pending = True
        self.chat_stop = False
        messages = [{"role": "system", "content": local_chat.SYSTEM_PROMPT}] + \
            [{"role": item["role"], "content": item["content"]} for item in messages]

        def worker():
            def on_delta(chunk):
                self.events.put(("delta", None, chunk))

            try:
                text = provider.reply_stream(model, messages, effort=effort,
                                             on_delta=on_delta,
                                             should_stop=lambda: self.chat_stop)
                if len(text) > 50_000:
                    raise ValueError("模型回复超过 50,000 字符")
                result = {"text": text}
                if self.chat_stop:
                    result["stopped"] = True
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
                if self.chat_stop:
                    result = {"text": "", "stopped": True}
                else:
                    result = {"error": "生成回复失败：%s" % error}
            self.chat_stop = False
            self.events.put(("reply", None, result))

        threading.Thread(target=worker, daemon=True).start()

    @objc.python_method
    def request_chat_stop(self, _request):
        if self.chat_pending:
            self.chat_stop = True

    @objc.python_method
    def request_taskctl(self, request):
        rid = request.get("id")
        args = request.get("args")
        if (not isinstance(rid, int) or isinstance(rid, bool) or not isinstance(args, list)
                or not 1 <= len(args) <= 10
                or not all(isinstance(a, str) and len(a) <= 128 for a in args)
                or args[0] not in TASKCTL_CMDS):
            self.events.put(("taskctl", rid, {"error": "非法运行时命令。"}))
            return

        def worker():
            try:
                self.data.mkdir(parents=True, exist_ok=True)
                process = subprocess.run(
                    [sys.executable, "-u", "-m", "hetu.taskctl", "--db",
                     str(self.data / "hetu.db"), *args],
                    cwd=SRC, capture_output=True, text=True, timeout=120,
                    env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
                try:
                    payload = json.loads(process.stdout)
                except ValueError:
                    payload = {"error": "运行时输出无法解析：%s"
                               % ((process.stdout or process.stderr)[:200].strip())}
            except Exception as error:
                payload = {"error": "运行时命令失败：%s" % error}
            self.events.put(("taskctl", rid, payload))

        threading.Thread(target=worker, daemon=True).start()

    def startJob_(self, job):
        if job not in JOBS or self.active is not None:
            return
        self.active = job
        self.last_result = None

        def worker():
            report = None
            rc = 1
            try:
                args = [sys.executable, "-u", *JOBS[job]]
                with tempfile.TemporaryDirectory(prefix="hetu-diagnostic-") as scratch:
                    env = dict(os.environ, TMPDIR=scratch, PYTHONDONTWRITEBYTECODE="1")
                    if job == "m2":
                        self.data.mkdir(parents=True, exist_ok=True)
                        report = tempfile.mkdtemp(prefix="m2-", dir=self.data)
                        args.extend(["--output-dir", report])
                    with subprocess.Popen(args, cwd=SRC, env=env, stdout=subprocess.PIPE,
                                          stderr=subprocess.STDOUT, encoding="utf-8",
                                          errors="replace") as process:
                        for line in process.stdout:
                            self.events.put(("line", job, line.rstrip("\n")[:8192]))
                        rc = process.wait()
                if report and not all(Path(report, name).is_file() for name in
                                      ("M2_SELF_BASELINE.md", "m2_baseline.json")):
                    if rc == 0:
                        self.events.put(("line", job, "M2 未生成完整报告。"))
                        rc = 1
                    if not any(Path(report).iterdir()):
                        Path(report).rmdir()
                    report = None
            except Exception as error:
                self.events.put(("line", job, "无法完成检查：%s" % error))
                rc = 1
                report = None
            self.events.put(("done", job, {"rc": rc, "report": report}))

        threading.Thread(target=worker, daemon=True).start()


class Bridge(NSObject):
    def userContentController_didReceiveScriptMessage_(self, _controller, message):
        if not message.frameInfo().isMainFrame():
            return
        body = str(message.body())
        if body == "smokeReload" and self.smoke_html is not None:
            self.engine.webview.loadHTMLString_baseURL_(self.smoke_html, None)
            return
        if body == "smokeChatReload" and self.smoke_html is not None:
            self.delegate.chat_reloaded = True
            self.engine.webview.loadHTMLString_baseURL_(self.smoke_html, None)
            return
        if body == "providersDone" and self.smoke_html is not None:
            self.delegate.finishProviders()
            return
        if body == "memoryDone" and self.smoke_html is not None:
            self.delegate.finishMemory()
            return
        if body in JOBS:
            self.engine.startJob_(body)
            return
        try:
            request = json.loads(body)
        except ValueError:
            return
        if not isinstance(request, dict):
            return
        if request.get("op") == "refreshModels":
            self.engine.refresh_models()
            return
        if request.get("op") == "chat":
            self.engine.request_reply(request)
            return
        if request.get("op") == "chatStop":
            self.engine.request_chat_stop(request)
            return
        if request.get("op") == "taskctl":
            self.engine.request_taskctl(request)
            return
        if request.get("op") == "providers":
            self.engine.request_providers(request)
            return
        if request.get("op") == "providersSave":
            self.engine.request_providers_save(request)
            return
        if request.get("op") == "providerTest":
            self.engine.request_provider_test(request)
            return
        if request.get("op") == "memStatus":
            self.engine.request_mem_status(request)
            return
        if request.get("op") == "memToggle":
            self.engine.request_mem_toggle(request)
            return
        if request.get("op") == "memSync":
            self.engine.request_mem_sync(request)
            return
        if request.get("op") != "saveLibrary":
            return
        error = None
        scratch = None
        try:
            payload = json.dumps(request["value"], ensure_ascii=False)
            if len(payload.encode("utf-8")) > 8_000_000:
                raise ValueError("本地会话数据超过 8 MB。")
            self.library_path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=self.library_path.parent, delete=False,
                                             mode="w", encoding="utf-8") as stream:
                scratch = Path(stream.name)
                stream.write(payload)
            scratch.replace(self.library_path)
        except (OSError, KeyError, ValueError) as failure:
            if scratch is not None:
                scratch.unlink(missing_ok=True)
            error = "未保存草稿：%s" % failure
        self.engine.webview.evaluateJavaScript_completionHandler_(
            "window.savedLibrary(%s)" % json.dumps(error), self.engine.delivered_error_)


class Delegate(NSObject):
    def applicationDidFinishLaunching_(self, _note):
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)

    def applicationShouldTerminateAfterLastWindowClosed_(self, _note):
        return True

    def webView_didFinishNavigation_(self, webview, _navigation):
        data = {"projects": [], "sessions": [], "summaries": False}
        error = None
        try:
            data = json.loads(self.library_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or not isinstance(data.get("projects"), list) or not isinstance(data.get("sessions"), list):
                raise ValueError("数据格式不受支持")
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as failure:
            data = {"projects": [], "sessions": [], "summaries": False}
            error = "无法读取会话，原文件已保留：%s" % failure
        webview.evaluateJavaScript_completionHandler_(
            "window.HetuAPI.setup(...%s)" % json.dumps([str(self.engine.data), data, error]), self.loaded_error_)

    def loaded_error_(self, _value, error):
        if error:
            print("GUI load: %s" % error.userInfo(), file=sys.stderr, flush=True)
            if self.smoke:
                self.exitSmoke_("前端初始化失败")
            return
        if self.smoke:
            if getattr(self, "chat_reloaded", False):
                self.webview.evaluateJavaScript_completionHandler_(
                    """(() => {
                        const row = [...document.querySelectorAll('[data-session]')]
                            .find(item => item.textContent.includes('第一条测试消息'));
                        if (!row) return false;
                        row.click();
                        const messages = document.querySelectorAll('#messages .message');
                        return messages.length === 10 && messages[3].textContent.includes('第二轮回复')
                            && messages[5].textContent.includes('远端回复:远端测试消息|eff=xhigh')
                            && messages[7].textContent.includes('sys=1')
                            && messages[9].textContent.includes('const x = 1')
                            && !!messages[9].querySelector('pre code')
                            && !!messages[9].querySelector('strong');
                    })()""", self.chatReloaded_error_)
                return
            if self.library_path.exists():
                self.verifyReload()
                return
            self.webview.evaluateJavaScript_completionHandler_(
                """(() => {
                    document.querySelector('#new-project').click();
                    document.querySelector('#project-name').value = '试用项目';
                    document.querySelector('#project-form').requestSubmit();
                    const wait = (ready, next) => {
                        if (ready()) next(); else setTimeout(() => wait(ready, next), 25);
                    };
                    wait(() => document.querySelector('#project').options.length === 2, () => {
                        document.querySelector('#goal').value = '整理项目交付说明';
                        document.querySelector('#composer').requestSubmit();
                        wait(() => document.querySelector('[data-session]'), () => {
                            document.querySelector('#search').value = '不存在的目标';
                            document.querySelector('#search').dispatchEvent(new Event('input'));
                            if (!document.querySelector('#history').textContent.includes('未找到会话')) return;
                            document.querySelector('#search').value = '';
                            document.querySelector('#search').dispatchEvent(new Event('input'));
                            document.querySelector('#summaries').click();
                            wait(() => document.querySelector('[data-session] small'), () => {
                                const menu = () => document.querySelector('.history-row .row-action').click();
                                const move = value => {
                                    menu();
                                    const select = document.querySelector('#item-action-content select');
                                    select.value = value;
                                    [...document.querySelectorAll('#item-action-content button')]
                                        .find(button => button.textContent === '移动会话').click();
                                };
                                const project = document.querySelector('#project').value;
                                move('');
                                wait(() => !document.querySelector('details [data-session]'), () => {
                                    move(project);
                                    wait(() => document.querySelector('details [data-session]'), () => {
                                        document.querySelector('.project-entry > .row-action').click();
                                        document.querySelector('#item-action-content input').value = '交付项目';
                                        document.querySelector('#item-action-content form').requestSubmit();
                                        wait(() => document.querySelector('.project-name').textContent.includes('交付项目'), () => {
                                            const rowByText = text => [...document.querySelectorAll('.history-row')]
                                                .find(row => row.textContent.includes(text));
                                            const menuButton = label => [...document.querySelectorAll('#item-action-content button')]
                                                .find(button => button.textContent === label);
                                            document.querySelector('#new-session').click();
                                            document.querySelector('#goal').value = '临时删除测试';
                                            document.querySelector('#goal').dispatchEvent(new Event('input'));
                                            document.querySelector('#composer').requestSubmit();
                                            wait(() => rowByText('临时删除测试'), () => {
                                                rowByText('临时删除测试').querySelector('.row-action').click();
                                                menuButton('删除会话').click();
                                                if (!document.querySelector('#item-action-content p').textContent.includes('不可撤销')) return;
                                                menuButton('永久删除').click();
                                                wait(() => !rowByText('临时删除测试') && rowByText('整理项目交付说明'), () => {
                                                    document.querySelector('#new-project').click();
                                                    document.querySelector('#project-name').value = '临时删除项目';
                                                    document.querySelector('#project-form').requestSubmit();
                                                    wait(() => [...document.querySelectorAll('.project-name')]
                                                        .some(name => name.textContent.includes('临时删除项目')), () => {
                                                        const box = [...document.querySelectorAll('.project-entry')]
                                                            .find(item => item.textContent.includes('临时删除项目'));
                                                        box.querySelector('.row-action').click();
                                                        menuButton('删除项目').click();
                                                        if (!document.querySelector('#item-action-content p').textContent.includes('确定删除项目')) return;
                                                        menuButton('永久删除').click();
                                                        wait(() => ![...document.querySelectorAll('.project-name')]
                                                                .some(name => name.textContent.includes('临时删除项目'))
                                                            && document.querySelector('.project-name').textContent.includes('交付项目')
                                                            && document.querySelector('details [data-session]'), () => {
                                            document.querySelector('#layout-toggle').click();
                                            document.querySelector('[data-preset=simple]').click();
                                            wait(() => document.body.classList.contains('simple'), () => {
                                                document.querySelector('#layout-mirror').click();
                                                wait(() => document.body.classList.contains('mirrored'), () => {
                                                    const width = document.querySelector('[data-size=sessions]');
                                                    width.value = '246';
                                                    width.dispatchEvent(new Event('input'));
                                                    width.dispatchEvent(new Event('change'));
                                                    wait(() => library.layout.sizes?.sessions === 246, () =>
                                                        window.webkit.messageHandlers.hetu.postMessage('smokeReload'));
                                                    });
                                                });
                                                });
                                            });
                                            });
                                        });
                                        });
                                    });
                                });
                            });
                        });
                    });
                    return true;
                })()""", self.engine.delivered_error_)

    @objc.python_method
    def verifyReload(self):
            self.webview.evaluateJavaScript_completionHandler_(
                """(() => {
                    if (!document.body.matches('.simple.mirrored')) return false;
                    if (document.body.style.getPropertyValue('--session-width') !== '246px') return false;
                    document.querySelector('#layout-toggle').click();
                    document.querySelector('[data-preset=diagnostics]').click();
                    const wait = (ready, next) => ready() ? next() : setTimeout(() => wait(ready,next),25);
                    wait(() => !document.querySelector('#dock-log').hidden && !document.querySelector('#evidence-inline').hidden, () => {
                        document.querySelector('#reset-layout').click();
                        wait(() => !document.body.matches('.mirrored') && document.querySelector('#dock-log').hidden &&
                            !document.body.style.getPropertyValue('--session-width'), () =>
                            document.querySelector('#close-layout').click());
                    });
                    return true;
                })()""", self.layoutReady_error_)

    def layoutReady_error_(self, value, error):
        if error or not value:
            self.exitSmoke_("布局恢复失败")
            return
        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            0.1, self, "layoutTick:", None, False)

    def layoutTick_(self, _timer):
        self.webview.evaluateJavaScript_completionHandler_(
            "!document.querySelector('#layout-editor').open", self.layoutReset_error_)

    def layoutReset_error_(self, value, error):
        if error or not value:
            self.layoutReady_error_(not error, error)
            return
        print("GUI layout presets, mirror, sizing restore and reset OK", flush=True)
        self.verifyWorkspace()

    @objc.python_method
    def verifyWorkspace(self):
            self.webview.evaluateJavaScript_completionHandler_(
                """(() => {
                    if (document.querySelector('[aria-current=page]').dataset.page !== 'overview') return false;
                    if (document.querySelector('#welcome-brand').textContent !== 'Hetu Agent') return false;
                    const session = document.querySelector('details [data-session]');
                    if (!session || !session.querySelector('small') || !document.querySelector('#summaries').checked) return false;
                    if (!document.querySelector('.project-name').textContent.includes('交付项目')) return false;
                    session.click();
                    if (document.querySelector('#goal').value !== '整理项目交付说明') return false;
                    const saved = document.querySelector('.tab[aria-pressed=true]');
                    document.querySelector('#new-tab').click();
                    const firstDraft = document.querySelector('.tab[aria-pressed=true]');
                    const goal = document.querySelector('#goal');
                    goal.value = '未保存的临时目标';
                    goal.dispatchEvent(new Event('input'));
                    document.querySelector('#new-tab').click();
                    if (goal.value || document.querySelectorAll('.tab').length !== 4) return false;
                    const choose = id => document.querySelector('.tab[data-session-tab="' + id + '"]').click();
                    choose(firstDraft.dataset.sessionTab);
                    if (goal.value !== '未保存的临时目标') return false;
                    const target = () => document.querySelector('[data-session-tab="' + firstDraft.dataset.sessionTab + '"]');
                    const close = () => target().dispatchEvent(new MouseEvent('click', {button:0, metaKey:true}));
                    close();
                    const actions = document.querySelector('#item-actions');
                    if (!actions.open) return false;
                    actions.close();
                    if (goal.value !== '未保存的临时目标') return false;
                    target().dispatchEvent(new PointerEvent('pointerdown', {button:1}));
                    target().dispatchEvent(new PointerEvent('pointerup', {button:1}));
                    document.querySelector('#item-action-content button').click();
                    if (actions.open || document.querySelectorAll('.tab').length !== 3) return false;
                    choose(saved.dataset.sessionTab);
                    if (goal.value !== '整理项目交付说明') return false;
                    document.querySelector('.tab[aria-pressed=true]').dispatchEvent(new MouseEvent('contextmenu'));
                    [...document.querySelectorAll('#item-action-content button')].find(
                        button => button.textContent === '关闭其他标签').click();
                    if (actions.open || document.querySelectorAll('.tab').length !== 1) return false;
                    document.querySelector('#layout-toggle').click();
                    if (!document.querySelector('[data-preset=standard] .thumbnail-pane.resting')) return false;
                    document.querySelector('#close-layout').click();
                    document.querySelector('#sidebar-toggle').click();
                    if (!document.body.classList.contains('sidebar-hidden')) return false;
                    document.querySelector('#sidebar-toggle').click();
                    document.querySelector('[data-page=settings]').click();
                    const settings = document.querySelector('#settings');
                    if (!settings.open || !document.querySelector('#data-dir').textContent) return false;
                    document.querySelector('#open-settings-search').click();
                    const search = document.querySelector('#settings-search');
                    search.value = '目录 M2';
                    search.dispatchEvent(new Event('input'));
                    document.querySelector('#settings-results button').click();
                    if (document.activeElement.textContent.indexOf('M2') < 0) return false;
                    if (document.querySelector('#settings-diagnostics').hidden) return false;
                    document.querySelector('#wrap').click();
                    document.querySelector('#close-settings').click();
                    if (settings.open) return false;
                    document.querySelector('#rail-handle').click();
                    document.querySelector('#dock-toggle').click();
                    if (document.querySelector('#evidence-inline').hidden || document.querySelector('#dock-log').hidden) return false;
                    document.querySelector('[data-page=workbench]').click();
                    document.querySelector('[data-page=verify]').click();
                    if (!document.querySelector('#log').classList.contains('nowrap')) return false;
                    document.querySelector('#run').click();
                    document.querySelector('[data-page=evidence]').click();
                    return document.querySelectorAll('#cards .card').length === 4;
                })()""", self.smokeStarted_error_)

    def smokeStarted_error_(self, value, error):
        if error or not value:
            self.exitSmoke_("GUI 页面导航或日志设置失败")
            return
        self.pending_jobs = list(JOBS)
        print("GUI projects, session search, reload and settings OK", flush=True)
        print("GUI tab isolation, settings search and workspace panes OK", flush=True)
        print("GUI session move, project rename and unsaved close protection OK", flush=True)
        print("GUI session delete (confirm step) and project delete (confirm step) OK", flush=True)
        print("GUI upstream settings ranking, tab close gestures and layout thumbnails OK", flush=True)
        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            0.20, self, "checkSmoke:", None, True)

    def checkSmoke_(self, timer):
        result = self.engine.last_result
        if self.engine.active is not None or result is None:
            return
        timer.invalidate()
        job, value = result
        if job != self.pending_jobs.pop(0) or value["rc"]:
            self.webview.evaluateJavaScript_completionHandler_(
                "document.querySelector('#records').textContent", self.smokeFailure_error_)
            return
        expected = len(JOBS) - len(self.pending_jobs)
        script = """(() => {
            const rows = Array.from(document.querySelectorAll('#records article'));
            const rail = document.querySelectorAll('#rail-records article');
            const output = document.querySelector('#dock-log').textContent.trim();
            return rows.length === %d && rail.length === rows.length && !!output &&
                rows.every(row => row.textContent.includes('退出码 0') && row.querySelector('pre').textContent.trim());
        })()""" % expected
        self.webview.evaluateJavaScript_completionHandler_(script, self.smokeResult_error_)

    def smokeFailure_error_(self, value, _error):
        self.exitSmoke_("诊断失败：%s" % value)

    def smokeResult_error_(self, value, error):
        if error or not value:
            self.exitSmoke_("证据页没有收到实际诊断输出")
            return
        print("GUI job OK: %s" % self.engine.last_result[0], flush=True)
        if not self.pending_jobs:
            self.verifyRuntime()
            return
        job = self.pending_jobs[0]
        self.webview.evaluateJavaScript_completionHandler_(
            "document.querySelector('[data-job=%s]').click(); document.querySelector('#run').click(); document.querySelector('[data-page=evidence]').click(); true" % job,
            self.nextSmoke_error_)

    @objc.python_method
    def verifyRuntime(self):
        self.rt_stage = 0
        self.webview.evaluateJavaScript_completionHandler_(
            """(() => {
                document.querySelector('[data-page=runtime]').click();
                const wait = (ready, next) => ready() ? next() : setTimeout(() => wait(ready, next), 50);
                wait(() => rt.loaded, () => {
                    document.querySelector('#rt-task').value = 'smoke-task';
                    document.querySelector('#rt-run-form').requestSubmit();
                });
                return true;
            })()""", self.engine.delivered_error_)
        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            0.25, self, "checkRuntimeSmoke:", None, True)

    def checkRuntimeSmoke_(self, timer):
        stage = getattr(self, "rt_stage", 0)
        if stage == 0:
            script = "(() => { const b = document.querySelector('#rt-interrupts .release-btn');" \
                     " if (!b) return false; b.click(); return true; })()"
        elif stage == 1:
            script = "(() => { const r = document.querySelector('#rt-run');" \
                     " if (!r || r.disabled || document.querySelector('#rt-interrupts .release-btn')) return false;" \
                     " r.click(); return true; })()"
        else:
            script = ("(() => { const o = document.querySelector('#rt-overall');"
                      " return o.dataset.state === 'pass' && o.textContent.includes('smoke-task')"
                      " && document.querySelectorAll('#rt-steps .step.done').length === 4"
                      " && document.querySelector('#rt-ev-state').dataset.state === 'pass'; })()")
        self.webview.evaluateJavaScript_completionHandler_(script, self.runtimeStage_error_)
        self.rt_timer = timer

    def runtimeStage_error_(self, value, error):
        if error:
            self.exitSmoke_("运行时页脚本错误")
            return
        if not value:
            return
        self.rt_stage = getattr(self, "rt_stage", 0) + 1
        if self.rt_stage == 3:
            self.rt_timer.invalidate()
            print("GUI runtime task run, HITL release, resume-to-DONE and evidence chain OK", flush=True)
            self.verifyChat()

    @objc.python_method
    def verifyChat(self):
        self.webview.evaluateJavaScript_completionHandler_(
            """(() => {
                const wait = (ready, next) => ready() ? next() : setTimeout(() => wait(ready, next), 25);
                const setEffort = (value, done) => {
                    document.querySelector('#sidebar-settings').click();
                    document.querySelector('[data-settings=models]').click();
                    const field = document.querySelector('#effort');
                    field.value = value;
                    field.dispatchEvent(new Event('change'));
                    wait(() => library.effort === value, () => {
                        document.querySelector('#close-settings').click();
                        wait(() => !document.querySelector('#settings').open, done);
                    });
                };
                const send = text => {
                    const field = document.querySelector('#goal');
                    field.value = text;
                    field.dispatchEvent(new Event('input'));
                    wait(() => !document.querySelector('#send-chat').disabled, () =>
                        field.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true})));
                };
                wait(() => [...document.querySelector('#model').options].some(option => option.value === 'fixture'), () => {
                    setEffort('low', () => {
                        document.querySelector('#new-tab').click();
                        const model = document.querySelector('#model');
                        model.value = 'fixture';
                        model.dispatchEvent(new Event('change'));
                        send('  第一条测试消息  ');
                        wait(() => document.querySelector('#messages').textContent.includes('第一轮回复|think=True'), () => {
                            send('第二条测试消息');
                            wait(() => document.querySelector('#messages').textContent.includes('第二轮回复|think=True'), () => {
                                send('保留这条失败消息');
                                wait(() => document.querySelector('#save-state').textContent.includes('HTTP 400'), () => {
                                    if (document.querySelector('#goal').value !== '保留这条失败消息' ||
                                        document.querySelectorAll('#messages .message').length !== 4) return;
                                    setEffort('xhigh', () => {
                                        model.value = 'remote-fixture';
                                        model.dispatchEvent(new Event('change'));
                                        send('远端测试消息');
                                        wait(() => document.querySelector('#messages').textContent
                                            .includes('远端测试消息|eff=xhigh'), () => {
                                            send('身份测试');
                                            wait(() => document.querySelector('#messages').textContent
                                                .includes('sys=1'), () => {
                                                send('渲染测试');
                                                wait(() => document.querySelector('#messages').textContent.includes('行内码') &&
                                                    document.querySelector('#messages .msg-body pre code') &&
                                                    document.querySelector('#messages .msg-body strong'), () => {
                                                    wait(() => !pendingChat && !saving && unsavedReplies.size === 0, () => {
                                                        window.webkit.messageHandlers.hetu.postMessage('smokeChatReload');
                                                    });
                                                });
                                            });
                                        });
                                    });
                                });
                            });
                        });
                    });
                });
                return true;
            })()""", self.engine.delivered_error_)

    def chatReloaded_error_(self, value, error):
        if error or not value:
            self.exitSmoke_("本机会话历史未恢复")
            return
        print("GUI Enter-send, effort propagation (incl. xhigh), identity system prompt, "
              "streaming, markdown render, "
              "local+remote turns, send failure recovery and transcript reload OK", flush=True)
        self.verifyProviders()

    @objc.python_method
    def verifyProviders(self):
        self.webview.evaluateJavaScript_completionHandler_(
            """(() => {
                const wait = (ready, next) => ready() ? next() : setTimeout(() => wait(ready, next), 25);
                document.querySelector('#sidebar-settings').click();
                document.querySelector('[data-settings=models]').click();
                wait(() => document.querySelectorAll('#provider-list .provider-row').length === 2, () => {
                    const rows = [...document.querySelectorAll('#provider-list .provider-row')];
                    const buttons = row => [...row.querySelectorAll('button')];
                    buttons(rows[0]).find(b => b.textContent === '编辑').click();
                    wait(() => !document.querySelector('#provider-form').hidden
                        && document.querySelector('#provider-name').value === '本机 Ollama', () => {
                        document.querySelector('#provider-cancel').click();
                        buttons(rows[0]).find(b => b.textContent === '测试').click();
                        wait(() => document.querySelector('.provider-status[data-pid="fixture"]')
                            .textContent.includes('连接正常'), () => {
                            document.querySelector('#close-settings').click();
                            window.webkit.messageHandlers.hetu.postMessage('providersDone');
                        });
                    });
                });
                return true;
            })()""", self.engine.delivered_error_)

    @objc.python_method
    def finishProviders(self):
        print("GUI provider registry list, edit form and connection test OK", flush=True)
        self.verifyMemory()

    @objc.python_method
    def verifyMemory(self):
        self.webview.evaluateJavaScript_completionHandler_(
            """(() => {
                const wait = (ready, next) => ready() ? next() : setTimeout(() => wait(ready, next), 25);
                document.querySelector('#sidebar-settings').click();
                document.querySelector('[data-settings=memory]').click();
                wait(() => document.querySelectorAll('#mem-providers .provider-row').length === 2
                    && document.querySelector('#mem-sources .provider-row'), () => {
                    document.querySelector('#close-settings').click();
                    window.webkit.messageHandlers.hetu.postMessage('memoryDone');
                });
                return true;
            })()""", self.engine.delivered_error_)

    @objc.python_method
    def finishMemory(self):
        print("GUI memory & cloud settings panel (sources, provider switches, login hints) OK",
              flush=True)
        self.exitSmoke_(None)

    def nextSmoke_error_(self, _value, error):
        if error:
            self.exitSmoke_(error.localizedDescription())
            return
        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            0.20, self, "checkSmoke:", None, True)

    def timeout_(self, _timer):
        self.exitSmoke_("GUI 冒烟超时 (active=%r, result=%r)" %
                        (self.engine.active, self.engine.last_result))

    def exitSmoke_(self, error):
        self.smoke_dir.cleanup()
        if error:
            print("GUI-SMOKE-FAILED: %s" % error, file=sys.stderr, flush=True)
            os._exit(1)
        print("GUI-SMOKE-OK", flush=True)
        NSApplication.sharedApplication().terminate_(None)


def main():
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyRegular)
    delegate = Delegate.alloc().init()
    delegate.smoke = "--smoke" in sys.argv
    delegate.smoke_dir = tempfile.TemporaryDirectory(prefix="hetu-gui-smoke-") if delegate.smoke else None
    if delegate.smoke:
        memory_cloud.status = lambda: {
            "sources": [{"name": "personal-memory", "path": "fixture", "exists": True,
                         "file_count": 1}],
            "providers": {
                "icloud": {"enabled": False, "ready": False, "destination": "fixture"},
                "gdrive": {"enabled": False, "ready": False, "effective_mode": "auto"}},
            "log_tail": []}
    app.setDelegate_(delegate)

    rect = NSMakeRect(0, 0, 1140, 720)
    style = (NSWindowStyleMaskTitled | NSWindowStyleMaskClosable |
             NSWindowStyleMaskMiniaturizable | NSWindowStyleMaskResizable |
             NSWindowStyleMaskFullSizeContentView)
    window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(rect, style, 2, False)
    window.setTitle_("Hetu Agent")
    window.setTitleVisibility_(NSWindowTitleHidden)
    window.setTitlebarAppearsTransparent_(True)
    window.setAppearance_(NSAppearance.appearanceNamed_(NSAppearanceNameDarkAqua))
    window.setBackgroundColor_(NSColor.colorWithRed_green_blue_alpha_(0.078, 0.106, 0.188, 1))
    window.setContentMinSize_(NSMakeSize(620, 460))

    config = WKWebViewConfiguration.new()
    engine = Engine.alloc().init()
    bridge = Bridge.alloc().init()
    bridge.engine = engine
    bridge.delegate = delegate
    config.userContentController().addScriptMessageHandler_name_(bridge, "hetu")
    webview = WKWebView.alloc().initWithFrame_configuration_(rect, config)
    engine.configure_data_(webview, Path(delegate.smoke_dir.name) if delegate.smoke else DATA)
    engine.providers_path = (engine.data / "Providers.json" if delegate.smoke
                             else engine.data.parent / "Providers.json")
    engine.load_providers()
    if delegate.smoke:
        from smoke_model import smoke_server
        server = smoke_server()
        engine.provider_cfg = {"version": model_providers.VERSION, "default": None,
                               "providers": [
            {"id": "fixture", "name": "本机 Ollama", "kind": "ollama",
             "base_url": "http://127.0.0.1:%d" % server.server_port,
             "api_key": "", "enabled": True},
            {"id": "fixture-remote", "name": "远程 OpenAI 兼容", "kind": "openai",
             "base_url": "http://127.0.0.1:%d/v1" % server.server_port,
             "api_key": "", "enabled": True},
        ]}
        engine.rebuild_provider_clients()
    bridge.library_path = engine.data.parent / "Workspace.json" if not delegate.smoke else engine.data / "Workspace.json"
    delegate.library_path = bridge.library_path
    delegate.engine = engine
    delegate.webview = webview
    webview.setNavigationDelegate_(delegate)
    html = (RES / "gui.html").read_text(encoding="utf-8").replace("__VERSION__", VERSION)
    port = (RES / "hasu_port" / "desktop.js").read_text(encoding="utf-8")
    html = html.replace("__DESKTOP_PORT__", port)
    bridge.smoke_html = html if delegate.smoke else None
    webview.loadHTMLString_baseURL_(html, None)

    window.setContentView_(webview)
    window.center()
    window.makeKeyAndOrderFront_(None)
    NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
        0.08, engine, "tick:", None, True)
    if delegate.smoke:
        # 预算须覆盖最慢序列: 页面导航 + selfcheck + 全量测试(打包内 ~45s) + m2 + isolation
        # + 运行时/记忆面板验证。测试套件增长后 45s 会在 m2 处截断, 放宽到 240s 兜底。
        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            240, delegate, "timeout:", None, False)
    app.run()


if __name__ == "__main__":
    main()
