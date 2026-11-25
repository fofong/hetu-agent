"""taskctl 运行时 CLI 端到端: 运行→PAUSED→放行→续跑→DONE + 证据链 + 调度器。"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1]


def taskctl(db, *argv):
    out = subprocess.run([sys.executable, "-m", "hetu.taskctl", "--db", str(db), *argv],
                         cwd=SRC, capture_output=True, text=True, timeout=60)
    payload = json.loads(out.stdout)
    return out.returncode, payload


class TaskctlTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="hetu-taskctl-")
        self.db = Path(self.tmp.name) / "hetu.db"
        self.addCleanup(self.tmp.cleanup)

    def test_full_runtime_loop(self):
        rc, run1 = taskctl(self.db, "run", "--task", "gui-demo")
        self.assertEqual(rc, 0, run1)
        self.assertEqual(run1["status"], "PAUSED")  # s3 高风险转人工
        self.assertIn("s1", run1["results"])
        self.assertIn("s2", run1["results"])

        rc, st = taskctl(self.db, "status", "--task", "gui-demo")
        self.assertEqual(rc, 0)
        self.assertEqual(st["overall"], "PAUSED")
        self.assertEqual(st["cursor"], 2)
        self.assertTrue(st["steps"][0]["written"])
        self.assertEqual(st["steps"][2]["ledger"], "PAUSED")

        rc, ints = taskctl(self.db, "interrupts")
        self.assertEqual(rc, 0)
        self.assertEqual(len(ints["pending"]), 1)
        iid = ints["pending"][0]["interrupt_id"]

        rc, rel = taskctl(self.db, "release", "--interrupt", iid)
        self.assertEqual(rc, 0)
        self.assertEqual(rel["state"], "RELEASED")
        self.assertEqual(rel["released_idem"], "gui-demo:s3")

        rc, run2 = taskctl(self.db, "run", "--task", "gui-demo")
        self.assertEqual(rc, 0)
        self.assertEqual(run2["status"], "DONE")

        rc, st = taskctl(self.db, "status", "--task", "gui-demo")
        self.assertEqual(st["overall"], "DONE")
        self.assertTrue(all(s["written"] for s in st["steps"]))

        # 效果真实落盘且零重复(s2 只追加了一次)
        notes = Path(self.tmp.name) / "task-workspace" / "gui-demo" / "notes.txt"
        self.assertEqual(len(notes.read_text().splitlines()), 2)

        rc, ev = taskctl(self.db, "evidence")
        self.assertEqual(rc, 0)
        self.assertTrue(ev["verified"])
        self.assertGreater(ev["total"], 5)
        events = {e["event"] for e in ev["entries"]}
        self.assertIn("task.done", events)

        rc, tasks = taskctl(self.db, "tasks")
        self.assertEqual(rc, 0)
        self.assertEqual(tasks["tasks"][0]["task_id"], "gui-demo")
        self.assertEqual(tasks["tasks"][0]["summary"], "DONE")

    def test_reject_keeps_paused(self):
        taskctl(self.db, "run", "--task", "t-rej")
        _, ints = taskctl(self.db, "interrupts")
        iid = ints["pending"][0]["interrupt_id"]
        rc, rel = taskctl(self.db, "release", "--interrupt", iid, "--reject")
        self.assertEqual(rel["state"], "REJECTED")
        rc, run2 = taskctl(self.db, "run", "--task", "t-rej")
        self.assertEqual(run2["status"], "PAUSED")  # 驳回后仍挂起, 新 interrupt
        _, ints2 = taskctl(self.db, "interrupts")
        self.assertEqual(len(ints2["pending"]), 1)

    def test_scheduler_flow(self):
        rc, add = taskctl(self.db, "add-job", "--job", "demo-note", "--interval", "60")
        self.assertEqual(rc, 0)
        rc, fire = taskctl(self.db, "fire", "--job", "demo-note")
        self.assertEqual(rc, 0)
        self.assertEqual(fire["fire"], "created")
        rc, dup = taskctl(self.db, "fire", "--job", "demo-note")
        # 同一秒重复投递: 幂等槽拒绝或创建不同 instant, 二者皆合法
        self.assertIn(dup["fire"], ("created", "duplicate"))
        rc, due = taskctl(self.db, "run-due")
        self.assertEqual(rc, 0)
        self.assertGreaterEqual(due["executed"], 1)
        rc, jobs = taskctl(self.db, "jobs")
        self.assertEqual(rc, 0)
        self.assertEqual(jobs["jobs"][0]["job_id"], "demo-note")
        self.assertTrue(any(s["state"] == "DONE" for s in jobs["slots"]))
        log = Path(self.tmp.name) / "task-workspace" / "scheduler.log"
        self.assertTrue(log.exists())

    def test_bad_command_is_json_error(self):
        rc, payload = taskctl(self.db, "status", "--task", "nonexistent")
        self.assertEqual(rc, 0)  # 未知任务不是错误: NEW 空态
        self.assertEqual(payload["overall"], "NEW")
        bad = subprocess.run([sys.executable, "-m", "hetu.taskctl", "--db", str(self.db),
                              "release", "--interrupt", "missing"],
                             cwd=SRC, capture_output=True, text=True, timeout=60)
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("error", json.loads(bad.stdout))

    def test_model_ask_effort_choices(self):
        bad = subprocess.run([sys.executable, "-m", "hetu.taskctl", "--db", str(self.db),
                              "model-ask", "--prompt", "x", "--effort", "bogus"],
                             cwd=SRC, capture_output=True, text=True, timeout=60)
        self.assertEqual(bad.returncode, 2)  # argparse 拒绝未知思考程度
        self.assertIn("--effort", bad.stderr)
        from hetu import taskctl
        self.assertEqual(set(taskctl.model_efforts()),
                         {"auto", "off", "minimal", "low", "medium", "high", "xhigh", "max"})


if __name__ == "__main__":
    unittest.main()
