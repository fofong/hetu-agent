"""L1 · 滞回 stall 计数: 仅作 replan 触发器, 永不直接判定任务失败。"""
from __future__ import annotations


class StallCounter:
    """带滞回: 连续 N 拍无进展才触发; 一旦有进展立即清零; 触发后需显式 reset。"""

    def __init__(self, threshold: int = 3, hysteresis: int = 1):
        self.threshold = threshold
        self.hysteresis = hysteresis
        self.count = 0
        self.armed = True

    def tick(self, progress: bool) -> bool:
        """返回 True = 触发 replan(仅触发, 不裁决)。"""
        if progress:
            self.count = 0
            self.armed = True
            return False
        self.count += 1
        if self.armed and self.count >= self.threshold:
            self.armed = False
            self.count = max(0, self.threshold - self.hysteresis)
            return True
        return False

    def reset(self) -> None:
        self.armed = True
        self.count = 0
