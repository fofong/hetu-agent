"""Phase 2 · 一体化任务运行时: 把 L0/L1/L2 机制组装成可恢复任务执行器。

一个任务 = plan-hash 恢复点 + 逐步 step_writes(经 Effect Ledger 提交) + heartbeat。
崩溃重放零重复; 计划漂移转人工; 高风险步骤 PAUSED 转人工; 回执丢失走对账。
"""
from __future__ import annotations

import json
import warnings
from typing import Any, Callable, Optional

from .evidence.chain import EvidenceChain
from .kernel.effect_ledger import (
    CONFIRMED, EXECUTING, INTENT, PAUSED, UNCERTAIN, EffectLedger,
)
from .kernel.heartbeat import Heartbeat
from .kernel.hitl import RELEASED, Interrupts
from .kernel.recovery import PlanDrift, RecoveryPoints
from .kernel.step_writes import StepWrites
from .security.policy import DENY, REQUIRE_APPROVAL, ActionPolicy

DONE = "DONE"
PAUSED_WAIT = "PAUSED"      # 等人工放行
ESCALATED = "ESCALATED"     # 计划漂移等异常转人工


class Step:
    def __init__(self, step_id: str, action: str, effect: Callable[[], Any],
                 payload: Any = None, risk: str = "normal", reversible: bool = False):
        self.step_id = step_id
        self.action = action
        self.effect = effect
        self.payload = payload or {}
        self.risk = risk
        self.reversible = reversible  # False(默认): 不可逆外部副作用, ledger 故障时禁降级


class StepPaused(Exception):
    pass


class StepDenied(Exception):
    """安全策略 DENY: 动作被结构性拒绝, 效果函数绝不执行。"""


class StepUncertain(Exception):
    pass


class TaskRunner:
    def __init__(self, db_path: str, probes: Optional[dict] = None,
                 lease_ttl: float = 30.0, policy: Optional[ActionPolicy] = None):
        self.db_path = db_path
        self.lease_ttl = lease_ttl
        self.policy = policy  # None = 不启用策略门(向后兼容); 启用即 fail-closed
        if policy is None:
            warnings.warn(
                "TaskRunner 未启用 ActionPolicy: 策略门关闭(0.3.x 为 opt-in)。"
                "生产接入请传 ActionPolicy(db) 以获得 fail-closed 门禁。",
                stacklevel=2)
        self.chain = EvidenceChain(db_path)
        self.ledger = EffectLedger(db_path, chain=self.chain)
        self.steps = StepWrites(db_path)
        self.recovery = RecoveryPoints(db_path)
        self.hitl = Interrupts(db_path)
        self.beat = Heartbeat(db_path)
        self.probes = probes or {}  # action -> 独立探针(回执丢失/孤儿对账用)

    def _guarded(self, task_id: str, step: Step) -> Any:
        """返回必须是可持久化结果; 一切未完成态用异常表达(不写 step 行, 重放不卡死)。"""
        idem = "%s:%s" % (task_id, step.step_id)
        state = self.ledger.state(idem)
        if state == CONFIRMED:  # 崩溃重放: 外部已确认, 零重复; 读回原回执而非标记
            raw = self.ledger.receipt(idem)
            if raw is not None:
                return json.loads(raw)
            return "replayed-from-ledger"  # 无回执的旧数据兜底
        if state in (UNCERTAIN, EXECUTING):
            # 回执丢失或孤儿(执行者疑似死亡): 一律先对账, 禁盲重放/盲接管
            probe = self.probes.get(step.action)
            if probe is None:
                raise StepUncertain("no probe for %s" % step.action)
            state = self.ledger.reconcile(idem, probe)
            if state == CONFIRMED:
                return "reconciled-from-ledger"
            if state != INTENT:
                raise StepUncertain(idem)
            # 探针确认外部未发生 -> 受控重放, 继续向下执行
        # 安全策略门(嵌入): DENY 直接拒绝且效果绝不执行; REQUIRE_APPROVAL
        # 并入既有 high-risk HITL 通道, 复用 PAUSED/放行全链路。
        risk = step.risk
        if self.policy is not None:
            decision = self.policy.decide(step.action, target=step.step_id,
                                          risk=step.risk)
            if decision.state == DENY:
                raise StepDenied("%s: %s" % (step.step_id, decision.reason))
            if decision.state == REQUIRE_APPROVAL:
                risk = "high"
        self.ledger.intent(step.action, step.payload, idem, risk=risk,
                           reversible=step.reversible)
        if self.ledger.state(idem) == PAUSED:  # 高风险: 转人工
            iid = self.hitl.raise_interrupt(task_id, "high-risk-step",
                                            {"step_id": step.step_id, "action": step.action})
            if self.hitl.state(iid) != RELEASED:
                raise StepPaused(idem)
            self.ledger.release_high_risk(idem)
        tok = self.ledger.acquire(idem, "runner", lease_ttl=self.lease_ttl)
        result = self.ledger.execute(idem, "runner", tok, step.effect)
        if result == UNCERTAIN:
            raise StepUncertain(idem)
        raw = self.ledger.receipt(idem)  # 业务结果以回执为准(状态常量仅是内核信号)
        if raw is not None:
            return json.loads(raw)
        return result

    def run_task(self, task_id: str, plan: list, steps: list,
                 crash_at_step: Optional[str] = None) -> dict:
        """执行任务。crash_at_step: 故障注入(该步外部效果完成后、checkpoint 前崩溃)。"""
        try:
            self.recovery.resume(task_id, plan)
        except KeyError:
            self.recovery.save(task_id, plan, {"cursor": 0})
        except PlanDrift:
            self.hitl.raise_interrupt(task_id, "plan-drift", {"plan": plan})
            self.chain.append("runtime", "task.escalated", {"task_id": task_id,
                                                            "reason": "plan-drift"})
            return {"status": ESCALATED, "results": {}}

        results: dict = {}
        for i, step in enumerate(steps):
            crash = (step.step_id == crash_at_step)
            try:
                out = self.steps.run(task_id, step.step_id,
                                     lambda s=step: self._guarded(task_id, s),
                                     crash_after_effect_before_write=crash)
            except StepPaused:
                self.beat.beat(task_id, {"cursor": i})
                self.chain.append("runtime", "task.paused", {"task_id": task_id,
                                                             "step": step.step_id})
                return {"status": PAUSED_WAIT, "results": results}
            except StepDenied as e:
                self.beat.beat(task_id, {"cursor": i})
                self.chain.append("runtime", "task.denied", {"task_id": task_id,
                                                             "step": step.step_id,
                                                             "reason": str(e)})
                return {"status": ESCALATED, "results": results, "at": step.step_id}
            except StepUncertain:
                self.beat.beat(task_id, {"cursor": i})
                self.chain.append("runtime", "task.uncertain", {"task_id": task_id,
                                                                "step": step.step_id})
                return {"status": "RECONCILE", "results": results}
            except Exception as e:  # 崩溃注入或不可对账: 断点已保留, 重跑续算
                self.beat.beat(task_id, {"cursor": i})
                self.chain.append("runtime", "task.interrupted",
                                  {"task_id": task_id, "step": step.step_id, "err": str(e)})
                return {"status": "INTERRUPTED", "results": results, "at": step.step_id}
            results[step.step_id] = out
            self.beat.beat(task_id, {"cursor": i + 1})
        self.chain.append("runtime", "task.done", {"task_id": task_id})
        return {"status": DONE, "results": results}


def run_due(sched, jobs: dict, owner: str = "worker-1", now: Optional[float] = None) -> int:
    """L2 集成: 认领并执行全部 PENDING/FAILED 槽。jobs: job_id -> callable。"""
    import time as _t
    now = now if now is not None else _t.time()
    n = 0
    for slot in sched.pending_slots():
        fn = jobs.get(slot["job_id"])
        if fn is None:
            continue
        sched.run_slot(slot["job_id"], slot["scheduled_instant"],
                       slot["trigger_type"], owner, fn)
        n += 1
    return n
