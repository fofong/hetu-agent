"""Hetu Agent 人工测试 GUI (Tkinter, stdlib only).

供人工测试: 内核自检 / 全量测试套件 / M2 自基线, 输出实时回显。
--smoke: 构建界面后立即销毁, 打印 GUI-SMOKE-OK (打包验证用)。
"""
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import scrolledtext

RES = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(RES, "src")
PY = sys.executable

JOBS = [
    ("内核自检", [PY, "-m", "hetu", "status"]),
    ("全量测试套件", [PY, "-m", "unittest", "discover",
                      "-s", os.path.join(SRC, "tests"), "-v"]),
    ("M2 自基线 (5 场景×5 重复)", [PY, os.path.join(SRC, "scripts", "m2_harness.py")]),
]


class App:
    def __init__(self, root):
        self.root = root
        root.title("Hetu Agent")
        root.geometry("760x480")
        top = tk.Frame(root, padx=10, pady=8)
        top.pack(fill="x")
        tk.Label(top, text="Hetu Agent", font=("Helvetica", 16, "bold")).pack(side="left")
        try:
            sys.path.insert(0, SRC)
            from hetu import __version__
        except Exception:
            __version__ = "?"
        tk.Label(top, text="v%s · 因果执行内核 · 零第三方依赖" % __version__,
                 fg="gray").pack(side="left", padx=12)
        bar = tk.Frame(root, padx=10)
        bar.pack(fill="x")
        self.buttons = []
        for label, cmd in JOBS:
            b = tk.Button(bar, text=label, command=lambda c=cmd: self.run(c))
            b.pack(side="left", padx=4, pady=4)
            self.buttons.append(b)
        self.out = scrolledtext.ScrolledText(root, font=("Menlo", 11), state="disabled")
        self.out.pack(fill="both", expand=True, padx=10, pady=8)
        self.q = queue.Queue()
        root.after(100, self.drain)
        root.after(300, lambda: self.run(JOBS[0][1]))  # 启动即自动运行自检

    def log(self, s):
        self.out.configure(state="normal")
        self.out.insert("end", s)
        self.out.see("end")
        self.out.configure(state="disabled")

    def drain(self):
        try:
            while True:
                item = self.q.get_nowait()
                if item is None:
                    for b in self.buttons:
                        b.configure(state="normal")
                else:
                    self.log(item)
        except queue.Empty:
            pass
        self.root.after(100, self.drain)

    def run(self, cmd):
        for b in self.buttons:
            b.configure(state="disabled")
        self.log("\n$ %s\n" % " ".join(cmd))

        def worker():
            try:
                p = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, text=True)
                assert p.stdout is not None
                for line in p.stdout:
                    self.q.put(line)
                self.q.put("[exit %d] %s\n" % (p.wait(),
                             "PASS" if p.returncode == 0 else "FAILED"))
            except Exception as e:
                self.q.put("error: %s\n" % e)
            self.q.put(None)

        threading.Thread(target=worker, daemon=True).start()


def main():
    root = tk.Tk()
    app = App(root)
    if "--smoke" in sys.argv:
        root.update_idletasks()
        root.update()
        try:
            root.destroy()
        except tk.TclError:
            pass  # Tk 在某些无头场景会先行销毁, 不影响冒烟结论
        print("GUI-SMOKE-OK")
        return
    root.mainloop()


if __name__ == "__main__":
    main()
