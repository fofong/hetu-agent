"""Hetu 最小 CLI（L4 接口层占位）：内核自检。UI/通道永不触执行逻辑。"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile

from . import __version__
from .evidence.chain import EvidenceChain
from .kernel.effect_ledger import CONFIRMED, INTENT, EffectLedger
from .sched.scheduler import DurableScheduler


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="hetu", description="Hetu Agent kernel (clean-room)")
    ap.add_argument("command", choices=["status"], help="status = kernel self-check")
    ap.add_argument("--db", default=None, help="SQLite path (default: ephemeral self-check db)")
    args = ap.parse_args(argv)

    if args.command == "status":
        db = args.db or os.path.join(tempfile.mkdtemp(prefix="hetu-status-"), "hetu.db")
        chain = EvidenceChain(db)
        led = EffectLedger(db, chain=chain)
        sched = DurableScheduler(db)
        # 冒烟: 三态提交 + 幂等槽 + 证据链完整性
        led.intent("selfcheck", {}, "sc-1")
        tok = led.acquire("sc-1", "cli")
        led.execute("sc-1", "cli", tok, lambda: "ok")
        sched.add_job("selfcheck", 60)
        sched.fire("selfcheck", 0.0)
        dup = sched.fire("selfcheck", 0.0)
        ok_chain, _ = chain.verify()
        report = {
            "version": __version__,
            "effect_ledger": led.state("sc-1") == CONFIRMED,
            "intent_state": led.state("sc-1"),
            "idempotent_slot": dup == "duplicate",
            "evidence_chain_valid": ok_chain,
            "third_party_deps": 0,
        }
        print("hetu %s self-check:" % __version__)
        for k, v in report.items():
            print("  %-20s %s" % (k, v))
        good = all(v for k, v in report.items() if k not in ("version", "intent_state",
                                                             "third_party_deps"))
        print("verdict:", "OK" if good else "FAILED")
        return 0 if good else 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
