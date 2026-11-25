"""记忆与云同步桥接：调用外部 memorax-cloud-sync CLI，供设置页使用。

UI 边界：本模块只做子进程调用与结果解析，不实现任何同步逻辑；
真正的同步器在仓库之外（~/.memorax-code/cloud-sync/），凭据与登录
完全由用户掌控，两个云端开关默认关闭。失败一律返回 {"error": ...}。
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

PROVIDERS = ("icloud", "gdrive")
ENV_CLI = "HETU_MEMORAX_SYNC"
TIMEOUT_STATUS = 30
TIMEOUT_SYNC = 180


def cli_path():
    """定位 memorax-cloud-sync CLI：环境变量优先，其次 PATH 与 ~/.local/bin。"""
    env = os.environ.get(ENV_CLI, "").strip()
    if env:
        candidate = Path(os.path.expanduser(env))
        return candidate if candidate.is_file() else None
    found = shutil.which("memorax-cloud-sync")
    if found:
        return Path(found)
    fallback = Path.home() / ".local" / "bin" / "memorax-cloud-sync"
    return fallback if fallback.is_file() else None


def _run(args, timeout):
    cli = cli_path()
    if cli is None:
        return {"error": "记忆同步工具未安装（memorax-cloud-sync）"}
    try:
        return subprocess.run([str(cli), *args], capture_output=True,
                              text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"error": "记忆同步命令超时"}
    except OSError as error:
        return {"error": "无法执行记忆同步命令：%s" % error}


def status():
    """读取记忆源与云端开关状态（单 JSON 对象）。"""
    proc = _run(["status", "--json"], TIMEOUT_STATUS)
    if isinstance(proc, dict):
        return proc
    try:
        data = json.loads(proc.stdout)
    except (ValueError, TypeError):
        detail = (proc.stdout or proc.stderr or "").strip()[:200]
        return {"error": "记忆同步输出无法解析：%s" % detail}
    if proc.returncode != 0:
        data.setdefault("error", "记忆同步命令异常退出（rc=%s）" % proc.returncode)
    return data


def set_enabled(provider, enable):
    """按用户点击开/关某个云端；返回最新 status。"""
    if provider not in PROVIDERS:
        return {"error": "未知云端"}
    if not isinstance(enable, bool):
        return {"error": "开关状态必须是布尔值"}
    proc = _run(["enable" if enable else "disable", provider], TIMEOUT_STATUS)
    if isinstance(proc, dict):
        return proc
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()[:200]
        return {"error": "开关切换失败：%s" % detail}
    return status()


def sync(provider=None):
    """单次同步（幂等、只追加）；provider 为 None 时同步所有已开启的云端。"""
    args = ["sync"]
    if provider is not None:
        if provider not in PROVIDERS:
            return {"error": "未知云端"}
        args += ["--provider", provider]
    proc = _run(args, TIMEOUT_SYNC)
    if isinstance(proc, dict):
        return proc
    tail = [line for line in (proc.stdout or "").splitlines() if line.strip()][-8:]
    if proc.returncode != 0:
        return {"error": "同步失败：%s" % ("；".join(tail) or "rc=%s" % proc.returncode),
                "output": tail}
    return {"ok": True, "output": tail}
