"""L1 · 独立探针: 自报绿≠实际绿。LLM/执行体自评只能作触发器, 结论必须过独立探针。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional


@dataclass
class ProbeResult:
    ok: bool
    observed: Any
    reason: str = ""


class IndependentProbe:
    """探针 = 与自评通道完全分离的第三方核验函数(查外部真实状态)。"""

    def __init__(self, sensor: Callable[[], Any]):
        self.sensor = sensor

    def check(self, expect: Callable[[Any], bool]) -> ProbeResult:
        observed = self.sensor()
        ok = expect(observed)
        return ProbeResult(ok=ok, observed=observed,
                           reason="independent probe" if ok else "self-report contradicted by probe")


def verdict(self_report: bool, probe: Optional[ProbeResult]) -> bool:
    """结论门: 自评与探针不一致时, 以探针为准; 无探针则不给结论(False=不算绿)。"""
    if probe is None:
        return False
    return probe.ok
