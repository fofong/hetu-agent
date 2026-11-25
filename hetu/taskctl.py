"""运行时 CLI: 把 TaskRunner / HITL / 证据链 / 调度器暴露为单条 JSON 命令。

桌面界面经子进程调用本模块(UI 永不 import 执行逻辑, 与 JOBS 同一边界):
    python -m hetu.taskctl --db PATH <command> [...]
每条命令 stdout 输出恰好一个 JSON 对象; 失败时 {"error": ...} 且退出码非 0。

demo 模板的效果是真实但可逆的本地文件写入(工作区默认 <db 目录>/task-workspace),
探针与效果独立核验, 与生产步骤同一 ledger 路径 —— 界面演示的即内核真实保证。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Callable

from .evidence.chain import EvidenceChain
from .kernel.effect_ledger import EffectLedger
from .kernel.hitl import Interrupts
from .runtime import TaskRunner, Step
from .sched.scheduler import DurableScheduler

TEMPLATES: dict[str, list[dict]] = {
    "demo": [
        {"step_id": "s1", "action": "prepare", "risk": "normal", "reversible": True,
         "label": "准备工作区"},
        {"step_id": "s2", "action": "note-append", "risk": "normal", "reversible": True,
         "label": "追加运行记录"},
        {"step_id": "s3", "action": "publish", "risk": "high", "reversible": False,
         "label": "发布成果(高风险, 需人工放行)"},
        {"step_id": "s4", "action": "finalize", "risk": "normal", "reversible": True,
         "label": "收尾归档"},
    ]
}


def _workspace(db_path: str, override: str | None) -> Path:
    root = Path(override) if override else Path(db_path).parent / "task-workspace"
    return root


def _demo_steps(task_id: str, workspace: Path):
    """返回 (plan, steps)。效果写真实文件; 探针独立读文件核验。"""
    task_dir = workspace / task_id
    notes = task_dir / "notes.txt"
    publish = task_dir / "PUBLISH.txt"
    done = task_dir / "DONE.txt"

    def exists(path: Path) -> Callable[[], Any]:
        return lambda: path.exists()

    def prepare() -> str:
        task_dir.mkdir(parents=True, exist_ok=True)
        notes.write_text("prepared %s\n" % task_id, encoding="utf-8")
        return str(notes)

    def note_append() -> int:
        with notes.open("a", encoding="utf-8") as f:
            f.write("run %.6f\n" % time.time())
        return len(notes.read_text(encoding="utf-8").splitlines())

    def publish_effect() -> str:
        task_dir.mkdir(parents=True, exist_ok=True)
        publish.write_text("PUBLISHED %.6f\n" % time.time(), encoding="utf-8")
        return str(publish)

    def finalize() -> str:
        done.write_text("DONE %.6f\n" % time.time(), encoding="utf-8")
        return str(done)

    effects = {"prepare": prepare, "note-append": note_append,
               "publish": publish_effect, "finalize": finalize}
    probes = {"prepare": exists(notes), "note-append": exists(notes),
              "publish": exists(publish), "finalize": exists(done)}
    spec = TEMPLATES["demo"]
    plan = [{"step_id": s["step_id"], "action": s["action"], "risk": s["risk"]} for s in spec]
    steps = [Step(s["step_id"], s["action"], effects[s["action"]],
                 payload={"task": task_id, "step": s["step_id"]},
                 risk=s["risk"], reversible=s["reversible"]) for s in spec]
    return plan, steps, probes


def _emit(value: dict) -> int:
    print(json.dumps(value, ensure_ascii=False, default=str))
    return 1 if "error" in value else 0


def model_efforts() -> tuple:
    from .model import EFFORTS
    return EFFORTS


# ---------------- commands ----------------

def cmd_run(args) -> int:
    plan, steps, probes = _demo_steps(args.task, _workspace(args.db, args.workspace))
    runner = TaskRunner(args.db, probes=probes)
    out = runner.run_task(args.task, plan, steps)
    out["template"] = args.template
    return _emit(out)


def _ensure_tables(db: str) -> None:
    """幂等建齐全部内核表(空库 status/tasks/evidence 不报无表)。"""
    EffectLedger(db)
    Interrupts(db)
    EvidenceChain(db)
    from .kernel.heartbeat import Heartbeat
    from .kernel.recovery import RecoveryPoints
    from .kernel.step_writes import StepWrites
    Heartbeat(db)
    RecoveryPoints(db)
    StepWrites(db)


def _overall(db: str, task_id: str, steps_spec: list, ledger: EffectLedger) -> dict:
    from .db import connect
    con = connect(db)
    try:
        rp = con.execute("SELECT state FROM recovery_points WHERE task_id=?",
                         (task_id,)).fetchone()
        hb = con.execute("SELECT last_beat, checkpoint FROM heartbeats WHERE task_id=?",
                         (task_id,)).fetchone()
        writes = {r["step_id"]: dict(r) for r in con.execute(
            "SELECT * FROM step_writes WHERE task_id=?", (task_id,)).fetchall()}
        chain_rows = con.execute(
            "SELECT event, detail FROM evidence_chain WHERE event LIKE 'task.%' ORDER BY seq"
        ).fetchall()
    finally:
        con.close()
    cursor = None
    if rp:
        try:
            cursor = json.loads(rp["state"]).get("cursor")
        except ValueError:
            pass
    if hb:  # 运行期游标以 heartbeat checkpoint 为准(recovery 行只在启动时落一次)
        try:
            hb_cursor = json.loads(hb["checkpoint"]).get("cursor")
            if hb_cursor is not None:
                cursor = hb_cursor
        except ValueError:
            pass
    latest = None
    for r in reversed(chain_rows):
        try:
            detail = json.loads(r["detail"])
        except ValueError:
            continue
        if detail.get("task_id") == task_id:
            latest = r["event"]
            break
    steps = []
    for spec in steps_spec:
        idem = "%s:%s" % (task_id, spec["step_id"])
        steps.append({
            "step_id": spec["step_id"], "action": spec["action"], "risk": spec["risk"],
            "label": spec["label"], "ledger": ledger.state(idem),
            "written": spec["step_id"] in writes,
            "result_hash": (writes.get(spec["step_id"]) or {}).get("result_hash", ""),
        })
    if all(s["written"] for s in steps):
        overall = "DONE"
    elif any(s["ledger"] == "PAUSED" for s in steps):
        overall = "PAUSED"
    elif any(s["ledger"] in ("UNCERTAIN", "EXECUTING") for s in steps):
        overall = "RECONCILE"
    elif latest == "task.escalated":
        overall = "ESCALATED"
    elif latest == "task.interrupted":
        overall = "INTERRUPTED"
    elif latest == "task.done":
        overall = "DONE"
    elif latest is None:
        overall = "NEW"
    else:
        overall = "PARTIAL"
    return {"task_id": task_id, "overall": overall, "cursor": cursor,
            "heartbeat_ts": hb["last_beat"] if hb else None,
            "latest_event": latest, "steps": steps}


def cmd_status(args) -> int:
    _ensure_tables(args.db)
    ledger = EffectLedger(args.db)
    return _emit(_overall(args.db, args.task, TEMPLATES["demo"], ledger))


def cmd_tasks(args) -> int:
    _ensure_tables(args.db)
    from .db import connect
    con = connect(args.db)
    try:
        rows = con.execute(
            "SELECT r.task_id, r.state, h.last_beat, h.checkpoint FROM recovery_points r "
            "LEFT JOIN heartbeats h ON h.task_id = r.task_id ORDER BY h.last_beat DESC"
        ).fetchall()
    finally:
        con.close()
    tasks = []
    for r in rows:
        cursor = None
        for source in (r["checkpoint"], r["state"]):
            try:
                value = json.loads(source).get("cursor")
                if value is not None:
                    cursor = value
                    break
            except (ValueError, TypeError):
                continue
        tasks.append({"task_id": r["task_id"], "cursor": cursor,
                      "heartbeat_ts": r["last_beat"],
                      "summary": _overall(args.db, r["task_id"], TEMPLATES["demo"],
                                          EffectLedger(args.db))["overall"]})
    return _emit({"tasks": tasks})


def cmd_interrupts(args) -> int:
    _ensure_tables(args.db)
    hitl = Interrupts(args.db)
    from .db import connect
    con = connect(args.db)
    try:
        rows = [dict(r) for r in con.execute(
            "SELECT * FROM interrupts ORDER BY created_ts DESC LIMIT 50").fetchall()]
    finally:
        con.close()
    for r in rows:
        try:
            r["payload"] = json.loads(r["payload"])
        except ValueError:
            pass
    return _emit({"pending": hitl.pending(), "recent": rows})


def cmd_release(args) -> int:
    hitl = Interrupts(args.db)
    from .db import connect
    con = connect(args.db)
    try:
        row = con.execute("SELECT * FROM interrupts WHERE interrupt_id=?",
                          (args.interrupt,)).fetchone()
    finally:
        con.close()
    if row is None:
        return _emit({"error": "interrupt 不存在: %s" % args.interrupt})
    approve = not args.reject
    hitl.release(args.interrupt, resolver="desktop", approve=approve)
    released_idem = None
    if approve and row["kind"] == "high-risk-step":
        try:
            payload = json.loads(row["payload"])
            idem = "%s:%s" % (row["task_id"], payload["step_id"])
            EffectLedger(args.db).release_high_risk(idem)
            released_idem = idem
        except (ValueError, KeyError):
            pass
    return _emit({"ok": True, "state": hitl.state(args.interrupt),
                  "released_idem": released_idem})


def cmd_evidence(args) -> int:
    _ensure_tables(args.db)
    chain = EvidenceChain(args.db)
    ok, bad_seq = chain.verify()
    entries = chain.entries()
    tail = entries[-args.last:] if args.last else entries
    return _emit({"verified": ok, "broken_at": bad_seq, "total": len(entries),
                  "entries": tail})


def cmd_model_status(args) -> int:
    from hetu import model
    return _emit(model.status())


def cmd_model_ask(args) -> int:
    from hetu import model
    try:
        client = model.ModelClient()
        text = client.reply([{"role": "user", "content": args.prompt}],
                            effort=model.normalize_effort(args.effort))
    except model.ModelError as error:
        return _emit({"error": str(error)})
    return _emit({"ok": True, "model": model.config()["model"],
                  "effort": model.normalize_effort(args.effort), "reply": text})


def cmd_jobs(args) -> int:
    from .db import connect
    con = connect(args.db)
    try:
        jobs = [dict(r) for r in con.execute("SELECT * FROM jobs ORDER BY job_id").fetchall()]
        slots = [dict(r) for r in con.execute(
            "SELECT * FROM job_slots ORDER BY scheduled_instant DESC LIMIT 30").fetchall()]
        missed = con.execute("SELECT COUNT(*) AS n FROM missed_ledger").fetchone()["n"]
        unacked = con.execute("SELECT COUNT(*) AS n FROM deliveries WHERE acked=0").fetchone()["n"]
    except Exception as e:  # 表尚未建立 = 调度器从未初始化, 空态而非错误
        con.close()
        return _emit({"jobs": [], "slots": [], "missed": 0, "unacked": 0, "note": str(e)})
    finally:
        if con:
            con.close()
    return _emit({"jobs": jobs, "slots": slots, "missed": missed, "unacked": unacked})


def cmd_add_job(args) -> int:
    sched = DurableScheduler(args.db)
    sched.add_job(args.job, args.interval, args.policy)
    return _emit({"ok": True, "job_id": args.job, "interval_sec": args.interval,
                  "policy": args.policy})


def cmd_fire(args) -> int:
    sched = DurableScheduler(args.db)
    result = sched.fire(args.job, time.time(), trigger_type="manual")
    return _emit({"ok": True, "job_id": args.job, "fire": result})


def cmd_run_due(args) -> int:
    from .runtime import run_due
    sched = DurableScheduler(args.db)
    workspace = _workspace(args.db, args.workspace)

    def demo_job():
        workspace.mkdir(parents=True, exist_ok=True)
        with (workspace / "scheduler.log").open("a", encoding="utf-8") as f:
            f.write("tick %.6f\n" % time.time())

    jobs = {}
    from .db import connect
    con = connect(args.db)
    try:
        for r in con.execute("SELECT job_id FROM jobs").fetchall():
            jobs[r["job_id"]] = demo_job
    finally:
        con.close()
    n = run_due(sched, jobs)
    return _emit({"ok": True, "executed": n})


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="hetu.taskctl", description="Hetu 运行时 JSON CLI")
    ap.add_argument("--db", required=True)
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("run"); p.add_argument("--task", required=True)
    p.add_argument("--template", default="demo", choices=sorted(TEMPLATES))
    p.add_argument("--workspace"); p.set_defaults(func=cmd_run)

    p = sub.add_parser("status"); p.add_argument("--task", required=True)
    p.set_defaults(func=cmd_status)

    sub.add_parser("tasks").set_defaults(func=cmd_tasks)
    sub.add_parser("interrupts").set_defaults(func=cmd_interrupts)

    p = sub.add_parser("release"); p.add_argument("--interrupt", required=True)
    p.add_argument("--reject", action="store_true"); p.set_defaults(func=cmd_release)

    p = sub.add_parser("evidence"); p.add_argument("--last", type=int, default=50)
    p.set_defaults(func=cmd_evidence)

    sub.add_parser("model-status").set_defaults(func=cmd_model_status)

    p = sub.add_parser("model-ask"); p.add_argument("--prompt", required=True)
    p.add_argument("--effort", default="auto", choices=sorted(model_efforts()))
    p.set_defaults(func=cmd_model_ask)

    sub.add_parser("jobs").set_defaults(func=cmd_jobs)

    p = sub.add_parser("add-job"); p.add_argument("--job", required=True)
    p.add_argument("--interval", type=float, required=True)
    p.add_argument("--policy", default="coalesce",
                   choices=["coalesce", "per-run", "skip+alert"])
    p.set_defaults(func=cmd_add_job)

    p = sub.add_parser("fire"); p.add_argument("--job", required=True)
    p.set_defaults(func=cmd_fire)

    p = sub.add_parser("run-due"); p.add_argument("--workspace")
    p.set_defaults(func=cmd_run_due)

    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except Exception as e:  # 单 JSON 契约: 异常也走 stdout JSON, 由退出码区分
        return _emit({"error": "%s: %s" % (type(e).__name__, e)})


if __name__ == "__main__":
    sys.exit(main())
